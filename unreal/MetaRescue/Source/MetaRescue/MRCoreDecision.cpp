#include "MRCoreRuntime.h"
#include "MRCoreJson.h"
#include "MRCoreReset.h"
#include "MRCoreValues.h"
#include "MRWorld.h"
#include "MRAgent.h"
#include "Components/BoxComponent.h"
#include "Kismet/GameplayStatics.h"
#include "HAL/PlatformFileManager.h"
#include "Misc/Paths.h"
#include "Misc/Guid.h"
#include "Misc/App.h"
#include "Engine/Engine.h"
#include "ProceduralMeshComponent.h"

using namespace MRCoreValues;

void FMRCoreRuntime::BeginEpisode(const FPending& R)
{
    const FString Id=Text(R.Request,TEXT("request_id"));
    FString Root=FPlatformMisc::GetEnvironmentVariable(TEXT("METARESCUE_OUTPUT"));if(Root.IsEmpty())Root=TEXT("D:/MetaRescue-output");
    const FString NewEpisode=FGuid::NewGuid().ToString(EGuidFormats::Digits);
    const FString NewDirectory=FPaths::ConvertRelativePathToFull(Root/TEXT("core-runs")/NewEpisode);
    auto& Files=FPlatformFileManager::Get().GetPlatformFile();
    if(!Files.CreateDirectoryTree(*NewDirectory)){Error(R.Complete,TEXT("INTERNAL_ERROR"),TEXT("Cannot create episode journal directory"),Id,500);return;}
    auto NewPublic=MakeUnique<FMRCoreDiskRecords>(),NewTruth=MakeUnique<FMRCoreDiskRecords>(),NewReplay=MakeUnique<FMRCoreDiskRecords>();
    FString OpenError;
    if(!NewPublic->Open(NewDirectory/TEXT("public"),OpenError)||!NewTruth->Open(NewDirectory/TEXT("truth"),OpenError)||
       !NewReplay->Open(NewDirectory/TEXT("replay"),OpenError))
    {Error(R.Complete,TEXT("INTERNAL_ERROR"),OpenError,Id,500);return;}
    FinalizeReplacement();
    PublicJournal=MoveTemp(NewPublic);TruthJournal=MoveTemp(NewTruth);ReplayJournal=MoveTemp(NewReplay);
    Directory=NewDirectory;Episode=NewEpisode;StorageError.Empty();
    Clock.Reset();SensorSamples=TelemetrySamples=0;OverviewFrame=0;
    Substeps.Reset();SubstepWindowsStarted=0;
    Status=TEXT("running");OutcomeReason.Empty();Closed=false;SafeStopRequested=false;
    KnownAgents.Empty();KnownTargets.Empty();AgentReceived.Empty();ActualConfigurations.Empty();Reports.Empty();ReportCounts.Empty();Commands.Empty();ReplayKeys.Empty();
    KnownZones.Empty();StepEvents.Empty();SurfaceObservedAt.Empty();SensorRadius.Empty();StaleAlerts.Empty();DegradationAlerts.Empty();
    EventViews.Empty();ScheduledViews.Empty();ViewStartedAt=-1;
    LastMotionSequence.Empty();CommandSequence=0;
    StepRequest.Reset();PlanRevision=0;
    Accepted=Obj({{TEXT("scenario_ids"),Arr({})},{TEXT("parameters"),Json(Obj())},{TEXT("synthesized_scenario"),Null()}});DesiredRoles=Obj();
    for(AMRAgent* A:World->Agents)
    {
        A->ResetForEpisode(InitialPoses.FindChecked(A->AgentKey()),Unlimited);
        SensorRadius.Add(A->AgentKey(),A->bAerial?45:A->Kind()==TEXT("infrastructure")?35:A->MediumLimits.IsValid?12:16);
    }
    ResetTeamActions();
    ResetServices();
    ResetResources();
    World->ResetCoreEventEffects();
    for(const auto& Body:InitialBodies)if(auto* Piece=Body.Key.Get())
    {
        Piece->SetSimulatePhysics(Body.Value.Simulating);
        Piece->SetWorldTransform(Body.Value.Pose,false,nullptr,ETeleportType::TeleportPhysics);
        if(Body.Value.Simulating)
        {
            Piece->SetPhysicsLinearVelocity(Body.Value.Linear);
            Piece->SetPhysicsAngularVelocityInRadians(Body.Value.Angular);
        }
    }
    for(auto& T:World->Targets)
    {
        T.bDiscovered=false;T.bAssigned=false;T.bRescued=false;T.DiscoveredAt=-1;T.ObservedAt=-1;T.Observer=-1;T.bAvailabilityReported=false;T.ObservationEpoch=0;
        T.ShoreStation.Empty();T.SupportCarrier.Reset();T.FloatDisplacedM3=0;
        if(T.Visual)
        {
            T.Visual->DetachFromActor(FDetachmentTransformRules::KeepWorldTransform);
            if(T.FloatBody)T.FloatBody->SetSimulatePhysics(false);
            T.Visual->SetActorTransform(InitialTargetPoses.FindChecked(T.Id),false,nullptr,ETeleportType::TeleportPhysics);
            T.Position=T.Visual->GetActorLocation();T.Visual->SetActorHiddenInGame(T.AvailableAt>0);
            if(T.FloatBody)
            {
                T.Visual->SetActorEnableCollision(true);T.FloatBody->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);T.FloatBody->SetSimulatePhysics(true);
                T.FloatBody->SetPhysicsLinearVelocity(FVector::ZeroVector);T.FloatBody->SetPhysicsAngularVelocityInRadians(FVector::ZeroVector);
            }
        }
    }
    ResetContest();AdvanceContest();World->ContactCount=0;UpdateNetwork();
    for(AMRAgent* A:World->Agents){KnownAgents.Add(A->AgentKey(),AgentSnapshot(A,0));AgentReceived.Add(A->AgentKey(),0);}
    UGameplayStatics::SetGamePaused(World,true);Snapshot(Id);
    Record(TEXT("reset_request"),R.Request);Record(TEXT("observation"),CachedObservation);
    if(!World->CoreEventProfile.IsEmpty())
        Record(TEXT("event_configuration"),World->CityLayout->GetObjectField(TEXT("event_model")),false);
    RecordTruthSnapshot(TEXT("initial"));
    CaptureOverviewFrame();
    FlushArchive();ArchiveManifest(TEXT("open"));
    if(!StorageError.IsEmpty()){Error(R.Complete,TEXT("INTERNAL_ERROR"),StorageError,Id,500);return;}
    ResetState->LastId=Id;
    ResetState->AcceptedIds.Add(ReplayKey(Id));
    ResetState->LastBody=R.Body;
    ResetState->LastResponse=MRCoreJson::Write(EpisodeResponse(Id,false));
    Reply(R.Complete,ResetState->LastResponse);
    UE_LOG(LogTemp,Display,TEXT("MR_CORE episode %s journal %s"),*Episode,*Directory);
}

