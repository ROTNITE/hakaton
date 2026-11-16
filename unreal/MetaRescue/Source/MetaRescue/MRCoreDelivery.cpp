#include "MRCoreRuntime.h"
#include "MRCoreValues.h"
#include "MRCoreJson.h"
#include "MRWorld.h"
#include "MRAgent.h"
#include "Components/BoxComponent.h"
#include "Engine/World.h"
#include "MRExplorationScene.h"

using namespace MRCoreValues;

namespace
{
void TargetSupport(const AMRWorld* World,const FMRTarget& Target,const Object& Report)
{
    if(!Target.FloatBody)return;
    const auto* Carrier=Target.SupportCarrier.Get();
    const bool Afloat=!Target.bRescued&&(Carrier?Carrier->bRescueWatercraft:Target.ShoreStation.IsEmpty()&&World->WaterDepth(Target.Position)>35);
    Report->SetStringField(TEXT("access_medium"),Afloat?TEXT("surface_water"):TEXT("ground"));
    Report->SetStringField(TEXT("support"),Target.bRescued?TEXT("medical_base"):Carrier?TEXT("carrier"):!Target.ShoreStation.IsEmpty()?TEXT("shore_platform"):
        Target.FloatDisplacedM3>.03?TEXT("floating_stretcher"):TEXT("ground"));
    Report->SetField(TEXT("transfer_station_id"),Target.ShoreStation.IsEmpty()?Null():Str(Target.ShoreStation));
    Report->SetField(TEXT("supported_by_agent"),Carrier?Str(Carrier->AgentKey()):Null());
    Report->SetField(TEXT("velocity_m_s"),Point((Carrier?Carrier->Body->GetPhysicsLinearVelocity():Target.FloatBody->GetPhysicsLinearVelocity())/100));
}
}

void FMRCoreRuntime::GatherReports()
{
    for(AMRAgent* A:World->Agents)
    {
        const FString Agent=A->AgentKey();
        FReport Pose;Pose.Agent=Agent;Pose.Data=AgentSnapshot(A,Time());Pose.Sequence=SensorSamples;
        if(ExplorationScene)Pose.ActorScene=ExplorationScene->CaptureActor(A,Time());
        QueueReport(MoveTemp(Pose));
        if(!A->IsOperational()||!A->CanSense()||DisabledInfrastructure.Contains(A->InfrastructureSite))continue;
        GatherExplorationReport(A);
        GatherHazardReport(A);
        for(int32 Index=0;Index<World->Targets.Num();Index++)
        {
            const auto& T=World->Targets[Index];
            const double Distance=A->MediumLimits.IsValid?FVector::Dist(A->GetActorLocation(),T.Position):FVector::Dist2D(A->GetActorLocation(),T.Position);
            if(Time()+1.e-9<T.AvailableAt||T.bRescued||T.bAssigned||Distance>SensorRadius.FindRef(Agent)*100)continue;
            FCollisionQueryParams Query;Query.AddIgnoredActor(A);FHitResult Hit;
            const FVector SensorPoint=T.Position+FVector(0,0,60-T.VisualAnchorOffsetCm);
            if(World->GetWorld()->LineTraceSingleByChannel(Hit,A->GetActorLocation(),SensorPoint,ECC_Visibility,Query))continue;
            const FString Target=FString::Printf(TEXT("person-%d"),T.Id);
            const auto Known=KnownTargets.FindRef(Target);
            if(Known&&T.bDiscovered)
            {
                if(!T.FloatBody)continue;
                FVector Last;MRCoreJson::Point(Field(Known,TEXT("position")),Last);
                const bool Afloat=T.SupportCarrier.IsValid()?T.SupportCarrier->bRescueWatercraft:T.ShoreStation.IsEmpty()&&World->WaterDepth(T.Position)>35;
                if(Time()-Known->GetNumberField(TEXT("observed_at"))<1||
                   (FVector::Dist(Last*100,T.Position)<50&&Text(Known,TEXT("access_medium"))==(Afloat?TEXT("surface_water"):TEXT("ground"))))continue;
            }
            if(Reports.ContainsByPredicate([&](const FReport& R){return R.Agent==Agent&&R.Target==Target&&R.TargetEpoch==T.ObservationEpoch;}))continue;
            const float Quality=SensorQuality(A->GetActorLocation(),SensorPoint);
            const bool Detected=SensorAccepts(A,T.Id,Quality,0);
            if(Quality<1||SensorReliability<1||A->SensorFactor<1)
                Record(TEXT("sensor_trial"),Obj({{TEXT("agent_id"),Str(Agent)},{TEXT("target_id"),Str(Target)},
                    {TEXT("visibility"),Num(Quality)},{TEXT("detected"),Bool(Detected)}}),false);
            if(!Detected)continue;
            FReport Report;Report.Agent=Agent;Report.Target=Target;Report.TargetEpoch=T.ObservationEpoch;Report.Kind=EPacket::Target;
            Report.Sequence=SensorSamples*65536+T.Id;
            Report.Data=Obj({{TEXT("id"),Str(Target)},{TEXT("kind"),Str(TEXT("person"))},
                {TEXT("status"),Str(Known&&T.bDiscovered&&Text(Known,TEXT("status"))==TEXT("confirmed")?TEXT("confirmed"):TEXT("suspected"))},{TEXT("position"),Point(T.Position/100.)},
                {TEXT("region_id"),Null()},{TEXT("confidence"),Num(.95*Quality*SensorReliability)},{TEXT("source_id"),Str(Agent)},
                {TEXT("observed_at"),Num(Time())},{TEXT("priority"),Num(T.Priority)},{TEXT("evacuation_state"),Str(TEXT("waiting"))},
                {TEXT("aid_received"),Num(ReceivedKits.FindRef(Index))},{TEXT("aid_required"),Num(3)}});
            TargetSupport(World,T,Report.Data);
            if(ExplorationScene)Report.ActorScene=ExplorationScene->CaptureTarget(Index,Time());
            QueueReport(MoveTemp(Report));
        }
    }
}

