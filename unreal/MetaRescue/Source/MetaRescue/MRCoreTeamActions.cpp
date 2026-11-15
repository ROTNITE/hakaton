#include "MRCoreRuntime.h"
#include "MRCoreValues.h"
#include "MRWorld.h"
#include "MRAgent.h"
#include "Components/BoxComponent.h"

using namespace MRCoreValues;

void FMRCoreRuntime::ResetTeamActions()
{
    LastRelaySequence.Reset();RelayingAgents.Reset();MedicalKits.Reset();ReceivedKits.Reset();Inboxes.Reset();
    const bool ExplicitRelay=World->bCityLayout&&Is(World->CityLayout,TEXT("explicit_mobile_relay"),EJson::Boolean)&&
        World->CityLayout->GetBoolField(TEXT("explicit_mobile_relay"));
    for(const AMRAgent* Agent:World->Agents)
    {
        const FString Id=Agent->AgentKey();
        if(!ExplicitRelay&&Agent->IsSpatial())RelayingAgents.Add(Id);
        if(Agent->CanCarry()||Agent->MediumLimits.IsValid)MedicalKits.Add(Id,3);
    }
}

bool FMRCoreRuntime::KnownRecipient(const FString& Id) const
{
    if(Id==TEXT("rescue-base")||KnownAgents.Contains(Id))return true;
    if(!World->bCityLayout)return false;
    return World->CityLayout->GetArrayField(TEXT("infrastructure")).ContainsByPredicate([&](const Value& Entry)
        {return Text(Entry->AsObject(),TEXT("id"))==Id;});
}

bool FMRCoreRuntime::DeliverAid(FCommand& Command,AMRAgent* Agent)
{
    const int32 Target=FindTarget(Text(Command.Parameters,TEXT("target_id")));
    const int32 Amount=Command.Parameters->GetIntegerField(TEXT("amount"));
    auto* Stock=MedicalKits.Find(Command.Agent);
    if(!Stock||*Stock<Amount||!World->Targets.IsValidIndex(Target))return false;
    const auto& Person=World->Targets[Target];
    const int32 Received=ReceivedKits.FindRef(Target);
    if(Person.bRescued||Person.bAssigned||Time()+1.e-9<Person.AvailableAt||Received+Amount>3||
        Agent->bCarrying||Agent->IsCharging()||(!Agent->bExternalHold&&!Agent->RouteFinished())||
        Agent->Body->GetPhysicsLinearVelocity().Size()>30||
        FVector::Dist(Agent->GetActorLocation(),Person.Position)>370)return false;
    FCollisionQueryParams Query;Query.AddIgnoredActor(Agent);FHitResult Hit;
    if(World->GetWorld()->LineTraceSingleByChannel(Hit,Agent->GetActorLocation(),Person.Position+FVector(0,0,60),ECC_Visibility,Query))
        return false;
    *Stock-=Amount;ReceivedKits.Add(Target,Received+Amount);
    Command.TargetIndex=Target;Command.FinalStatus=TEXT("completed");
    Record(TEXT("aid_transferred"),Obj({{TEXT("command_id"),Str(Command.Key)},{TEXT("agent_id"),Str(Command.Agent)},
        {TEXT("target_id"),Field(Command.Parameters,TEXT("target_id"))},{TEXT("resource_id"),Str(TEXT("medical_kits"))},
        {TEXT("amount"),Num(Amount)},{TEXT("remaining"),Num(*Stock)},{TEXT("total_received"),Num(Received+Amount)},
        {TEXT("position"),Point(Person.Position/100.)}}),false);
    return true;
}

void FMRCoreRuntime::ProgressMessage(FCommand& Command)
{
    const auto Finish=[&](const FString& Status,const FString& Reason)
    {
        Command.FinalStatus=Status;Command.Reason=Reason;
        QueueAck(Command,Latency*FMath::Max(1,Hops.FindRef(Command.Agent)));
    };
    if(Time()+1.e-9>=Command.MessageDeadline)
    {
        Finish(TEXT("failed"),TEXT("message_ttl"));
        Record(TEXT("peer_message_expired"),Obj({{TEXT("message_id"),Str(Command.Key)}}),false);
        return;
    }
    const auto* Sender=Hops.Find(Command.Agent);
    const auto* Recipient=Hops.Find(Command.Recipient);
    if(!Sender||!Recipient){Command.MessageDue=-1;return;}
    const double Delay=Latency*(*Sender+*Recipient);
    if(Command.MessageDue<0)Command.MessageDue=Time()+Delay;
    if(Time()+1.e-9<Command.MessageDue)return;
    const int32 Attempt=Command.MessageAttempts++;
    if(PacketLost(Command.Agent,EPacket::Message,Command.Sequence,Attempt)||
       PacketLost(Command.Recipient,EPacket::Message,Command.Sequence,Attempt))
    {
        Command.MessageDue=Time()+.25+Delay;
        Record(TEXT("peer_message_dropped"),Obj({{TEXT("message_id"),Str(Command.Key)},{TEXT("attempt"),Num(Attempt+1)}}),false);
        return;
    }
    auto Message=Obj({{TEXT("message_id"),Str(Command.Key)},{TEXT("sender_id"),Str(Command.Agent)},
        {TEXT("recipient_id"),Str(Command.Recipient)},{TEXT("received_at"),Num(Time())},
        {TEXT("hops"),Num(*Sender+*Recipient)},{TEXT("payload"),Field(Command.Parameters,TEXT("payload"))}});
    auto& Inbox=Inboxes.FindOrAdd(Command.Recipient);
    if(Inbox.Num()>=128)
    {
        Record(TEXT("peer_inbox_eviction"),Obj({{TEXT("recipient_id"),Str(Command.Recipient)},
            {TEXT("message_id"),Field(Inbox[0],TEXT("message_id"))}}),false);
        Inbox.RemoveAt(0);
    }
    Inbox.Add(Message);
    Record(TEXT("peer_message_delivered"),Message,false);
    Finish(TEXT("completed"),TEXT(""));
}
