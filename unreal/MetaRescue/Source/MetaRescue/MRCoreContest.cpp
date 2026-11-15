#include "MRCoreRuntime.h"
#include "MRCoreJson.h"
#include "MRCoreValues.h"
#include "MRAgent.h"
#include "MRWorld.h"

using namespace MRCoreValues;

namespace
{
const TSet<FString> Temporary={TEXT("agent_degradation"),TEXT("infrastructure_failure"),TEXT("connectivity_loss"),
    TEXT("operator_directive"),TEXT("restricted_zone_appeared")};
const TSet<FString> Permanent={TEXT("agent_failure"),TEXT("mission_priority_change"),TEXT("resource_shortage"),TEXT("contradictory_information")};

bool Number(const Object& Row,const FString& Key,double Low,double High)
{
    if(!Is(Row,Key,EJson::Number))return false;
    const double Value=Row->GetNumberField(Key);
    return FMath::IsFinite(Value)&&Value>=Low&&Value<=High;
}

bool Identifier(const FString& Value)
{
    if(Value.IsEmpty()||Value.Len()>100)return false;
    for(const TCHAR Char:Value)if(Char<32)return false;
    return true;
}

TArray<Value> SubjectValues(const TArray<FString>& Subjects)
{
    TArray<Value> Values;
    for(const FString& Subject:Subjects)Values.Add(Str(Subject));
    return Values;
}

Object PublicRestriction(const FString& Id,const Object& Parameters)
{
    const auto Bounds=Parameters->GetObjectField(TEXT("bounds"));
    return Obj({{TEXT("id"),Str(Id)},{TEXT("type"),Str(TEXT("restricted"))},{TEXT("risk"),Num(1)},
        {TEXT("geometry"),Json(Obj({{TEXT("type"),Str(TEXT("box"))},{TEXT("min"),Field(Bounds,TEXT("min"))},
            {TEXT("max"),Field(Bounds,TEXT("max"))}}))},
        {TEXT("access"),Json(Obj({{TEXT("allowed_kinds"),Field(Parameters,TEXT("allowed_kinds"))}}))},
        {TEXT("cost"),Json(Obj())},{TEXT("communication"),Json(Obj())},{TEXT("constraints"),Arr({})}});
}
}