void FMRCoreRuntime::DeliverReports()
{
    for(int32 I=0;I<Reports.Num();)
    {
        auto& R=Reports[I];
        if(R.Deadline>=0&&Time()+1.e-9>=R.Deadline)
        {
            Record(TEXT("message_expired"),Obj({{TEXT("message_id"),Str(R.MessageId)},
                {TEXT("agent_id"),Str(R.Agent)},{TEXT("reason"),Str(TEXT("report_ttl"))}}),false);
            RemoveReport(I);continue;
        }
        const auto* H=Hops.Find(R.Agent);
        if(R.Due<0)
        {
            if(!H){++I;continue;}
            R.Due=Time()+Latency*(*H);
        }
        if(Time()+1.e-9<R.Due){++I;continue;}
        if(!H){R.Due=-1;++I;continue;}
        if(PacketLost(R.Agent,R.Kind,R.Sequence,R.Attempts++))
        {
            Record(TEXT("message_dropped"),Obj({{TEXT("message_id"),Str(R.MessageId)},{TEXT("source_id"),Str(R.Agent)},
                {TEXT("attempt"),Num(R.Attempts)},{TEXT("reason"),Str(TEXT("packet_loss"))}}),false);
            if(R.Kind==EPacket::Pose||R.Attempts>=3){RemoveReport(I);continue;}
            R.Due=Time()+.5+Latency*(*H);++I;continue;
        }
        if(R.Kind==EPacket::Exploration)DeliverExplorationReport(R);
        else if(R.Kind==EPacket::Hazard)DeliverHazardReport(R);
        else if(R.Kind==EPacket::Pose)
            UpdateAgentKnowledge(R.Agent,R.Data,R.ActorScene);
        else
        {
            const int32 Target=FindTarget(R.Target);
            if(World->Targets.IsValidIndex(Target))
            {
                auto& T=World->Targets[Target];
                const auto Known=KnownTargets.FindRef(R.Target);
                if(T.ObservationEpoch==R.TargetEpoch&&(!T.bDiscovered||T.FloatBody)&&
                   (!Known||R.Data->GetNumberField(TEXT("observed_at"))>Known->GetNumberField(TEXT("observed_at"))+1.e-9))
                {
                    const bool First=!T.bDiscovered;auto Copy=MRCoreJson::Copy(R.Data);
                    // A queued earlier position sample must not undo a later
                    // inspection of this same ownership epoch.
                    if(!First&&Known&&Text(Known,TEXT("status"))==TEXT("confirmed"))Copy->SetStringField(TEXT("status"),TEXT("confirmed"));
                    if(Known&&Is(Known,TEXT("priority_updated_at"),EJson::Number))
                    {
                        Copy->SetField(TEXT("priority_updated_at"),Field(Known,TEXT("priority_updated_at")));
                        if(Known->GetNumberField(TEXT("priority_updated_at"))>Copy->GetNumberField(TEXT("observed_at")))Copy->SetField(TEXT("priority"),Field(Known,TEXT("priority")));
                    }
                    Copy->SetNumberField(TEXT("received_at"),Time());KnownTargets.Add(R.Target,Copy);
                    if(ExplorationScene)ExplorationScene->ApplyActors(R.ActorScene);
                    T.bDiscovered=true;if(First)T.DiscoveredAt=Time();const FString Kind=First?TEXT("target_detected"):TEXT("target_state_changed");Record(Kind,Copy);
                    PublishEvent(R.MessageId,Kind,Copy->GetNumberField(TEXT("observed_at")),R.Agent,{R.Target},
                        Obj({{TEXT("message_id"),Str(R.MessageId)}}),TEXT("new"),Copy->GetNumberField(TEXT("confidence")));
                }
            }
        }
        RemoveReport(I);
    }
}