FString FMRCoreRuntime::ValidateDecision(const Object& R,FString& Code) const
{
    Code=TEXT("INVALID_REQUEST");
    for(const FString& K:{TEXT("episode_id"),TEXT("decision_id"),TEXT("request_id"),TEXT("operation")})
        if(Text(R,K).IsEmpty())return K+TEXT(" must be a nonempty string");
    for(const FString& K:{TEXT("previous_configuration"),TEXT("selected_configuration"),TEXT("role_assignments"),TEXT("explanation")})
        if(!Is(R,K,EJson::Object))return K+TEXT(" must be an object");
    for(const FString& K:{TEXT("candidate_evaluations"),TEXT("commands"),TEXT("constraint_checks")})
    {
        if(!Is(R,K,EJson::Array))return K+TEXT(" must be an array");
        for(const auto& V:R->GetArrayField(K))if(V->Type!=EJson::Object)return K+TEXT(" must contain objects");
    }
    if(!Is(R,TEXT("time"),EJson::Number)||FMath::Abs(R->GetNumberField(TEXT("time"))-Time())>1.e-9)return TEXT("Decision time is stale or future");
    if(R->GetArrayField(TEXT("commands")).Num()>256)return TEXT("Too many commands");
    const auto Explanation=R->GetObjectField(TEXT("explanation"));
    for(const FString& K:{TEXT("observation_refs"),TEXT("reason_codes"),TEXT("expected_effects")})if(!Is(Explanation,K,EJson::Array))return TEXT("Invalid explanation array");
    for(const FString& K:{TEXT("observation_refs"),TEXT("reason_codes")})for(const auto& V:Explanation->GetArrayField(K))if(V->Type!=EJson::String||V->AsString().IsEmpty())return TEXT("Invalid explanation reference");
    if(!Is(Explanation,TEXT("confidence"),EJson::Number)||Explanation->GetNumberField(TEXT("confidence"))<0||Explanation->GetNumberField(TEXT("confidence"))>1)return TEXT("Invalid explanation confidence");
    return ValidatePlan(R,Code);
}