bool FMRCoreRuntime::LoadContestTape()
{
    if(!World->bCityLayout||!World->CityLayout->HasField(TEXT("disturbances")))return true;
    auto Fail=[](const FString& Message)
    {UE_LOG(LogTemp,Error,TEXT("MR_CORE invalid contest disturbances: %s"),*Message);return false;};
    if(!Is(World->CityLayout,TEXT("disturbances"),EJson::Object))return Fail(TEXT("expected object"));
    const auto Script=World->CityLayout->GetObjectField(TEXT("disturbances"));
    if(Script->Values.Num()!=2||Text(Script,TEXT("format"))!=TEXT("metarescue.disturbances.v1")||!Is(Script,TEXT("events"),EJson::Array))
        return Fail(TEXT("invalid format"));
    const auto& Events=Script->GetArrayField(TEXT("events"));
    if(Events.Num()>256)return Fail(TEXT("event limit exceeded"));
    TSet<FString> Ids,Infrastructure;
    for(const auto& Row:World->CityLayout->GetArrayField(TEXT("infrastructure")))Infrastructure.Add(Text(Row->AsObject(),TEXT("id")));
    const auto Bounds=World->CityLayout->GetObjectField(TEXT("bounds"));
    FVector MapMin,MapMax;
    if(!MRCoreJson::Point(Field(Bounds,TEXT("min")),MapMin)||!MRCoreJson::Point(Field(Bounds,TEXT("max")),MapMax))
        return Fail(TEXT("invalid map bounds"));
    const FBox Map(MapMin,MapMax);
    double Previous=-1;
    for(const auto& Entry:Events)
    {
        if(Entry->Type!=EJson::Object)return Fail(TEXT("invalid row"));
        const auto Row=Entry->AsObject();
        FContestEvent Event;
        Event.Id=Text(Row,TEXT("id"));Event.Type=Text(Row,TEXT("type"));Event.Source=Text(Row,TEXT("source"));
        const bool Timed=Temporary.Contains(Event.Type);
        if(Row->Values.Num()!=7||!Identifier(Event.Id)||Ids.Contains(Event.Id)||!Identifier(Event.Source)||
           (!Timed&&!Permanent.Contains(Event.Type))||!Number(Row,TEXT("time"),FMath::Max(0.,Previous),Horizon)||
           !Is(Row,TEXT("targets"),EJson::Array)||!Is(Row,TEXT("parameters"),EJson::Object))return Fail(Event.Id+TEXT(" invalid header"));
        Event.At=Row->GetNumberField(TEXT("time"));Previous=Event.At;
        if(Timed)
        {
            if(!Number(Row,TEXT("until"),Event.At,Horizon))return Fail(Event.Id+TEXT(" invalid expiry"));
            Event.Until=Row->GetNumberField(TEXT("until"));if(Event.Until<=Event.At)return Fail(Event.Id+TEXT(" empty duration"));
        }
        else if(!Is(Row,TEXT("until"),EJson::Null))return Fail(Event.Id+TEXT(" unexpected expiry"));
        for(const auto& Subject:Row->GetArrayField(TEXT("targets")))
        {
            if(Subject->Type!=EJson::String||!Identifier(Subject->AsString())||Event.Subjects.Contains(Subject->AsString()))
                return Fail(Event.Id+TEXT(" invalid subject"));
            Event.Subjects.Add(Subject->AsString());
        }
        const auto P=Row->GetObjectField(TEXT("parameters"));Event.Parameters=P;
        const FString Kind=Event.Type;
        bool Valid=false;
        if(Kind==TEXT("restricted_zone_appeared")&&Event.Subjects.IsEmpty()&&P->Values.Num()==2&&
           Is(P,TEXT("bounds"),EJson::Object)&&Is(P,TEXT("allowed_kinds"),EJson::Array))
        {
            const auto Box=P->GetObjectField(TEXT("bounds"));FVector Min,Max;
            Valid=Box->Values.Num()==2&&MRCoreJson::Point(Field(Box,TEXT("min")),Min)&&MRCoreJson::Point(Field(Box,TEXT("max")),Max)&&
                Map.IsInsideOrOn(Min)&&Map.IsInsideOrOn(Max)&&Min.X<Max.X&&Min.Y<Max.Y&&Min.Z<Max.Z;
            static const TSet<FString> Kinds={TEXT("ground"),TEXT("aerial"),TEXT("underground"),TEXT("surface_water"),
                TEXT("underwater"),TEXT("infrastructure"),TEXT("digital"),TEXT("operator")};
            TSet<FString> Seen;
            for(const auto& Value:P->GetArrayField(TEXT("allowed_kinds")))
            {
                if(Value->Type!=EJson::String||!Kinds.Contains(Value->AsString())||Seen.Contains(Value->AsString())){Valid=false;break;}
                Seen.Add(Value->AsString());
            }
        }
        else if(Kind==TEXT("connectivity_loss")&&!Event.Subjects.IsEmpty())
        {
            Valid=P->Values.Num()==1&&Identifier(Text(P,TEXT("reason")));
            for(const auto& Id:Event.Subjects)Valid&=FindAgent(Id)!=nullptr;
        }
        else if(Event.Subjects.Num()==1)
        {
            const FString Id=Event.Subjects[0];
            if(Kind==TEXT("agent_failure"))Valid=FindAgent(Id)&&P->Values.Num()==1&&Identifier(Text(P,TEXT("reason")));
            else if(Kind==TEXT("agent_degradation"))Valid=FindAgent(Id)&&P->Values.Num()==2&&
                Number(P,TEXT("speed_factor"),.1,1)&&Number(P,TEXT("sensor_factor"),0,1);
            else if(Kind==TEXT("operator_directive"))Valid=FindAgent(Id)&&P->Values.Num()==2&&
                Text(P,TEXT("action"))==TEXT("hold")&&Identifier(Text(P,TEXT("reason")));
            else if(Kind==TEXT("infrastructure_failure"))Valid=Infrastructure.Contains(Id)&&P->Values.Num()==1&&Identifier(Text(P,TEXT("reason")));
            else if(Kind==TEXT("resource_shortage"))Valid=ChargingStations.Contains(Id)&&P->Values.Num()==1&&Number(P,TEXT("remaining_wh"),0,1.e8);
            else if(Kind==TEXT("mission_priority_change")&&FindTarget(Id)!=INDEX_NONE&&P->Values.Num()==1&&Number(P,TEXT("priority"),1,3))
                Valid=P->GetNumberField(TEXT("priority"))==FMath::FloorToDouble(P->GetNumberField(TEXT("priority")));
            else if(Kind==TEXT("contradictory_information")&&FindTarget(Id)!=INDEX_NONE&&P->Values.Num()==2&&Number(P,TEXT("confidence"),0,1))
            {
                FVector Position;Valid=MRCoreJson::Point(Field(P,TEXT("position")),Position)&&Map.IsInsideOrOn(Position);
            }
        }
        if(!Valid)return Fail(Event.Id+TEXT(" invalid parameters or subject"));
        Ids.Add(Event.Id);ContestTape.Add(MoveTemp(Event));
    }
    for(const auto& Target:World->Targets)InitialPriorities.Add(Target.Id,Target.Priority);
    return true;
}

