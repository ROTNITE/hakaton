#include "MRCoreRuntime.h"
#include "MRCoreJson.h"
#include "MRCoreValues.h"
#include "MRAgent.h"
#include "MRWorld.h"
#include "Misc/Guid.h"
#include "MRExplorationScene.h"

using namespace MRCoreValues;

namespace
{
constexpr int32 MaxPacketsPerAgent=128;
constexpr double ReportTtlSeconds=30;
constexpr double AckTtlSeconds=10;
}

void FMRCoreRuntime::UpdateNetwork()
{
    Hops.Reset();Signals.Reset();
    if(DisabledInfrastructure.Contains(TEXT("rescue-base")))return;
    struct FNode {FString Id;FVector Position;double RangeCm;bool Relay=true;double Gain=1.;};
    TArray<FNode> Nodes={{TEXT("rescue-base"),World->Base,RadioRange*100}};
    if(World->bCityLayout)for(const auto& V:World->CityLayout->GetArrayField(TEXT("infrastructure")))
    {
        const auto J=V->AsObject();
        const FString Id=Text(J,TEXT("id"));
        if(Id==TEXT("rescue-base")||DisabledInfrastructure.Contains(Id))continue;
        FVector Position;
        if(!MRCoreJson::Point(Field(J,TEXT("position")),Position))continue;
        const double Range=Is(J,TEXT("range_m"),EJson::Number)?J->GetNumberField(TEXT("range_m")):RadioRange;
        if(Range>0)Nodes.Add({Id,Position*100,Range*100,Text(J,TEXT("kind"))==TEXT("relay")});
    }
    // An independent standby radio can report the failed vehicle. Its main
    // battery must still be available for forwarding another agent's packets.
    for(AMRAgent* Agent:World->Agents)if(!RadioMuted.Contains(Agent->AgentKey())&&!DisabledInfrastructure.Contains(Agent->InfrastructureSite))
        Nodes.Add({Agent->AgentKey(),Agent->GetActorLocation(),RadioRange*100,
            Agent->IsOperational()&&RelayingAgents.Contains(Agent->AgentKey())});
    if(World->bCityLayout&&Is(World->CityLayout,TEXT("competition"),EJson::Object))
        for(const auto& Value:World->CityLayout->GetObjectField(TEXT("competition"))->GetArrayField(TEXT("zones")))
        {
            if(Value->Type!=EJson::Object)continue;
            const auto Zone=Value->AsObject();
            if(Text(Zone,TEXT("type"))!=TEXT("low_connectivity")||!Is(Zone,TEXT("geometry"),EJson::Object)||
               !Is(Zone,TEXT("communication"),EJson::Object))continue;
            const auto Geometry=Zone->GetObjectField(TEXT("geometry"));FVector Min,Max;
            if(!MRCoreJson::Point(Field(Geometry,TEXT("min")),Min)||!MRCoreJson::Point(Field(Geometry,TEXT("max")),Max))continue;
            double Gain=1.;Zone->GetObjectField(TEXT("communication"))->TryGetNumberField(TEXT("quality_multiplier"),Gain);
            const FBox Bounds(Min*100,Max*100);
            for(auto& Node:Nodes)if(Bounds.IsInsideOrOn(Node.Position))Node.Gain=FMath::Min(Node.Gain,FMath::Clamp(Gain,.05,1.));
        }
    double CellWidth=100;
    for(const auto& Node:Nodes)CellWidth=FMath::Max(CellWidth,Node.RangeCm);
    const auto Cell=[&](const FVector& Position)
    {return FIntVector(FMath::FloorToInt(Position.X/CellWidth),FMath::FloorToInt(Position.Y/CellWidth),FMath::FloorToInt(Position.Z/CellWidth));};
    TMap<FIntVector,TArray<int32>> Buckets;
    for(int32 I=0;I<Nodes.Num();++I)Buckets.FindOrAdd(Cell(Nodes[I].Position)).Add(I);
    Hops.Add(Nodes[0].Id,0);Signals.Add(Nodes[0].Id,FSignal());
    TArray<int32> Queue={0};
    for(int32 Head=0;Head<Queue.Num();++Head)
    {
        const auto& From=Nodes[Queue[Head]];
        if(!From.Relay)continue;
        const int32 HopsToNode=Hops.FindChecked(From.Id);
        const FSignal Prior=Signals.FindChecked(From.Id);
        const FIntVector Center=Cell(From.Position);
        for(int32 X=-1;X<=1;++X)for(int32 Y=-1;Y<=1;++Y)for(int32 Z=-1;Z<=1;++Z)
        {
            const auto* Neighbours=Buckets.Find(Center+FIntVector(X,Y,Z));
            if(!Neighbours)continue;
            for(int32 Index:*Neighbours)
            {
                const auto& Next=Nodes[Index];
                const double Range=FMath::Min(From.RangeCm,Next.RangeCm);
                const double Gain=FMath::Min(From.Gain,Next.Gain);
                const double Ratio=FVector::DistSquared(From.Position,Next.Position)/(Gain*FMath::Square(Range));
                if(Ratio>1||Hops.Contains(Next.Id))continue;
                const double Quality=(1-.65*Ratio)*Gain;
                const double Success=1-FMath::Min(1.,RadioLoss*(2-Quality));
                Hops.Add(Next.Id,HopsToNode+1);
                Signals.Add(Next.Id,{From.Id,FMath::Min(Prior.Quality,Quality),Quality,Prior.Success*Success});
                Queue.Add(Index);
            }
        }
    }
}