FString FMRCoreRuntime::ValidateCommand(const Object& C) const
{
    const FString Agent=Text(C,TEXT("agent_id")),Action=Text(C,TEXT("action"));
    if(SafeStopRequested&&Action!=TEXT("hold"))return TEXT("safe_stop_in_progress");
    if(!KnownAgents.Contains(Agent)||!Is(C,TEXT("parameters"),EJson::Object))return TEXT("unknown_agent_or_invalid_parameters");
    const auto Known=KnownAgents.FindChecked(Agent),P=C->GetObjectField(TEXT("parameters"));
    bool Available=false;
    for(const auto& A:Known->GetArrayField(TEXT("available_actions")))if(Text(A->AsObject(),TEXT("action"))==Action)Available=true;
    if(Time()-AgentReceived.FindRef(Agent)>5||!Available)return TEXT("action_unavailable_in_delivered_knowledge");
    if(Action==TEXT("move")||Action==TEXT("follow_route"))
    {
        const auto* Actor=FindAgent(Agent);
        TArray<Value> Points;
        if(Action==TEXT("move"))Points.Add(Field(P,TEXT("target")));
        else
        {
            if(!Is(P,TEXT("waypoints"),EJson::Array))return TEXT("invalid_route");Points=P->GetArrayField(TEXT("waypoints"));
            if(Points.IsEmpty()||Points.Num()>4096)return TEXT("invalid_route_size");
            if(const auto Precision=Field(P,TEXT("precise_stop"));Precision&&
                (Precision->Type!=EJson::Boolean||(Precision->AsBool()&&(!Actor||Actor->Kind()!=TEXT("ground")))))
                return TEXT("invalid_ground_precision_stop");
        }
        for(const auto& V:Points)
        {
            FVector Point;if(!MRCoreJson::Point(V,Point))return TEXT("invalid_point");
            if(World->bCityLayout)
            {
                const auto Bounds=World->CityLayout->GetObjectField(TEXT("bounds"));FVector Min,Max;
                MRCoreJson::Point(Field(Bounds,TEXT("min")),Min);MRCoreJson::Point(Field(Bounds,TEXT("max")),Max);
                const double MinimumZ=Actor&&Actor->MediumLimits.IsValid?Min.Z:0;
                if(Point.X<Min.X||Point.X>Max.X||Point.Y<Min.Y||Point.Y>Max.Y||Point.Z<MinimumZ||Point.Z>Max.Z)return TEXT("outside_announced_bounds");
                if(Actor&&Actor->MediumLimits.IsValid&&!Actor->MediumPointAllowed(Point*100))return TEXT("outside_announced_medium");
            }
            else if(FMath::Abs(Point.X)>700||FMath::Abs(Point.Y)>700||Point.Z<0||Point.Z>150)return TEXT("outside_announced_bounds");
        }
    }
    else if(Action==TEXT("observe"))
    {
        const FString Kind=Text(Known,TEXT("kind"));const auto* Actor=FindAgent(Agent);
        const double Maximum=Kind==TEXT("aerial")?45:Kind==TEXT("infrastructure")?35:Actor&&Actor->MediumLimits.IsValid?12:16;
        if(!Is(P,TEXT("radius"),EJson::Number)||P->GetNumberField(TEXT("radius"))<=0||P->GetNumberField(TEXT("radius"))>Maximum)return TEXT("invalid_sensor_radius");
    }
    else if(Action==TEXT("inspect")||Action==TEXT("pickup"))
    {
        const FString Id=Text(P,TEXT("target_id"));if(!KnownTargets.Contains(Id))return TEXT("unknown_public_target");
        if(Action==TEXT("pickup")&&Text(KnownTargets.FindChecked(Id),TEXT("status"))!=TEXT("confirmed"))return TEXT("target_not_confirmed");
    }
    else if(Action==TEXT("handover")){if(Text(P,TEXT("station_id"))!=TEXT("rescue-base"))return TEXT("unknown_station");}
    else if(Action==TEXT("disembark"))
    {
        const auto Station=World->ShoreStation();const auto* Actor=FindAgent(Agent);
        if(!Station||!Actor||!Actor->bRescueWatercraft||Text(P,TEXT("station_id"))!=Text(Station,TEXT("id")))return TEXT("unknown_shore_station");
    }
    else if(Action==TEXT("charge"))
    {
        const auto* Station=ChargingStations.Find(Text(P,TEXT("station_id")));
        if(!Station)return TEXT("unknown_charging_station");
        if(Station->Kind!=Text(Known,TEXT("kind"))||(!Station->AgentId.IsEmpty()&&Station->AgentId!=Agent))
            return TEXT("incompatible_charging_station");
    }
    else if(Action==TEXT("deliver"))
    {
        const auto Target=KnownTargets.FindRef(Text(P,TEXT("target_id")));
        if(!Target||Text(Target,TEXT("status"))!=TEXT("confirmed"))return TEXT("aid_target_not_confirmed");
        const auto Amount=Field(P,TEXT("amount"));
        if(Text(P,TEXT("resource_id"))!=TEXT("medical_kits")||!Amount||Amount->Type!=EJson::Number||
           Amount->AsNumber()<1||Amount->AsNumber()>3||Amount->AsNumber()!=FMath::FloorToDouble(Amount->AsNumber()))
            return TEXT("invalid_aid_amount_or_resource");
    }
    else if(Action==TEXT("relay"))
    {if(!Is(P,TEXT("enabled"),EJson::Boolean))return TEXT("relay_requires_boolean_enabled");}
    else if(Action==TEXT("send_message"))
    {
        const FString Recipient=Text(P,TEXT("recipient_id"));
        if(Recipient==Agent||!KnownRecipient(Recipient)||!Is(P,TEXT("payload"),EJson::Object)||
            MRCoreJson::Write(P->GetObjectField(TEXT("payload"))).Len()>4096)return TEXT("invalid_message_recipient_or_payload");
    }
    else if(Action==TEXT("compute")||Action==TEXT("issue_directive"))return ValidateServiceCommand(C);
    else if(Action!=TEXT("hold"))return TEXT("undeclared_action");
    return TEXT("");
}

