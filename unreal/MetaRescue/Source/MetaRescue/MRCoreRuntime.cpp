#include "MRCoreRuntime.h"
#include "MRCoreJson.h"
#include "MRCoreReset.h"
#include "MRCoreValues.h"
#include "MRMissionSession.h"
#include "MRWorld.h"
#include "MRAgent.h"
#include "MRCameraPawn.h"
#include "HttpServerModule.h"
#include "IHttpRouter.h"
#include "HttpServerRequest.h"
#include "HttpServerResponse.h"
#include "Engine/World.h"
#include "Engine/Engine.h"
#include "Kismet/GameplayStatics.h"
#include "HAL/PlatformFileManager.h"
#include "Misc/App.h"
#include "Misc/Paths.h"
#include "Misc/Guid.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Serialization/JsonSerializer.h"
#include "ProceduralMeshComponent.h"
#include "UnrealClient.h"

using namespace MRCoreValues;

FMRCoreRuntime::~FMRCoreRuntime(){Stop();}

bool FMRCoreRuntime::Start(int32 Port)
{
    if(Port<1024||Port>65535||Started)return false;
    if(World->bDisasterCity&&World->CityLayout->HasField(TEXT("hydrology"))&&!World->UrbanWater)
    {UE_LOG(LogTemp,Error,TEXT("MR_CORE refusing an incomplete hydraulic world"));return false;}
    if(auto* Session=UMRMissionSession::Get(World->GetWorld()))
    {
        if(!Session->CoreReset)Session->CoreReset=MakeShared<FMRCoreResetState>();
        ResetState=Session->CoreReset;
        FParse::Value(FCommandLine::Get(),TEXT("MRCorePython="),ResetPython);
        FParse::Value(FCommandLine::Get(),TEXT("MRCoreSource="),ResetSource);
        if(!FPaths::FileExists(ResetPython)||!FPaths::FileExists(ResetSource/TEXT("environment/reset_layout.py")))
            ResetPython.Empty();
    }
    else ResetState=MakeShared<FMRCoreResetState>();
    Router=FHttpServerModule::Get().GetHttpRouter(Port,true);if(!Router)return false;
    for(const FString& Endpoint:{TEXT("health"),TEXT("capabilities"),TEXT("reset"),TEXT("observation"),TEXT("step"),TEXT("logs"),TEXT("close")})
    {
        const bool Get=Endpoint==TEXT("health")||Endpoint==TEXT("capabilities")||Endpoint==TEXT("observation")||Endpoint==TEXT("logs");
        auto Handle=Router->BindRoute(FHttpPath(TEXT("/v1/environment/")+Endpoint),
            Get?EHttpServerRequestVerbs::VERB_GET:EHttpServerRequestVerbs::VERB_POST,
            FHttpRequestHandler::CreateLambda([this,Endpoint](const FHttpServerRequest& Request,const FHttpResultCallback& Complete){return this->Handle(Endpoint,Request,Complete);}));
        if(!Handle){Stop();return false;}Routes.Add(Handle);
    }
    if(World->bCityLayout)
    {
        auto Settings=World->CityLayout->GetObjectField(TEXT("settings"));
        Horizon=Settings->GetNumberField(TEXT("horizon"));Latency=Settings->GetNumberField(TEXT("communication_latency_s"));
        RadioRange=Settings->GetNumberField(TEXT("communication_range_m"));Unlimited=Settings->GetStringField(TEXT("resource_profile"))==TEXT("unlimited");
        if(Is(Settings,TEXT("sensor_reliability"),EJson::Number))SensorReliability=Settings->GetNumberField(TEXT("sensor_reliability"));
        if(Is(Settings,TEXT("communication_loss"),EJson::Number))RadioLoss=Settings->GetNumberField(TEXT("communication_loss"));
    }
    if(!FMath::IsFinite(RadioLoss)||RadioLoss<0||RadioLoss>1)
    {UE_LOG(LogTemp,Error,TEXT("MR_CORE invalid radio loss"));Stop();return false;}
    if(!LoadResources()||!LoadContestTape()||!LoadScenarios()){Stop();return false;}
    DeclareZones();
    if(ResetState->StartupSeed==INDEX_NONE)
    {
        ResetState->StartupSeed=World->Seed;
        ResetState->Defaults=World->bCityLayout?World->CityLayout->GetObjectField(TEXT("settings")):Obj();
        ResetState->GenerateEvents=!World->CoreEventProfile.IsEmpty();
    }
    OldFixedStep=FApp::UseFixedTimeStep();OldFixedDelta=FApp::GetFixedDeltaTime();
    Realtime=FParse::Param(FCommandLine::Get(),TEXT("MRCoreRealtime"));
    if(const auto* Session=UMRMissionSession::Get(World->GetWorld());Session&&Session->Enabled)Realtime=Session->IsRealtime();
    CaptureEventFrames=FParse::Param(FCommandLine::Get(),TEXT("MRCoreCaptureEvents"));
    CaptureOverview=World->bCityLayout&&FParse::Param(FCommandLine::Get(),TEXT("MRCoreCaptureOverview"))&&
        !FParse::Param(FCommandLine::Get(),TEXT("NullRHI"));
    if(CaptureOverview)FParse::Value(FCommandLine::Get(),TEXT("MRCoreCaptureBaseAt="),CaptureBaseAt);
    if(auto* Session=UMRMissionSession::Get(World->GetWorld());CaptureOverview&&Session&&!Session->Enabled)
    {
        Session->CaptureOverview=true;
        Session->Mission=World;
        Session->SetupOpen=false;
        Session->InspectorOpen=false;
        if(auto* Camera=Cast<AMRCameraPawn>(UGameplayStatics::GetPlayerPawn(World,0)))Camera->SetPreset(1);
    }
    OldFixedFrameRate=GEngine->bUseFixedFrameRate;OldFrameRate=GEngine->FixedFrameRate;
    FApp::SetFixedDeltaTime(1./60.);FApp::SetUseFixedTimeStep(!Realtime);
    if(Realtime){GEngine->bUseFixedFrameRate=true;GEngine->FixedFrameRate=60;}
    Started=true;
    for(AMRAgent* Agent:World->Agents)Agent->AddTickPrerequisiteActor(World);
    PostTickHandle=FWorldDelegates::OnWorldPostActorTick.AddRaw(this,&FMRCoreRuntime::AfterPhysics);
    FHttpServerModule::Get().StartAllListeners();
    UE_LOG(LogTemp,Display,TEXT("MR_CORE listening on 127.0.0.1:%d; warming physics, external=1s execution=1/60s pacing=%s"),Port,Realtime?TEXT("realtime"):TEXT("accelerated"));
    return true;
}