bool FMRCoreRuntime::PacketLost(const FString& Agent,EPacket Kind,int64 Sequence,int32 Attempt) const
{
    const auto* Signal=Signals.Find(Agent);
    if(!Signal||Signal->Success<=0)return true;
    if(Signal->Success>=1)return false;
    const auto* A=FindAgent(Agent);
    const uint32 Owner=A?uint32(A->AgentId)+(A->bAerial?0x10000u:0):0x20000u;
    const uint32 Channel=HashCombineFast(uint32(Kind),uint32(Attempt));
    const uint32 Key=HashCombineFast(uint32(World->Seed)^0x7d6ee092u,Owner);
    FRandomStream Radio(HashCombineFast(HashCombineFast(Key,GetTypeHash(Sequence)),Channel));
    return Radio.GetFraction()>=Signal->Success;
}

void FMRCoreRuntime::QueueReport(FReport Packet)
{
    if(Packet.MessageId.IsEmpty())Packet.MessageId=FGuid::NewGuid().ToString(EGuidFormats::Digits);
    const auto* Route=Hops.Find(Packet.Agent);
    Packet.Deadline=Time()+ReportTtlSeconds;
    Packet.Due=Route?Time()+Latency*(*Route):-1;
    if(Packet.Kind==EPacket::Pose&&!Route)
    {
        const int32 Old=Reports.IndexOfByPredicate([&](const FReport& R){return R.Agent==Packet.Agent&&R.Kind==EPacket::Pose&&R.Due<0;});
        if(Old!=INDEX_NONE)
        {
            Record(TEXT("message_superseded"),Obj({{TEXT("message_id"),Str(Reports[Old].MessageId)},
                {TEXT("replacement_id"),Str(Packet.MessageId)},{TEXT("source_id"),Str(Packet.Agent)}}),false);
            RemoveReport(Old);
        }
    }
    if(ReportCounts.FindRef(Packet.Agent)>=MaxPacketsPerAgent)
    {
        const int32 Low=Packet.Kind==EPacket::Pose?INDEX_NONE:Reports.IndexOfByPredicate([&](const FReport& R)
        {return R.Agent==Packet.Agent&&R.Kind==EPacket::Pose;});
        const FString Dropped=Low==INDEX_NONE?Packet.MessageId:Reports[Low].MessageId;
        Record(TEXT("message_dropped"),Obj({{TEXT("message_id"),Str(Dropped)},{TEXT("source_id"),Str(Packet.Agent)},
            {TEXT("reason"),Str(TEXT("source_queue_full"))}}),false);
        if(Low==INDEX_NONE)return;
        RemoveReport(Low);
    }
    Packet.Data->SetStringField(TEXT("message_id"),Packet.MessageId);
    Record(TEXT("message_queued"),Obj({{TEXT("message_id"),Str(Packet.MessageId)},{TEXT("source_id"),Str(Packet.Agent)},
        {TEXT("target_id"),Packet.Target.IsEmpty()?Null():Str(Packet.Target)},{TEXT("deadline"),Num(Packet.Deadline)},
        {TEXT("initial_delivery"),Route?Num(Packet.Due):Null()},{TEXT("kind"),Num(uint8(Packet.Kind))}}),false);
    ++ReportCounts.FindOrAdd(Packet.Agent);
    TrackExplorationPacket(Packet,true);
    Reports.Add(MoveTemp(Packet));
}

void FMRCoreRuntime::RemoveReport(int32 Index)
{
    const FString Agent=Reports[Index].Agent;
    TrackExplorationPacket(Reports[Index],false);
    if(--ReportCounts.FindChecked(Agent)==0)ReportCounts.Remove(Agent);
    Reports.RemoveAt(Index);
}