void FMRCoreRuntime::UpdateCommands()
{
    for(auto& C:Commands)
    {
        if(C.Finished)continue;
        AMRAgent* A=FindAgent(C.Agent);
        if(!C.Delivered)
        {
            if(C.Revision!=PlanRevision)
            {
                C.PublicResult->SetStringField(TEXT("delivery_status"),TEXT("not_required"));
                C.PublicResult->SetStringField(TEXT("execution_status"),TEXT("cancelled"));
                C.PublicResult->SetStringField(TEXT("reason_code"),TEXT("superseded_plan"));
                C.PublicResult->SetNumberField(TEXT("updated_at"),Time());C.PublicDirty=true;C.Finished=true;
                Record(C.Index>=0?TEXT("command_result"):TEXT("internal_control_result"),C.PublicResult);continue;
            }
            if(Time()+1.e-9>=C.Deadline)
            {
                C.PublicResult->SetStringField(TEXT("delivery_status"),TEXT("expired"));C.PublicResult->SetStringField(TEXT("reason_code"),TEXT("delivery_ttl"));
                C.PublicResult->SetNumberField(TEXT("updated_at"),Time());C.PublicDirty=true;C.Finished=true;
                Record(C.Index>=0?TEXT("command_result"):TEXT("internal_control_result"),C.PublicResult);continue;
            }
            const int32* H=Hops.Find(C.Agent);
            if(!H){C.Due=-1;continue;}
            if(C.Due<0)C.Due=Time()+Latency*(*H);
            if(Time()+1.e-9<C.Due)continue;
            if(PacketLost(C.Agent,EPacket::Command,C.Sequence,C.DeliveryAttempts++))
            {
                Record(TEXT("command_packet_dropped"),Obj({{TEXT("command_id"),Str(C.Key)},
                    {TEXT("agent_id"),Str(C.Agent)},{TEXT("attempt"),Num(C.DeliveryAttempts)}}),false);
                C.Due=Time()+.25+Latency*(*H);continue;
            }
            C.Delivered=true;QueueAck(C,Latency*(*H));bool Success=false;
            const bool Motion=C.Action==TEXT("move")||C.Action==TEXT("follow_route")||C.Action==TEXT("hold");
            if(Motion&&LastMotionSequence.FindRef(C.Agent)>C.Sequence)
            {C.FinalStatus=TEXT("cancelled");C.Reason=TEXT("newer_motion_already_delivered");}
            else if(C.Action==TEXT("relay")&&LastRelaySequence.FindRef(C.Agent)>C.Sequence)
            {C.FinalStatus=TEXT("cancelled");C.Reason=TEXT("newer_relay_already_delivered");}
            else if(A&&!DisabledInfrastructure.Contains(A->InfrastructureSite)&&
                    (A->IsOperational()||C.Action==TEXT("charge")||C.Action==TEXT("hold")||C.Action==TEXT("assign_role")))
            {
                if(Motion)LastMotionSequence.Add(C.Agent,C.Sequence);
                if(C.Action==TEXT("assign_role"))
                {
                    const FString Role=Text(C.Parameters,TEXT("role_id"));
                    ActualConfigurations.Add(C.Agent,{Role,C.Parameters->GetArrayField(TEXT("scenario_ids")),C.Revision});
                    if(Role==TEXT("safe_holder")&&!A->bCarrying&&A->State!=TEXT("loading")&&A->State!=TEXT("unloading"))
                    {A->Hold(C.Key);LastMotionSequence.Add(C.Agent,C.Sequence);}
                    Success=true;C.FinalStatus=TEXT("completed");
                }
                else if(C.Action==TEXT("hold"))Success=A->Hold(C.Key);
                else if(C.Action==TEXT("move")||C.Action==TEXT("follow_route"))
                {
                    TArray<FVector> Points;
                    if(C.Action==TEXT("move")){FVector P;MRCoreJson::Point(Field(C.Parameters,TEXT("target")),P);Points.Add(P*100);}
                    else for(const auto& V:C.Parameters->GetArrayField(TEXT("waypoints"))){FVector P;MRCoreJson::Point(V,P);Points.Add(P*100);}
                    bool PreciseStop=false;
                    if(C.Action==TEXT("follow_route"))C.Parameters->TryGetBoolField(TEXT("precise_stop"),PreciseStop);
                    Success=A->AcceptRoute(C.Key,Points,PreciseStop);
                }
                else if(C.Action==TEXT("observe")){SensorRadius.Add(C.Agent,C.Parameters->GetNumberField(TEXT("radius")));Success=true;C.FinalStatus=TEXT("completed");}
                else if(C.Action==TEXT("deliver"))Success=DeliverAid(C,A);
                else if(C.Action==TEXT("compute"))Success=StartCompute(C);
                else if(C.Action==TEXT("issue_directive"))Success=IssueDirective(C);
                else if(C.Action==TEXT("relay"))
                {
                    const bool Enabled=C.Parameters->GetBoolField(TEXT("enabled"));
                    LastRelaySequence.Add(C.Agent,C.Sequence);
                    if(Enabled)RelayingAgents.Add(C.Agent);else RelayingAgents.Remove(C.Agent);
                    UpdateNetwork();Success=true;C.FinalStatus=TEXT("completed");
                    Record(TEXT("relay_changed"),Obj({{TEXT("command_id"),Str(C.Key)},{TEXT("agent_id"),Str(C.Agent)},
                        {TEXT("enabled"),Bool(Enabled)},{TEXT("position"),Point(A->GetActorLocation()/100.)}}),false);
                }
                else if(C.Action==TEXT("send_message"))
                {
                    C.Recipient=Text(C.Parameters,TEXT("recipient_id"));C.MessageDeadline=Time()+30;Success=true;
                    Record(TEXT("peer_message_queued"),Obj({{TEXT("message_id"),Str(C.Key)},{TEXT("sender_id"),Str(C.Agent)},
                        {TEXT("recipient_id"),Str(C.Recipient)},{TEXT("deadline"),Num(C.MessageDeadline)}}),false);
                }
                else if(C.Action==TEXT("pickup"))
                {C.TargetIndex=FindTarget(Text(C.Parameters,TEXT("target_id")));Success=A->BeginPickup(C.TargetIndex,C.Key);}
                else if(C.Action==TEXT("handover")){C.TargetIndex=A->TargetIndex;Success=A->BeginHandover(C.Key);}
                else if(C.Action==TEXT("disembark"))
                {C.TargetIndex=A->TargetIndex;Success=A->BeginDisembark(Text(C.Parameters,TEXT("station_id")),C.Key);}
                else if(C.Action==TEXT("charge"))
                {
                    C.Station=Text(C.Parameters,TEXT("station_id"));
                    Success=CanStartCharge(C.Station,A)&&A->BeginCharge(C.Key);
                    if(Success)Record(TEXT("charge_queued"),Obj({{TEXT("command_id"),Str(C.Key)},
                        {TEXT("agent_id"),Str(C.Agent)},{TEXT("station_id"),Str(C.Station)}}),false);
                }
                else if(C.Action==TEXT("inspect"))
                {
                    C.TargetIndex=FindTarget(Text(C.Parameters,TEXT("target_id")));
                    if(World->Targets.IsValidIndex(C.TargetIndex))
                    {
                        const auto& T=World->Targets[C.TargetIndex];FCollisionQueryParams Query;Query.AddIgnoredActor(A);FHitResult Hit;
                        const FVector SensorPoint=T.Position+FVector(0,0,60-T.VisualAnchorOffsetCm);
                        Success=Time()+1.e-9>=T.AvailableAt&&FVector::Dist(A->GetActorLocation(),T.Position)<=SensorRadius.FindRef(C.Agent)*100&&
                            !World->GetWorld()->LineTraceSingleByChannel(Hit,A->GetActorLocation(),SensorPoint,ECC_Visibility,Query);
                        if(Success)
                        {
                            const float Quality=SensorQuality(A->GetActorLocation(),SensorPoint);
                            Success=SensorAccepts(A,T.Id,Quality,1);
                            if(Quality<1||SensorReliability<1||A->SensorFactor<1)Record(TEXT("inspection_trial"),Obj({
                                {TEXT("command_id"),Str(C.Key)},{TEXT("agent_id"),Str(C.Agent)},
                                {TEXT("target_id"),Str(Text(C.Parameters,TEXT("target_id")))},
                                {TEXT("visibility"),Num(Quality)},{TEXT("confirmed"),Bool(Success)}}),false);
                        }
                    }
                    C.FinalStatus=Success?TEXT("completed"):TEXT("failed");
                }
                if(!Success){C.FinalStatus=TEXT("failed");C.Reason=TEXT("local_execution_precondition_failed");}
            }
            else {C.FinalStatus=TEXT("failed");C.Reason=TEXT("local_agent_unavailable");}
            Record(TEXT("local_command_received"),Obj({{TEXT("command_id"),Str(C.Key)},{TEXT("action"),Str(C.Action)},
                {TEXT("agent_id"),Str(C.Agent)},{TEXT("successful_start"),Bool(Success)}}),false);
        }
        if(C.FinalStatus.IsEmpty())
        {
            FString Finish;
            if(C.Action==TEXT("send_message"))ProgressMessage(C);
            else if(C.Action==TEXT("compute"))
            {
                if(!A||!A->IsOperational()||DisabledInfrastructure.Contains(A->InfrastructureSite))
                {Finish=TEXT("failed");C.Reason=TEXT("compute_node_unavailable");}
                else if(Time()+1.e-9>=C.ServiceDue)
                {
                    Finish=TEXT("completed");Record(TEXT("compute_completed"),Obj({{TEXT("command_id"),Str(C.Key)},
                        {TEXT("agent_id"),Str(C.Agent)},{TEXT("result"),Json(C.ServiceResult)}}),false);
                }
            }
            else if(C.Action==TEXT("charge"))
            {
                if(!A||A->CommandId!=C.Key||!A->IsCharging()){Finish=TEXT("cancelled");C.Reason=TEXT("charge_replaced");}
            }
            else if(!A||(!A->IsOperational()&&C.Action!=TEXT("hold"))){Finish=TEXT("failed");C.Reason=TEXT("agent_failed_during_execution");}
            else if((C.Action==TEXT("move")||C.Action==TEXT("follow_route")||C.Action==TEXT("hold")))
            {
                if(A->CommandId!=C.Key){Finish=TEXT("cancelled");C.Reason=TEXT("motion_replaced");}
                else if(C.Action==TEXT("hold")?A->IsHoldingStable():A->RouteFinished())Finish=TEXT("completed");
            }
            else if(C.Action==TEXT("pickup")&&A->bCarrying&&A->TargetIndex==C.TargetIndex)Finish=TEXT("completed");
            else if(C.Action==TEXT("handover")&&World->Targets.IsValidIndex(C.TargetIndex)&&World->Targets[C.TargetIndex].bRescued)Finish=TEXT("completed");
            else if(C.Action==TEXT("disembark")&&World->Targets.IsValidIndex(C.TargetIndex)&&A->CommandId==C.Key&&
                !A->bCarrying&&World->Targets[C.TargetIndex].ShoreStation==Text(C.Parameters,TEXT("station_id")))Finish=TEXT("completed");
            if(!Finish.IsEmpty())
            {
                C.FinalStatus=Finish;
                // The receiving base witnesses its own physical handover.
                // It need not wait for a radio report from the carrier.
                QueueAck(C,C.Action==TEXT("handover")&&Finish==TEXT("completed")?0:Latency*FMath::Max(1,Hops.FindRef(C.Agent)));
            }
        }
        if(!C.FinalStatus.IsEmpty()&&A&&!C.AgentReport)
        {C.AgentReport=AgentSnapshot(A,Time());if(ExplorationScene)C.AgentVisual=ExplorationScene->CaptureActor(A,Time());}
        if(C.FinalStatus==TEXT("completed")&&World->Targets.IsValidIndex(C.TargetIndex)&&!C.TargetReport)
        {
            const auto& T=World->Targets[C.TargetIndex];
            const bool Loaded=T.bAssigned&&World->Agents.ContainsByPredicate([&](const AMRAgent* Carrier)
                {return Carrier->bCarrying&&Carrier->TargetIndex==C.TargetIndex;});
            C.TargetEpoch=T.ObservationEpoch;
            C.TargetReport=Obj({{TEXT("id"),Str(FString::Printf(TEXT("person-%d"),T.Id))},
                {TEXT("kind"),Str(TEXT("person"))},{TEXT("status"),Str(T.bRescued?TEXT("resolved"):TEXT("confirmed"))},
                {TEXT("position"),Point((T.Visual?T.Visual->GetActorLocation():T.Position)/100.)},
                {TEXT("confidence"),Num(1)},{TEXT("source_id"),Str(C.Action==TEXT("handover")?TEXT("rescue-base"):C.Agent)},{TEXT("observed_at"),Num(Time())},
                {TEXT("priority"),Num(T.Priority)},{TEXT("evacuation_state"),Str(T.bRescued?TEXT("evacuated"):Loaded?TEXT("loaded"):TEXT("waiting"))},
                {TEXT("aid_received"),Num(ReceivedKits.FindRef(C.TargetIndex))},{TEXT("aid_required"),Num(3)}});
            TargetSupport(World,T,C.TargetReport);
            if(ExplorationScene)C.TargetVisual=ExplorationScene->CaptureTarget(C.TargetIndex,Time());
        }
        if(C.AckDeadline>=0&&Time()+1.e-9>=C.AckDeadline)
        {
            if(Text(C.PublicResult,TEXT("delivery_status"))!=TEXT("delivered"))C.PublicResult->SetStringField(TEXT("delivery_status"),TEXT("unknown"));
            C.PublicResult->SetStringField(TEXT("execution_status"),TEXT("unknown"));
            C.PublicResult->SetStringField(TEXT("reason_code"),TEXT("acknowledgement_expired"));
            C.PublicResult->SetNumberField(TEXT("updated_at"),Time());C.PublicDirty=true;
            Record(C.Index>=0?TEXT("command_result"):TEXT("internal_control_result"),C.PublicResult);
            C.AckDue=C.AckDeadline=-1;
            if(!C.FinalStatus.IsEmpty())C.Finished=true;
        }
        const bool BaseWitness=C.Action==TEXT("handover")&&C.FinalStatus==TEXT("completed");
        if(C.AckDue>=0&&Time()+1.e-9>=C.AckDue&&(BaseWitness||Hops.Contains(C.Agent)))
        {
            if(!BaseWitness&&PacketLost(C.Agent,EPacket::Ack,C.Sequence,C.AckAttempts++))
            {
                Record(TEXT("ack_packet_dropped"),Obj({{TEXT("command_id"),Str(C.Key)},
                    {TEXT("agent_id"),Str(C.Agent)},{TEXT("attempt"),Num(C.AckAttempts)}}),false);
                C.AckDue=Time()+.25+Latency*FMath::Max(1,Hops.FindRef(C.Agent));continue;
            }
            C.PublicResult->SetStringField(TEXT("delivery_status"),TEXT("delivered"));
            C.PublicResult->SetStringField(TEXT("execution_status"),C.FinalStatus.IsEmpty()?TEXT("in_progress"):C.FinalStatus);
            if(C.Action==TEXT("send_message")&&C.FinalStatus==TEXT("completed"))
            {
                C.PublicResult->SetStringField(TEXT("message_id"),C.Key);
                C.PublicResult->SetStringField(TEXT("recipient_id"),C.Recipient);
            }
            if(C.ServiceResult&&C.FinalStatus==TEXT("completed"))C.PublicResult->SetObjectField(TEXT("service_result"),C.ServiceResult);
            C.PublicResult->SetField(TEXT("reason_code"),C.Reason.IsEmpty()?Null():Str(C.Reason));C.PublicResult->SetNumberField(TEXT("updated_at"),Time());
            C.PublicDirty=true;
            Record(C.Index>=0?TEXT("command_result"):TEXT("internal_control_result"),C.PublicResult);
            if(C.AgentReport&&!BaseWitness)UpdateAgentKnowledge(C.Agent,C.AgentReport,C.AgentVisual);
            if(C.TargetReport&&World->Targets.IsValidIndex(C.TargetIndex)&&World->Targets[C.TargetIndex].ObservationEpoch==C.TargetEpoch)
            {
                const FString Target=Text(C.TargetReport,TEXT("id"));
                const auto Known=KnownTargets.FindRef(Target);
                if(Known&&Known->GetNumberField(TEXT("observed_at"))<=C.TargetReport->GetNumberField(TEXT("observed_at"))&&
                    (Text(Known,TEXT("status"))!=TEXT("resolved")||Text(C.TargetReport,TEXT("status"))==TEXT("resolved")))
                {
                    auto T=MRCoreJson::Copy(C.TargetReport);
                    const auto PriorityAt=Field(Known,TEXT("priority_updated_at"));
                    if(PriorityAt)
                    {
                        T->SetField(TEXT("priority_updated_at"),PriorityAt);
                        if(PriorityAt->AsNumber()>T->GetNumberField(TEXT("observed_at")))T->SetField(TEXT("priority"),Field(Known,TEXT("priority")));
                    }
                    T->SetNumberField(TEXT("received_at"),Time());KnownTargets.Add(Target,T);Record(TEXT("target_state_changed"),T);
                    if(ExplorationScene)ExplorationScene->ApplyActors(C.TargetVisual);
                    PublishEvent(C.Key+TEXT("-target"),TEXT("target_state_changed"),T->GetNumberField(TEXT("observed_at")),
                        Text(T,TEXT("source_id")),{Target},Obj({{TEXT("command_id"),Str(C.Key)},
                            {TEXT("evacuation_state"),Field(T,TEXT("evacuation_state"))}}));
                    if(C.Action==TEXT("inspect"))ResolveConflicts(Target,C.Agent,T->GetNumberField(TEXT("observed_at")));
                }
            }
            C.AckDue=C.AckDeadline=-1;if(!C.FinalStatus.IsEmpty())C.Finished=true;
        }
    }
    if(SafeStopRequested)
    {
        bool Safe=true;
        for(const auto& C:Commands)if(!C.Finished&&(C.Action==TEXT("move")||C.Action==TEXT("follow_route"))&&!C.Delivered)Safe=false;
        for(AMRAgent* A:World->Agents)if(A->CanMove()&&!A->IsHoldingStable())Safe=false;
        if(Safe&&Clock.ExecutedFrames()>0){Status=TEXT("safe_stopped");OutcomeReason=TEXT("physical_stop_confirmed");}
    }
}