void FMRCoreRuntime::Stop()
{
    if(OwnerExitTickHandle.IsValid()){FTSTicker::GetCoreTicker().RemoveTicker(OwnerExitTickHandle);OwnerExitTickHandle.Reset();}
    if(LayoutTickHandle.IsValid()){FTSTicker::GetCoreTicker().RemoveTicker(LayoutTickHandle);LayoutTickHandle.Reset();}
    if(LayoutWorker.IsValid())
    {
        if(FPlatformProcess::IsProcRunning(LayoutWorker))FPlatformProcess::TerminateProc(LayoutWorker,true);
        FPlatformProcess::CloseProc(LayoutWorker);LayoutWorker.Reset();
        FailReset(TEXT("INTERNAL_ERROR"),TEXT("Environment stopped while preparing the layout"),500);
    }
    if(Router)for(const auto& Route:Routes)Router->UnbindRoute(Route);
    Routes.Empty();Router.Reset();
    if(PostTickHandle.IsValid()){FWorldDelegates::OnWorldPostActorTick.Remove(PostTickHandle);PostTickHandle.Reset();}
    if(Started)
    {
        UGameplayStatics::SetGamePaused(World,false);
        FApp::SetFixedDeltaTime(OldFixedDelta);FApp::SetUseFixedTimeStep(OldFixedStep);
        if(GEngine){GEngine->bUseFixedFrameRate=OldFixedFrameRate;GEngine->FixedFrameRate=OldFrameRate;}
    }
    if(PublicJournal&&!Closed){FlushArchive();ArchiveManifest(TEXT("interrupted"));}
    Started=false;PublicJournal.Reset();TruthJournal.Reset();ReplayJournal.Reset();
    // Other Unreal plugins may own routes on the same HTTP module.
    // Never stop listeners owned by those plugins.
}