void FMRCoreRuntime::ResetContest()
{
    NextContest=0;ActiveContest.Reset();RadioMuted.Reset();DisabledInfrastructure.Reset();
    Directives.Reset();Conflicts.Reset();World->CoreRestrictions.Reset();
    for(auto& Target:World->Targets)if(const auto* Priority=InitialPriorities.Find(Target.Id))Target.Priority=*Priority;
}

double FMRCoreRuntime::NextContestBoundary() const
{
    double Next=ContestTape.IsValidIndex(NextContest)?ContestTape[NextContest].At:-1;
    for(int32 Index:ActiveContest)
    {
        const double End=ContestTape[Index].Until;
        if(Next<0||End<Next)Next=End;
    }
    return Next;
}

void FMRCoreRuntime::AdvanceContest()
{
    bool Refresh=false;
    while(ContestTape.IsValidIndex(NextContest)&&ContestTape[NextContest].At<=Time()+1.e-9)
    {
        const int32 Index=NextContest++;
        const auto& E=ContestTape[Index];const auto P=E.Parameters;
        const FString Subject=E.Subjects.IsEmpty()?FString():E.Subjects[0];
        Record(TEXT("contest_event_started"),Obj({{TEXT("id"),Str(E.Id)},{TEXT("type"),Str(E.Type)},
            {TEXT("scheduled_at"),Num(E.At)},{TEXT("source"),Str(E.Source)},{TEXT("targets"),Arr(SubjectValues(E.Subjects))},
            {TEXT("parameters"),Json(P)}}),false);
        if(E.Until>=0){ActiveContest.Add(Index);Refresh=true;}
        if(E.Type==TEXT("agent_failure"))
        {
            auto* Agent=FindAgent(Subject);Agent->bFaulted=true;
            const int32 Released=Agent->StopAndRelease(Text(P,TEXT("reason")));
            const auto* Target=World->Targets.IsValidIndex(Released)?&World->Targets[Released]:nullptr;
            Record(TEXT("agent_fault_effect"),Obj({{TEXT("event_id"),Str(E.Id)},{TEXT("agent_id"),Str(Subject)},
                {TEXT("position"),Point(Agent->GetActorLocation()/100.)},
                {TEXT("released_target"),Target?Str(FString::Printf(TEXT("person-%d"),Target->Id)):Null()},
                {TEXT("target_position"),Target?Point(Target->Position/100.):Null()}}),false);
            Refresh=true;
        }
        else if(E.Type==TEXT("infrastructure_failure"))
            PublishEvent(E.Id,E.Type,E.At,E.Source,E.Subjects,P,TEXT("active"));
        else if(E.Type==TEXT("mission_priority_change"))
        {
            auto& Target=World->Targets[FindTarget(Subject)];Target.Priority=P->GetNumberField(TEXT("priority"))/3.;
            if(auto* Known=KnownTargets.Find(Subject))
            {
                auto Copy=MRCoreJson::Copy(*Known);Copy->SetNumberField(TEXT("priority"),Target.Priority);
                Copy->SetNumberField(TEXT("priority_updated_at"),Time());KnownTargets.Add(Subject,Copy);
                PublishEvent(E.Id,E.Type,E.At,E.Source,E.Subjects,P);
            }
        }
        else if(E.Type==TEXT("operator_directive"))
        {
            const auto Order=Obj({{TEXT("id"),Str(E.Id)},{TEXT("action"),Field(P,TEXT("action"))},{TEXT("agent_id"),Str(Subject)},
                {TEXT("source"),Str(E.Source)},{TEXT("issued_at"),Num(E.At)},{TEXT("expires_at"),Num(E.Until)},
                {TEXT("reason"),Field(P,TEXT("reason"))}});
            Directives.Add(E.Id,Order);PublishEvent(E.Id,E.Type,E.At,E.Source,E.Subjects,Order,TEXT("active"));
        }
        else if(E.Type==TEXT("restricted_zone_appeared"))
        {
            const FString Zone=TEXT("restriction-")+E.Id;const auto Box=P->GetObjectField(TEXT("bounds"));
            FVector Min,Max;MRCoreJson::Point(Field(Box,TEXT("min")),Min);MRCoreJson::Point(Field(Box,TEXT("max")),Max);
            FMRRestriction Region;Region.Bounds=FBox(Min*100,Max*100);
            for(const auto& Kind:P->GetArrayField(TEXT("allowed_kinds")))
                Region.AllowedKinds.Add(Kind->AsString());
            World->CoreRestrictions.Add(Zone,Region);KnownZones.Add(Zone,PublicRestriction(Zone,P));
            PublishEvent(E.Id,E.Type,E.At,E.Source,{Zone},P,TEXT("active"));
        }
        else if(E.Type==TEXT("resource_shortage"))
        {
            auto& Station=ChargingStations.FindChecked(Subject);const double Before=Station.EnergyWh;
            Station.EnergyWh=FMath::Min(Before,P->GetNumberField(TEXT("remaining_wh")));
            PublishEvent(E.Id,E.Type,E.At,E.Source,E.Subjects,Obj({{TEXT("resource"),Str(TEXT("energy"))},
                {TEXT("withdrawn_wh"),Num(Before-Station.EnergyWh)},{TEXT("remaining_wh"),Num(Station.EnergyWh)}}),TEXT("active"));
        }
        else if(E.Type==TEXT("contradictory_information"))
        {
            const auto* Known=KnownTargets.Find(Subject);
            FVector Claimed,Observed;
            if(Known&&MRCoreJson::Point(Field(*Known,TEXT("position")),Observed)&&MRCoreJson::Point(Field(P,TEXT("position")),Claimed)&&
               FVector::Dist(Observed,Claimed)>.5)
            {
                const auto Conflict=Obj({{TEXT("id"),Str(E.Id)},{TEXT("target_id"),Str(Subject)},{TEXT("source"),Str(E.Source)},
                    {TEXT("time"),Num(E.At)},{TEXT("position"),Point(Claimed)},{TEXT("known_position"),Point(Observed)},
                    {TEXT("confidence"),Field(P,TEXT("confidence"))},{TEXT("source_trust"),Num(.35)}});
                Conflicts.Add(E.Id,Conflict);PublishEvent(E.Id,E.Type,E.At,E.Source,E.Subjects,Conflict,TEXT("active"),P->GetNumberField(TEXT("confidence")));
            }
        }
    }
    for(int32 I=ActiveContest.Num()-1;I>=0;--I)
    {
        const auto& E=ContestTape[ActiveContest[I]];
        if(E.Until>Time()+1.e-9)continue;
        Record(TEXT("contest_event_ended"),Obj({{TEXT("id"),Str(E.Id)},{TEXT("type"),Str(E.Type)},{TEXT("scheduled_at"),Num(E.Until)}}),false);
        if(E.Type==TEXT("restricted_zone_appeared"))
        {
            const FString Zone=TEXT("restriction-")+E.Id;
            World->CoreRestrictions.Remove(Zone);KnownZones.Remove(Zone);
            PublishEvent(E.Id,E.Type,E.At,E.Source,{Zone},E.Parameters,TEXT("resolved"));
        }
        else if(E.Type==TEXT("operator_directive")||E.Type==TEXT("infrastructure_failure"))
        {
            Directives.Remove(E.Id);PublishEvent(E.Id,E.Type,E.At,E.Source,E.Subjects,E.Parameters,TEXT("resolved"));
        }
        ActiveContest.RemoveAt(I);Refresh=true;
    }
    if(!Refresh)return;
    RadioMuted.Reset();DisabledInfrastructure.Reset();
    for(AMRAgent* Agent:World->Agents)Agent->SpeedFactor=Agent->SensorFactor=1;
    for(int32 Index:ActiveContest)
    {
        const auto& E=ContestTape[Index];
        if(E.Type==TEXT("connectivity_loss"))for(const auto& Agent:E.Subjects)RadioMuted.Add(Agent);
        else if(E.Type==TEXT("infrastructure_failure"))DisabledInfrastructure.Add(E.Subjects[0]);
        else if(E.Type==TEXT("agent_degradation"))
        {
            auto* Agent=FindAgent(E.Subjects[0]);
            Agent->SpeedFactor=FMath::Min(Agent->SpeedFactor,float(E.Parameters->GetNumberField(TEXT("speed_factor"))));
            Agent->SensorFactor=FMath::Min(Agent->SensorFactor,float(E.Parameters->GetNumberField(TEXT("sensor_factor"))));
        }
    }
    UpdateNetwork();
}

void FMRCoreRuntime::ResolveConflicts(const FString& Target,const FString& Source,double ObservedAt)
{
    for(auto It=Conflicts.CreateIterator();It;++It)
    {
        const auto Conflict=It.Value();
        if(Text(Conflict,TEXT("target_id"))!=Target||ObservedAt<Conflict->GetNumberField(TEXT("time")))continue;
        auto Resolution=MRCoreJson::Copy(Conflict);Resolution->SetStringField(TEXT("verified_by"),Source);
        PublishEvent(It.Key(),TEXT("contradictory_information"),Conflict->GetNumberField(TEXT("time")),Text(Conflict,TEXT("source")),
            {Target},Resolution,TEXT("resolved"));It.RemoveCurrent();
    }
}