void FMRCoreRuntime::Step(const FPending& R)
{
    const FString Id=Text(R.Request,TEXT("decision_id")),RequestId=Text(R.Request,TEXT("request_id"));
    // A replay record written before a failed manifest was never acknowledged
    // as durable. Do not turn its original HTTP500 into success on retry.
    if(!StorageError.IsEmpty())
    {Snapshot(RequestId);Error(R.Complete,TEXT("INTERNAL_ERROR"),StorageError,RequestId,500);return;}
    FReplay Prior;bool Found=false;
    if(!LoadReplay(Id,Prior,Found))
    {Snapshot(RequestId);ArchiveManifest(TEXT("incomplete"));Error(R.Complete,TEXT("INTERNAL_ERROR"),StorageError,RequestId,500);return;}
    if(Found)
    {
        if(Prior.Body!=R.Body)Error(R.Complete,TEXT("INVALID_REQUEST"),TEXT("decision_id body differs from cached request"),RequestId);
        else Reply(R.Complete,Prior.Response,Prior.HttpStatus);return;
    }
    if(ReplayKeys.Num()>=100000){Error(R.Complete,TEXT("RESOURCE_EXHAUSTED"),TEXT("Declared decision limit reached"),RequestId);return;}
    auto Reject=[&](const FString& Code,const FString& Message)
    {
        FString Response;int32 HttpStatus=400;
        const FHttpResultCallback Capture=[&](TUniquePtr<FHttpServerResponse>&& Result)
        {FUTF8ToTCHAR Text(reinterpret_cast<const ANSICHAR*>(Result->Body.GetData()),Result->Body.Num());Response=FString(Text.Length(),Text.Get());HttpStatus=int32(Result->Code);};
        Error(Capture,Code,Message,RequestId);
        Record(TEXT("protocol_error"),Obj({{TEXT("code"),Str(Code)},{TEXT("message"),Str(Message)},{TEXT("decision_id"),Str(Id)}}));
        if((!Id.IsEmpty()&&!StoreReplay(Id,{R.Body,Response,HttpStatus}))||!FlushArchive())
        {Error(R.Complete,TEXT("INTERNAL_ERROR"),StorageError,RequestId,500);return;}
        ArchiveManifest(Closed?TEXT("complete"):TEXT("open"));Reply(R.Complete,Response,HttpStatus);
    };
    if(Status!=TEXT("running")||Closed){Reject(TEXT("INVALID_REQUEST"),TEXT("Episode is terminal or closed"));return;}
    FString Code;const FString Invalid=ValidateDecision(R.Request,Code);if(!Invalid.IsEmpty()){Reject(Code,Invalid);return;}
    const FString Operation=Text(R.Request,TEXT("operation"));
    const auto& Input=R.Request->GetArrayField(TEXT("commands"));
    TArray<FString> Reasons;Reasons.SetNum(Input.Num());TArray<TArray<int32>> Groups;TSet<int32> Grouped;
    if(Is(R.Request,TEXT("metaevolution"),EJson::Object))
    {
        auto M=R.Request->GetObjectField(TEXT("metaevolution"));
        if(M->HasField(TEXT("command_groups")))
        {
            if(!Is(M,TEXT("command_groups"),EJson::Array)){Reject(TEXT("INVALID_REQUEST"),TEXT("Invalid command_groups"));return;}
            TSet<FString> GroupIds;
            for(const auto& G:M->GetArrayField(TEXT("command_groups")))
            {
                if(G->Type!=EJson::Object||Text(G->AsObject(),TEXT("id")).IsEmpty()||!Is(G->AsObject(),TEXT("command_indices"),EJson::Array))
                {Reject(TEXT("INVALID_REQUEST"),TEXT("Invalid command group"));return;}
                const FString GroupId=Text(G->AsObject(),TEXT("id"));if(GroupIds.Contains(GroupId)){Reject(TEXT("INVALID_REQUEST"),TEXT("Duplicate group ID"));return;}GroupIds.Add(GroupId);
                TArray<int32> Indices;
                for(const auto& Index:G->AsObject()->GetArrayField(TEXT("command_indices")))
                {
                    if(Index->Type!=EJson::Number||Index->AsNumber()!=FMath::FloorToDouble(Index->AsNumber())||Index->AsNumber()<0||Index->AsNumber()>=Input.Num()||Grouped.Contains(int32(Index->AsNumber())))
                    {Reject(TEXT("INVALID_REQUEST"),TEXT("Invalid or repeated group index"));return;}
                    const int32 I=int32(Index->AsNumber());Grouped.Add(I);Indices.Add(I);
                }
                if(Indices.IsEmpty()){Reject(TEXT("INVALID_REQUEST"),TEXT("Empty command group"));return;}Groups.Add(MoveTemp(Indices));
            }
        }
    }
    TMap<FString,int32> ExclusiveCounts,RelayCounts;
    const auto Exclusive=[](const FString& Action){return Action!=TEXT("observe")&&Action!=TEXT("inspect")&&
        Action!=TEXT("relay")&&Action!=TEXT("send_message");};
    for(int32 I=0;I<Input.Num();I++)
    {
        const auto Command=Input[I]->AsObject();
        Reasons[I]=ValidateCommand(Command);if(!Grouped.Contains(I))Groups.Add({I});
        if(!Reasons[I].IsEmpty())continue;
        const FString Action=Text(Command,TEXT("action")),Agent=Text(Command,TEXT("agent_id"));
        if(Exclusive(Action))++ExclusiveCounts.FindOrAdd(Agent);
        if(Action==TEXT("relay"))++RelayCounts.FindOrAdd(Agent);
    }
    for(int32 I=0;I<Input.Num();I++)
    {
        const auto Command=Input[I]->AsObject();
        const FString Agent=Text(Command,TEXT("agent_id")),Action=Text(Command,TEXT("action"));
        if(Reasons[I].IsEmpty()&&((Exclusive(Action)&&ExclusiveCounts.FindRef(Agent)>1)||
           (Action==TEXT("relay")&&RelayCounts.FindRef(Agent)>1)))
            Reasons[I]=TEXT("conflicting_commands_for_agent");
    }
    for(const auto& G:Groups)
    {
        FString Reason;for(int32 I:G)if(!Reasons[I].IsEmpty()){Reason=Reasons[I];break;}
        if(!Reason.IsEmpty())for(int32 I:G)Reasons[I]=TEXT("group_rejected:")+Reason;
    }
    // Include commands from this batch in the declared per-agent queue budget.
    TMap<FString,int32> Reserved;
    for(const auto& C:Commands)if(!C.Finished&&(C.Delivered||Operation==TEXT("keep")))++Reserved.FindOrAdd(C.Agent);
    for(const auto& G:Groups)
    {
        bool ValidGroup=true;TMap<FString,int32> Needed;
        for(int32 I:G){ValidGroup&=Reasons[I].IsEmpty();++Needed.FindOrAdd(Text(Input[I]->AsObject(),TEXT("agent_id")));}
        if(!ValidGroup)continue;
        for(const auto& Need:Needed)if(Reserved.FindRef(Need.Key)+Need.Value>32)ValidGroup=false;
        if(!ValidGroup){for(int32 I:G)Reasons[I]=TEXT("group_rejected:pending_command_limit");}
        else for(const auto& Need:Needed)Reserved.FindOrAdd(Need.Key)+=Need.Value;
    }
    int32 Valid=0;for(const auto& Reason:Reasons)Valid+=Reason.IsEmpty();
    if(!Input.IsEmpty()&&Valid==0){Reject(TEXT("INVALID_COMMAND"),TEXT("All independent command groups were rejected"));return;}
    StepRequest=R.Request;StepBody=R.Body;StepCallbacks={R.Complete};
    StepEvents.Empty();
    const auto PriorRoles=DesiredRoles;
    if(Operation!=TEXT("keep"))
    {
        Accepted=MRCoreJson::Copy(R.Request->GetObjectField(TEXT("selected_configuration")));
        DesiredRoles=MRCoreJson::Copy(R.Request->GetObjectField(TEXT("role_assignments")));++PlanRevision;
    }
    auto Queue=[&](const Object& C,int32 Index,const FString& Reason)
    {
        FCommand Command;Command.Decision=Id;Command.Index=Index;Command.Key=Id+TEXT(":")+FString::FromInt(Index);
        Command.Sequence=++CommandSequence;Command.Revision=PlanRevision;
        Command.Agent=Text(C,TEXT("agent_id"));Command.Action=Text(C,TEXT("action"));Command.Parameters=C->GetObjectField(TEXT("parameters"));
        Command.Due=Hops.Contains(Command.Agent)?Time()+Latency*Hops.FindChecked(Command.Agent):-1;Command.Deadline=Time()+5;
        Command.PublicResult=Obj({{TEXT("decision_id"),Str(Id)},{TEXT("command_index"),Num(Index)},
            {TEXT("agent_id"),Str(Command.Agent)},{TEXT("action"),Str(Command.Action)},
            {TEXT("command_id"),Str(Command.Key)},{TEXT("plan_revision"),Num(Command.Revision)},
            {TEXT("validation_status"),Str(Reason.IsEmpty()?TEXT("accepted"):TEXT("rejected"))},
            {TEXT("delivery_status"),Str(Reason.IsEmpty()?TEXT("queued"):TEXT("not_required"))},
            {TEXT("execution_status"),Str(TEXT("not_started"))},{TEXT("reason_code"),Reason.IsEmpty()?Null():Str(Reason)},
            {TEXT("updated_at"),Num(Time())}});
        if(!Reason.IsEmpty())Command.Finished=true;
        Commands.Add(MoveTemp(Command));
    };
    int32 InternalIndex=-1;
    TSet<FString> Participants;
    for(const auto& Role:PriorRoles->Values)Participants.Add(FString(*Role.Key));
    for(const auto& Role:DesiredRoles->Values)Participants.Add(FString(*Role.Key));
    for(const auto& Actual:ActualConfigurations)if(!Actual.Value.Role.IsEmpty())Participants.Add(Actual.Key);
    auto Ordered=Participants.Array();Ordered.Sort();
    for(const FString& Agent:Ordered)
    {
        if(Operation==TEXT("keep"))
        {
            const auto* Actual=ActualConfigurations.Find(Agent);
            if(!Hops.Contains(Agent)||(Actual&&Actual->Revision==PlanRevision)||Commands.ContainsByPredicate([&](const FCommand& C)
                {return C.Agent==Agent&&C.Action==TEXT("assign_role")&&C.Revision==PlanRevision&&!C.Finished;}))continue;
        }
        const FString Role=Text(DesiredRoles,Agent);
        Queue(Obj({{TEXT("agent_id"),Str(Agent)},{TEXT("action"),Str(TEXT("assign_role"))},
            {TEXT("parameters"),Json(Obj({{TEXT("role_id"),Role.IsEmpty()?Null():Str(Role)},
                {TEXT("scenario_ids"),Arr(AgentScenarios(Agent,Role))}}))}}),InternalIndex--,TEXT(""));
    }
    for(int32 I=0;I<Input.Num();I++)Queue(Input[I]->AsObject(),I,Reasons[I]);
    if(Operation==TEXT("safe_stop"))
    {
        SafeStopRequested=true;
        for(AMRAgent* A:World->Agents)if(A->CanMove())Queue(Obj({{TEXT("agent_id"),Str(A->AgentKey())},{TEXT("action"),Str(TEXT("hold"))},
            {TEXT("parameters"),Json(Obj())}}),InternalIndex--,TEXT(""));
    }
    Record(TEXT("decision"),R.Request);
    if(!StorageError.IsEmpty())
    {
        Snapshot(RequestId);for(const auto& Complete:StepCallbacks)Error(Complete,TEXT("INTERNAL_ERROR"),StorageError,RequestId,500);
        StepCallbacks.Empty();StepRequest.Reset();StepBody.Empty();return;
    }
    Clock.BeginStep(Horizon);ActiveStep=true;
    UpdateCommands();ConfigureExecutionDelta();UGameplayStatics::SetGamePaused(World,false);
}