void FMRCoreRuntime::CaptureOverviewFrame()
{
    if(!CaptureOverview)return;
    if(OverviewFrame==0)
    {
        CaptureAtBase=false;
        if(auto* Camera=Cast<AMRCameraPawn>(UGameplayStatics::GetPlayerPawn(World,0)))Camera->SetPreset(1);
    }
    if(!CaptureAtBase&&CaptureBaseAt>=0&&Time()>=CaptureBaseAt)
        if(auto* Camera=Cast<AMRCameraPawn>(UGameplayStatics::GetPlayerPawn(World,0)))
        {Camera->SetPreset(0);CaptureAtBase=true;}
    const FString Folder=Directory/TEXT("overview");
    if(OverviewFrame==0&&!FPlatformFileManager::Get().GetPlatformFile().CreateDirectoryTree(*Folder))
    {
        ArchiveFailure(TEXT("Cannot create overview recording directory"));
        return;
    }
    const FString File=FString::Printf(TEXT("overview-%05d.png"),OverviewFrame++);
    FScreenshotRequest::RequestScreenshot(Folder/File,false,false);
    Record(TEXT("observer_frame_requested"),Obj({{TEXT("file"),Str(TEXT("overview/")+File)},
        {TEXT("view"),Str(CaptureAtBase?TEXT("base"):TEXT("overhead"))}}),false);
}

void FMRCoreRuntime::Reply(const FHttpResultCallback& Complete,const FString& Text,int32 HttpStatus)
{
    auto Response=FHttpServerResponse::Create(Text,TEXT("application/json; charset=utf-8"));
    Response->Code=static_cast<EHttpServerResponseCodes>(HttpStatus);
    Response->Headers.Add(TEXT("Cache-Control"),{TEXT("no-store")});Complete(MoveTemp(Response));
}

void FMRCoreRuntime::Error(const FHttpResultCallback& Complete,const FString& Code,const FString& Message,const FString& RequestId,int32 HttpStatus) const
{
    if(HttpStatus==0)
    {
        HttpStatus=Code==TEXT("UNKNOWN_EPISODE")?404:Code==TEXT("RESOURCE_EXHAUSTED")?409:
            Code==TEXT("INTERNAL_ERROR")?500:Code==TEXT("TIMEOUT")?503:
            Code==TEXT("INVALID_COMMAND")||Code==TEXT("INVALID_SCENARIO")||Code==TEXT("CONSTRAINT_VIOLATION")?422:400;
    }
    Reply(Complete,MRCoreJson::Write(Obj({{TEXT("protocol_version"),Str(TEXT("1.0"))},
        {TEXT("request_id"),RequestId.IsEmpty()?Null():Str(RequestId)},
        {TEXT("episode_id"),Episode.IsEmpty()?Null():Str(Episode)},
        {TEXT("error"),Json(Obj({{TEXT("code"),Str(Code)},{TEXT("message"),Str(Message)},{TEXT("details"),Json(Obj())}}))}})),HttpStatus);
}