void FMRCoreRuntime::QueueAck(FCommand& Command,double Delay)
{
    Command.AckDue=Time()+Delay;
    Command.AckDeadline=Time()+FMath::Max(AckTtlSeconds,Delay+.5);
    Command.AckAttempts=0;
}

void FMRCoreRuntime::UpdateFreshnessEvents()
{
    for(const auto& Pair:KnownAgents)
    {
        const auto Stamp=Pair.Value->GetObjectField(TEXT("freshness"))->GetObjectField(TEXT("position"));
        const double Observed=Stamp->GetNumberField(TEXT("observed_at")),Age=Time()-Observed;
        auto* Existing=StaleAlerts.Find(Pair.Key);
        if((Age>5)==(Existing!=nullptr))continue;
        const FStaleAlert Alert=Existing?*Existing:FStaleAlert{FGuid::NewGuid().ToString(EGuidFormats::Digits),Time()};
        const FString State=Existing?TEXT("resolved"):TEXT("active");
        auto Parameters=Obj({{TEXT("observed_at"),Num(Observed)},{TEXT("age_s"),Num(Age)},
            {TEXT("threshold_s"),Num(5)},{TEXT("basis"),Str(TEXT("received_pose_timeout"))}});
        PublishEvent(Alert.Id+TEXT("-freshness"),TEXT("stale_information"),Alert.StartedAt,TEXT("rescue-base"),{Pair.Key},Parameters,State);
        PublishEvent(Alert.Id+TEXT("-connectivity"),TEXT("connectivity_loss"),Alert.StartedAt,TEXT("rescue-base"),{Pair.Key},Parameters,State);
        if(Existing)StaleAlerts.Remove(Pair.Key);else StaleAlerts.Add(Pair.Key,Alert);
    }
}

void FMRCoreRuntime::UpdateAgentKnowledge(const FString& Agent,const Object& Report,const TSharedPtr<FMRSceneActorReport>& Visual)
{
    const auto Previous=KnownAgents.FindChecked(Agent);
    const double Observed=Report->GetObjectField(TEXT("freshness"))->GetObjectField(TEXT("position"))->GetNumberField(TEXT("observed_at"));
    const double Old=Previous->GetObjectField(TEXT("freshness"))->GetObjectField(TEXT("position"))->GetNumberField(TEXT("observed_at"));
    if(Observed<Old)return;
    auto Copy=MRCoreJson::Copy(Report);
    for(auto& Group:Copy->GetObjectField(TEXT("freshness"))->Values)Group.Value->AsObject()->SetNumberField(TEXT("received_at"),Time());
    KnownAgents.Add(Agent,Copy);AgentReceived.Add(Agent,Time());
    if(ExplorationScene)ExplorationScene->ApplyActors(Visual);
    const FString Message=Text(Report,TEXT("message_id"));
    if(!Message.IsEmpty())Record(TEXT("message_delivered"),Obj({{TEXT("message_id"),Str(Message)},
        {TEXT("source_id"),Str(Agent)},{TEXT("observed_at"),Num(Observed)},{TEXT("received_at"),Num(Time())},
        {TEXT("payload"),Json(Copy)}}));
    if(Text(Copy,TEXT("status"))==TEXT("failed")&&Text(Previous,TEXT("status"))!=TEXT("failed"))
        PublishEvent(FGuid::NewGuid().ToString(EGuidFormats::Digits),TEXT("agent_failure"),Observed,Agent,{Agent},
            Obj({{TEXT("reason"),Field(Copy->GetObjectField(TEXT("physical")),TEXT("stop_reason"))},
                {TEXT("basis"),Str(TEXT("delivered_agent_state"))}}));
    const auto Physical=Copy->GetObjectField(TEXT("physical"));
    const bool Degraded=Physical->GetNumberField(TEXT("speed_factor"))<1||Physical->GetNumberField(TEXT("sensor_factor"))<1;
    auto* Existing=DegradationAlerts.Find(Agent);
    if(Degraded!=(Existing!=nullptr))
    {
        const FStaleAlert Alert=Existing?*Existing:FStaleAlert{FGuid::NewGuid().ToString(EGuidFormats::Digits),Observed};
        PublishEvent(Alert.Id,TEXT("agent_degradation"),Alert.StartedAt,Agent,{Agent},
            Obj({{TEXT("speed_factor"),Field(Physical,TEXT("speed_factor"))},{TEXT("sensor_factor"),Field(Physical,TEXT("sensor_factor"))}}),
            Degraded?TEXT("active"):TEXT("resolved"));
        if(Degraded)DegradationAlerts.Add(Agent,Alert);else DegradationAlerts.Remove(Agent);
    }
}