void FMRCoreRuntime::FinishStep()
{
    UGameplayStatics::SetGamePaused(World,true);ActiveStep=false;
    FApp::SetFixedDeltaTime(FMRCoreClock::Quantum);if(Realtime)GEngine->FixedFrameRate=60;
    const FString RequestId=Text(StepRequest,TEXT("request_id"));UpdateFreshnessEvents();Snapshot(RequestId);
    Record(TEXT("observation"),CachedObservation);
    if(Status!=TEXT("running"))FlushSubstepWindows();
    RecordTruthSnapshot(Status==TEXT("running")?TEXT("step"):TEXT("terminal"));
    CaptureOverviewFrame();
    if(!StorageError.IsEmpty())Snapshot(RequestId);
    const FString Response=MRCoreJson::Write(EpisodeResponse(RequestId,true));
    const bool Stored=StoreReplay(Text(StepRequest,TEXT("decision_id")),{StepBody,Response,200})&&FlushArchive();
    if(!Stored)Snapshot(RequestId);
    for(auto& C:Commands)
    {
        C.PublicDirty=false;
        if(C.Finished)if(auto* A=FindAgent(C.Agent))A->ForgetCompletedCoreCommand(C.Key);
    }
    Commands.RemoveAll([](const FCommand& C){return C.Finished;});
    ArchiveManifest(TEXT("open"));
    for(const auto& Complete:StepCallbacks)
        if(Stored&&StorageError.IsEmpty())Reply(Complete,Response);else Error(Complete,TEXT("INTERNAL_ERROR"),StorageError,RequestId,500);
    StepCallbacks.Empty();StepRequest.Reset();StepBody.Empty();
    while(!ActiveStep&&!Waiting.IsEmpty())
    {FPending Next=MoveTemp(Waiting[0]);Waiting.RemoveAt(0);Mutate(MoveTemp(Next));}
}