bool FMRCoreRuntime::Handle(const FString& Endpoint,const FHttpServerRequest& Request,const FHttpResultCallback& Complete)
{
    check(IsInGameThread());
    FString RequestId=Request.QueryParams.FindRef(TEXT("request_id"));
    if(RequestId.IsEmpty())
    {
        const auto* Header=Request.Headers.Find(TEXT("x-request-id"));
        if(Header&&!Header->IsEmpty())RequestId=(*Header)[0];
    }
    if(RequestId.IsEmpty())RequestId=FGuid::NewGuid().ToString(EGuidFormats::Digits);
    if(Endpoint==TEXT("health"))
    {
        Reply(Complete,MRCoreJson::Write(Obj({{TEXT("protocol_version"),Str(TEXT("1.0"))},{TEXT("component"),Str(TEXT("environment"))},
            {TEXT("status"),Str(Ready&&!ResetState->Pending.IsSet()?TEXT("ready"):TEXT("initializing"))},{TEXT("environment_id"),Str(TEXT("metarescue_unreal"))},
            {TEXT("capabilities_url"),Str(TEXT("/v1/environment/capabilities"))}})));return true;
    }
    if(Endpoint==TEXT("capabilities")){Reply(Complete,MRCoreJson::Write(Capabilities()));return true;}
    if(Endpoint==TEXT("observation"))
    {
        if(!CachedObservation){Error(Complete,TEXT("UNKNOWN_EPISODE"),TEXT("Reset is required"),RequestId);return true;}
        const FString Requested=Request.QueryParams.FindRef(TEXT("episode_id"));
        if(!Requested.IsEmpty()&&Requested!=Episode)
        {Error(Complete,TEXT("UNKNOWN_EPISODE"),TEXT("Episode is not current"),RequestId);return true;}
        auto Result=MRCoreJson::Copy(CachedObservation);Result->SetStringField(TEXT("request_id"),RequestId);
        Reply(Complete,MRCoreJson::Write(Result));return true;
    }
    if(Endpoint==TEXT("logs"))
    {
        if(Episode.IsEmpty()){Error(Complete,TEXT("UNKNOWN_EPISODE"),TEXT("Reset is required"),RequestId);return true;}
        const FString Requested=Request.QueryParams.FindRef(TEXT("episode_id"));
        if(!Requested.IsEmpty()&&Requested!=Episode)
        {Error(Complete,TEXT("UNKNOWN_EPISODE"),TEXT("Episode is not current"),RequestId);return true;}
        int64 Cursor=0;int32 Limit=200;const FString* C=Request.QueryParams.Find(TEXT("cursor"));const FString* L=Request.QueryParams.Find(TEXT("limit"));
        if((C&&(!LexTryParseString(Cursor,**C)||Cursor<0||Cursor>PublicJournal->Num()))||
           (L&&(!LexTryParseString(Limit,**L)||Limit<1||Limit>1000)))
        {Error(Complete,TEXT("INVALID_REQUEST"),TEXT("Invalid public cursor or limit"),RequestId);return true;}
        TArray<Value> Records;int64 PageBytes=0;
        for(int64 I=Cursor;I<FMath::Min(Cursor+Limit,PublicJournal->Num());I++)
        {
            TArray<uint8> Raw;FString ReadError;
            if(!PublicJournal->Read(I,Raw,ReadError))
            {Error(Complete,TEXT("INTERNAL_ERROR"),ReadError,RequestId,500);return true;}
            if(PageBytes+Raw.Num()>8*1024*1024&&!Records.IsEmpty())break;
            const FUTF8ToTCHAR TextBytes(reinterpret_cast<const ANSICHAR*>(Raw.GetData()),Raw.Num());Object Record;
            if(!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(FString(TextBytes.Length(),TextBytes.Get())),Record)||!Record)
            {Error(Complete,TEXT("INTERNAL_ERROR"),TEXT("Corrupt public JSON record"),RequestId,500);return true;}
            PageBytes+=Raw.Num();Records.Add(Json(Record));
        }
        Reply(Complete,MRCoreJson::Write(Obj({{TEXT("protocol_version"),Str(TEXT("1.0"))},{TEXT("request_id"),Str(RequestId)},
            {TEXT("episode_id"),Str(Episode)},{TEXT("records"),Arr(Records)},{TEXT("next_cursor"),Num(Cursor+Records.Num())}})));return true;
    }
    Object Body;FString ParseError;
    if(!MRCoreJson::Parse(Request.Body,Body,ParseError)){Error(Complete,TEXT("INVALID_REQUEST"),ParseError);return true;}
    RequestId=Text(Body,TEXT("request_id"));
    if(Text(Body,TEXT("protocol_version"))!=TEXT("1.0"))
    {Error(Complete,TEXT("UNSUPPORTED_PROTOCOL_VERSION"),TEXT("Expected protocol_version=1.0"),RequestId);return true;}
    if(RequestId.IsEmpty()){Error(Complete,TEXT("INVALID_REQUEST"),TEXT("request_id is required"));return true;}
    if(!Ready&&!ResetState->Pending.IsSet())
    {Error(Complete,TEXT("CONSTRAINT_VIOLATION"),TEXT("Physics initialization is not complete"),RequestId);return true;}
    FPending Pending;Pending.Endpoint=Endpoint;Pending.Body=Request.Body;Pending.Request=Body;Pending.Complete=Complete;
    if(ActiveStep)
    {
        if(Endpoint==TEXT("step")&&Text(Body,TEXT("decision_id"))==Text(StepRequest,TEXT("decision_id")))
        {
            if(Request.Body!=StepBody)Error(Complete,TEXT("INVALID_REQUEST"),TEXT("decision_id body differs from pending request"),RequestId);
            else if(StepCallbacks.Num()>=16)Error(Complete,TEXT("RESOURCE_EXHAUSTED"),TEXT("Too many pending identical retries"),RequestId);
            else StepCallbacks.Add(Complete);
        }
        else if(Waiting.Num()>=64)Error(Complete,TEXT("RESOURCE_EXHAUSTED"),TEXT("Mutation queue is full"),RequestId);
        else Waiting.Add(MoveTemp(Pending));
    }
    else Mutate(MoveTemp(Pending));
    return true;
}

