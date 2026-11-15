#include "MRCoreRuntime.h"
#include "MRCoreValues.h"
#include "MRAgent.h"
#include "MRWorld.h"
#include "Components/BoxComponent.h"

using namespace MRCoreValues;

namespace
{
constexpr int32 RecentCapacity=64;
constexpr int32 MaximumWindows=48;
constexpr double ContextSeconds=.5;

FName StopTag(const AMRAgent& Agent)
{
    if(Agent.StopReason==TEXT("yield_to_vehicle"))return TEXT("yield_to_vehicle");
    if(Agent.StopReason==TEXT("obstacle_on_route")||Agent.StopReason==TEXT("medium_obstacle"))
        return TEXT("obstacle_on_route");
    if(Agent.StopReason==TEXT("hazard_on_route")||Agent.StopReason==TEXT("restricted_volume"))
        return TEXT("hazard_on_route");
    return NAME_None;
}
}

void FMRCoreRuntime::TrackSubsteps()
{
    for(const AMRAgent* Agent:World->Agents)
    {
        if(!Agent->CanMove())continue;
        if(SubstepWindowsStarted>=MaximumWindows)
        {
            const auto* Existing=Substeps.Find(Agent->AgentKey());
            if(!Existing||Existing->Window.IsEmpty())continue;
        }
        const FString Id=Agent->AgentKey();
        auto& Trace=Substeps.FindOrAdd(Id);
        const FSubstepSample Current{Time(),Agent->Energy,Agent->GetActorLocation()/100.,
            Agent->Body->GetPhysicsLinearVelocity()/100.,Agent->IntendedVelocity/100.,
            StopTag(*Agent),Agent->AgentContacts,Agent->bCarrying,Agent->IsOperational()};
        if(!Trace.Recent.IsEmpty()&&Trace.Window.IsEmpty()&&SubstepWindowsStarted<MaximumWindows)
        {
            const auto& Prior=Trace.Recent[(Trace.Cursor+RecentCapacity-1)%RecentCapacity];
            FString Trigger;
            if(!Current.Operational&&Prior.Operational)Trigger=TEXT("agent_became_inoperable");
            else if(Current.Contacts>Prior.Contacts)Trigger=TEXT("vehicle_contact");
            else if(!Current.Stop.IsNone()&&Current.Stop!=Prior.Stop)Trigger=Current.Stop.ToString();
            if(!Trigger.IsEmpty())
            {
                Trace.TriggerAt=Current.At;
                Trace.Reason=MoveTemp(Trigger);
                Trace.Command=Agent->CommandId;
                Trace.Window.Reserve(RecentCapacity*2);
                const int32 Oldest=Trace.Recent.Num()==RecentCapacity?Trace.Cursor:0;
                for(int32 I=0;I<Trace.Recent.Num();++I)
                {
                    const auto& Sample=Trace.Recent[(Oldest+I)%RecentCapacity];
                    if(Sample.At>=Current.At-ContextSeconds)Trace.Window.Add(Sample);
                }
                ++SubstepWindowsStarted;
            }
        }
        if(!Trace.Window.IsEmpty())
        {
            Trace.Window.Add(Current);
            if(Current.At>=Trace.TriggerAt+ContextSeconds||Trace.Window.Num()>=RecentCapacity*2)
                RecordSubstepWindow(Id,Trace,Current.At<Trace.TriggerAt+ContextSeconds);
        }
        if(Trace.Recent.Num()<RecentCapacity)Trace.Recent.Add(Current);
        else Trace.Recent[Trace.Cursor]=Current;
        Trace.Cursor=(Trace.Cursor+1)%RecentCapacity;
    }
}

void FMRCoreRuntime::RecordSubstepWindow(const FString& Agent,FSubstepWindow& Trace,bool Truncated)
{
    TArray<Value> Samples;
    Samples.Reserve(Trace.Window.Num());
    for(const auto& Row:Trace.Window)Samples.Add(Json(Obj({
        {TEXT("time_s"),Num(Row.At)},{TEXT("position_m"),Point(Row.Position)},
        {TEXT("velocity_m_s"),Point(Row.Velocity)},{TEXT("intended_velocity_m_s"),Point(Row.Intended)},
        {TEXT("energy_wh"),Num(Row.Energy)},{TEXT("carrying"),Bool(Row.Carrying)},
        {TEXT("operational"),Bool(Row.Operational)},{TEXT("vehicle_contacts"),Num(Row.Contacts)},
        {TEXT("stop_reason"),Row.Stop.IsNone()?Null():Str(Row.Stop.ToString())}})));
    Record(TEXT("substep_trace"),Obj({{TEXT("agent_id"),Str(Agent)},
        {TEXT("trigger"),Str(Trace.Reason)},{TEXT("trigger_at_s"),Num(Trace.TriggerAt)},
        {TEXT("command_id"),Trace.Command.IsEmpty()?Null():Str(Trace.Command)},
        {TEXT("truncated"),Bool(Truncated)},{TEXT("samples"),Arr(Samples)}}),false);
    Trace.Window.Reset();
}

void FMRCoreRuntime::FlushSubstepWindows()
{
    for(auto& Trace:Substeps)
        if(!Trace.Value.Window.IsEmpty())RecordSubstepWindow(Trace.Key,Trace.Value,true);
}