void FMRCoreRuntime::Mutate(FPending Request)
{
    if(Request.Endpoint==TEXT("reset")){Reset(Request);return;}
    if(ResetState->Pending.IsSet())
    {Error(Request.Complete,TEXT("CONSTRAINT_VIOLATION"),TEXT("World reset is in progress"),Text(Request.Request,TEXT("request_id")));return;}
    if(Text(Request.Request,TEXT("episode_id"))!=Episode||Episode.IsEmpty())
    {Error(Request.Complete,TEXT("UNKNOWN_EPISODE"),TEXT("Episode is not current"),Text(Request.Request,TEXT("request_id")));return;}
    if(Request.Endpoint==TEXT("step")){Step(Request);return;}
    if(!Closed)
    {
        if(Status==TEXT("running")){Status=TEXT("failed");OutcomeReason=TEXT("closed_by_client");}
        Closed=true;
        for(const auto& C:Commands)if(auto* A=FindAgent(C.Agent))A->ForgetCompletedCoreCommand(C.Key);
        Commands.Empty();Reports.Empty();UGameplayStatics::SetGamePaused(World,true);
        FlushSubstepWindows();
        RecordTruthSnapshot(TEXT("close"));
        Snapshot(Text(Request.Request,TEXT("request_id")));Record(TEXT("outcome"),Obj({{TEXT("status"),Str(Status)},{TEXT("reason"),Str(OutcomeReason)}}));
        FlushArchive();ArchiveManifest(TEXT("complete"));if(!StorageError.IsEmpty())Snapshot(Text(Request.Request,TEXT("request_id")));
        if(FParse::Param(FCommandLine::Get(),TEXT("MRCoreExitOnClose")))
            FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateLambda([](float){FPlatformMisc::RequestExit(false);return false;}),.5f);
        else if(!OwnerExitTickHandle.IsValid()&&StorageError.IsEmpty())
        {
            FString OwnerExitRequest;
            // A persistent acceptance client can complete terminal reads before its process owner requests exit.
            if(FParse::Value(FCommandLine::Get(),TEXT("MRCoreExitRequestFile="),OwnerExitRequest)&&
               !OwnerExitRequest.IsEmpty()&&!FPaths::IsRelative(OwnerExitRequest))
                OwnerExitTickHandle=FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateLambda([this,OwnerExitRequest](float)
                {
                    if(!Closed||!StorageError.IsEmpty()||!FPaths::FileExists(OwnerExitRequest))return true;
                    UE_LOG(LogTemp,Display,TEXT("MR_CORE owner requested exit after archive close"));
                    FPlatformMisc::RequestExit(false);
                    return false;
                }),.25f);
        }
    }
    Reply(Request.Complete,MRCoreJson::Write(Obj({{TEXT("protocol_version"),Str(TEXT("1.0"))},
        {TEXT("episode_id"),Str(Episode)},{TEXT("request_id"),Field(Request.Request,TEXT("request_id"))},
        {TEXT("time"),Num(Time())},{TEXT("status"),Str(Status)},{TEXT("closed"),Bool(true)}})));
}

void FMRCoreRuntime::AfterPhysics(UWorld* InWorld,ELevelTick TickType,float Dt)
{
    if(InWorld!=World->GetWorld()||!Started||Dt<=0||UGameplayStatics::IsGamePaused(World))return;
    if(!Ready)
    {
        if(++WarmupTicks<120)return;
        for(AMRAgent* A:World->Agents){A->AccountExecutedMovement();InitialPoses.Add(A->AgentKey(),A->GetActorTransform());}
        for(const auto& T:World->Targets)if(T.Visual)InitialTargetPoses.Add(T.Id,T.Visual->GetActorTransform());
        for(UProceduralMeshComponent* Piece:World->PhysicsPieces)if(Piece)
            InitialBodies.Add(Piece,{Piece->GetComponentTransform(),Piece->GetPhysicsLinearVelocity(),
                Piece->GetPhysicsAngularVelocityInRadians(),Piece->IsSimulatingPhysics()});
        Ready=true;UGameplayStatics::SetGamePaused(World,true);
        if(CaptureOverview)
            if(auto* Camera=Cast<AMRCameraPawn>(UGameplayStatics::GetPlayerPawn(World,0)))Camera->SetPreset(1);
        UE_LOG(LogTemp,Display,TEXT("MR_CORE ready; physics paused until reset/step"));
        CompleteResetTravel();return;
    }
    if(!ActiveStep)return;
    if(FMath::Abs(double(Dt)-ExecutionDelta)>1.e-5||!Clock.Advance(ExecutionDelta))
    {
        Status=TEXT("failed");OutcomeReason=TEXT("execution_clock_mismatch");
        UE_LOG(LogTemp,Error,TEXT("MR_CORE execution dt differs: actual=%.12f expected=%.12f"),double(Dt),ExecutionDelta);
        FinishStep();return;
    }
    for(AMRAgent* A:World->Agents)A->AccountExecutedMovement();
    UpdateResources(ExecutionDelta);
    AdvanceEvents();
    AdvanceContest();
    AdvanceServices();
    for(auto& T:World->Targets)
    {
        if(T.bAssigned&&T.Visual)T.Position=T.Visual->GetActorLocation();
        if(!T.bAvailabilityReported&&Time()+1.e-9>=T.AvailableAt)
        {T.bAvailabilityReported=true;if(T.Visual)T.Visual->SetActorHiddenInGame(false);Record(TEXT("target_became_observable"),Obj({{TEXT("target_id"),Str(FString::Printf(TEXT("person-%d"),T.Id))}}),false);}
    }
    if(Time()+1.e-9>=(TelemetrySamples+1)/10.)UpdateNetwork();
    if(Time()+1.e-9>=(SensorSamples+1)*.5){++SensorSamples;GatherReports();}
    DeliverReports();UpdateCommands();
    TrackSubsteps();
    if(Time()+1.e-9>=(TelemetrySamples+1)/10.)
    {
        ++TelemetrySamples;
        TArray<Value> Data;for(AMRAgent* A:World->Agents)Data.Add(Json(AgentSnapshot(A,Time())));
        Record(TEXT("agent_telemetry"),Obj({{TEXT("agents"),Arr(Data)}}),false);
    }
    if(Status==TEXT("running")&&World->Targets.Num()>0&&World->SavedCount()==World->Targets.Num())
    {Status=TEXT("success");OutcomeReason=TEXT("all_targets_evacuated");}
    if(Status==TEXT("running")&&Time()>=Horizon){Status=TEXT("time_limit");OutcomeReason=TEXT("horizon_reached");}
    if(Clock.StepFinished()||Status!=TEXT("running"))FinishStep();else ConfigureExecutionDelta();
}

void FMRCoreRuntime::BeforePhysics(float Dt)
{
    if(ActiveStep)UpdateCommands();
}

void FMRCoreRuntime::ConfigureExecutionDelta()
{
    TArray<double> Boundaries={(SensorSamples+1)*.5,(TelemetrySamples+1)/10.};
    for(const auto& C:Commands)if(!C.Finished)
    {
        if(!C.Delivered){Boundaries.Add(C.Due);Boundaries.Add(C.Deadline);}
        if(C.AckDue>=0)Boundaries.Add(C.AckDue);
        if(C.AckDeadline>=0)Boundaries.Add(C.AckDeadline);
        if(C.FinalStatus.IsEmpty()&&C.MessageDeadline>=0){Boundaries.Add(C.MessageDue);Boundaries.Add(C.MessageDeadline);}
        if(C.FinalStatus.IsEmpty()&&C.ServiceDue>=0)Boundaries.Add(C.ServiceDue);
    }
    for(const auto& R:Reports){Boundaries.Add(R.Due);Boundaries.Add(R.Deadline);}
    Boundaries.Add(World->Environment.NextBoundary());
    Boundaries.Add(NextContestBoundary());
    Boundaries.Add(NextOrbitalScan);Boundaries.Add(OrbitalDeliveryAt);
    for(const FString& Id:IssuedDirectives)if(auto Order=Directives.FindRef(Id))Boundaries.Add(Order->GetNumberField(TEXT("expires_at")));
    ExecutionDelta=Clock.NextDelta(Boundaries);FApp::SetFixedDeltaTime(ExecutionDelta);
    if(Realtime)GEngine->FixedFrameRate=float(1./ExecutionDelta);
}

void FMRCoreRuntime::Record(const FString& Type,const Object& Payload,bool Public)
{
    auto Record=Obj({{TEXT("trace_id"),Str(FGuid::NewGuid().ToString(EGuidFormats::Digits))},{TEXT("episode_id"),Str(Episode)},
        {TEXT("request_id"),StepRequest?Field(StepRequest,TEXT("request_id")):Null()},
        {TEXT("decision_id"),StepRequest?Field(StepRequest,TEXT("decision_id")):Null()},
        {TEXT("time"),Num(Time())},{TEXT("record_type"),Str(Type)},{TEXT("payload"),Json(Payload)}});
    const FString Line=MRCoreJson::Write(Record)+TEXT("\n");const FTCHARToUTF8 Bytes(*Line);
    TArray<uint8> Raw;Raw.Append(reinterpret_cast<const uint8*>(Bytes.Get()),Bytes.Length());FString Error;
    auto* Journal=Public?PublicJournal.Get():TruthJournal.Get();
    if(!Journal||!Journal->Append(Raw,Error))ArchiveFailure(Error);
}

void FMRCoreRuntime::PublishEvent(const FString& Id,const FString& Type,double OccurredAt,const FString& Source,
    const TArray<FString>& Subjects,const Object& Parameters,const FString& State,double Confidence)
{
    TArray<Value> Targets;
    for(const FString& Subject:Subjects)Targets.Add(Str(Subject));
    auto Event=Obj({{TEXT("id"),Str(Id)},{TEXT("type"),Str(Type)},{TEXT("time"),Num(OccurredAt)},
        {TEXT("source"),Str(Source)},{TEXT("targets"),Arr(Targets)},{TEXT("parameters"),Json(Parameters)},
        {TEXT("status"),Str(State)},{TEXT("confidence"),Num(Confidence)},{TEXT("received_at"),Num(Time())}});
    StepEvents.Add(Id,Event);
    Record(TEXT("event"),Event);
}
