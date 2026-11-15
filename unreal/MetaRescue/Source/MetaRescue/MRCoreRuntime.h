#pragma once
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "HttpRouteHandle.h"
#include "HttpResultCallback.h"
#include "HAL/PlatformProcess.h"
#include "MRCoreStore.h"
#include "MRCoreClock.h"

class AMRWorld;
class AMRAgent;
class IHttpRouter;
class IFileHandle;
class UProceduralMeshComponent;
struct FHttpServerRequest;
struct FMRCoreResetState;

// Only the game thread mutates this object. HTTP GET serves CachedObservation.
class FMRCoreRuntime : public TSharedFromThis<FMRCoreRuntime>
{
public:
    explicit FMRCoreRuntime(AMRWorld* InWorld):World(InWorld){}
    ~FMRCoreRuntime();
    bool Start(int32 Port);
    void Stop();
    void BeforePhysics(float Dt);
    double Time() const {return Clock.Time();}
    bool ReadyForInterface() const {return Ready;}
    TSharedPtr<FJsonObject> ObservationForInterface() const {return CachedObservation;}
    TArray<TSharedPtr<FJsonValue>> PublicRoutesForInterface() const;
private:
    struct FCommand
    {
        FString Key,Decision,Agent,Action,Station,Recipient;
        int32 Index=0,TargetIndex=-1,TargetEpoch=-1;
        TSharedPtr<FJsonObject> Parameters,PublicResult,TargetReport,AgentReport,ServiceResult;
        double Due=0,Deadline=0,AckDue=-1,AckDeadline=-1;
        double MessageDue=-1,MessageDeadline=-1;
        double ServiceDue=-1;
        bool Delivered=false,Finished=false,PublicDirty=true;
        FString FinalStatus,Reason;
        int32 Revision=0,Sequence=0,DeliveryAttempts=0,AckAttempts=0,MessageAttempts=0;
    };
    enum class EPacket : uint8 { Pose,Target,Hazard,Command,Ack,Message };
    struct FReport
    {
        FString Agent,Target,MessageId;
        double Due=0,Deadline=-1;
        int32 TargetEpoch=0;
        int64 Sequence=0;
        int32 Attempts=0;
        TSharedPtr<FJsonObject> Data;
        EPacket Kind=EPacket::Pose;
    };
    struct FReplay
    {
        TArray<uint8> Body;
        FString Response;
        int32 HttpStatus=200;
    };
    struct FPending
    {
        TArray<uint8> Body;
        TSharedPtr<FJsonObject> Request;
        FString Endpoint;
        FHttpResultCallback Complete;
    };
    AMRWorld* World;
    TSharedPtr<IHttpRouter> Router;
    TArray<FHttpRouteHandle> Routes;
    FDelegateHandle PostTickHandle;
    bool Started=false,Ready=false,ActiveStep=false,Closed=false;
    bool SafeStopRequested=false;
    bool OldFixedStep=false;
    bool Realtime=false,OldFixedFrameRate=false;
    float OldFrameRate=0;
    double OldFixedDelta=0,Horizon=480,Latency=.2,RadioRange=180,RadioLoss=0,SensorReliability=1;
    bool Unlimited=true;
    double GroundBatteryWh=220,AerialBatteryWh=120,InitialBatteryFraction=1,ReserveFraction=.10;
    struct FChargeStation
    {
        FString Kind,AgentId;
        FVector Position;
        double RadiusCm=0,PowerW=0,CapacityWh=0,EnergyWh=0;
        int32 Ports=1;
    };
    TMap<FString,FChargeStation> ChargingStations;
    struct FContestEvent
    {
        FString Id,Type,Source;
        double At=0,Until=-1;
        TArray<FString> Subjects;
        TSharedPtr<FJsonObject> Parameters;
    };
    TArray<FContestEvent> ContestTape;
    TArray<int32> ActiveContest;
    int32 NextContest=0;
    TSet<FString> RadioMuted,DisabledInfrastructure;
    TMap<FString,TSharedPtr<FJsonObject>> Directives,Conflicts;
    TMap<int32,double> InitialPriorities;
    FMRCoreClock Clock;
    double ExecutionDelta=FMRCoreClock::Quantum;
    int64 SensorSamples=0,TelemetrySamples=0;
    struct FSubstepSample
    {
        double At, Energy;
        FVector Position,Velocity,Intended;
        FName Stop;
        int32 Contacts;
        bool Carrying,Operational;
    };
    struct FSubstepWindow
    {
        TArray<FSubstepSample> Recent,Window;
        int32 Cursor=0;
        double TriggerAt=0;
        FString Reason,Command;
    };
    TMap<FString,FSubstepWindow> Substeps;
    int32 SubstepWindowsStarted=0;
    int32 WarmupTicks=0;
    FString Episode,Status=TEXT("running"),OutcomeReason,Directory;
    TMap<FString,FTransform> InitialPoses;
    TMap<int32,FTransform> InitialTargetPoses;
    struct FPhysicsStart
    {
        FTransform Pose;
        FVector Linear,Angular;
        bool Simulating=false;
    };
    TMap<TWeakObjectPtr<UProceduralMeshComponent>,FPhysicsStart> InitialBodies;
    TMap<FString,TSharedPtr<FJsonObject>> KnownAgents,KnownTargets;
    TMap<FString,TSharedPtr<FJsonObject>> KnownZones,StepEvents;
    TArray<TSharedPtr<FJsonValue>> DeclaredZones;
    TMap<FString,double> SurfaceObservedAt;
    struct FEventView {double At;FVector Focus;FString Name;float Distance,Yaw;};
    bool CaptureEventFrames=false;
    bool CaptureOverview=false;
    bool CaptureAtBase=false;
    double CaptureBaseAt=-1;
    int32 OverviewFrame=0;
    double ViewStartedAt=-1;
    TSet<int32> ScheduledViews;
    TArray<FEventView> EventViews;
    TMap<FString,double> AgentReceived;
    struct FStaleAlert {FString Id;double StartedAt;};
    TMap<FString,FStaleAlert> StaleAlerts;
    TMap<FString,FStaleAlert> DegradationAlerts;
    struct FAgentConfiguration
    {
        FString Role;
        TArray<TSharedPtr<FJsonValue>> Scenarios;
        int32 Revision=0;
    };
    TMap<FString,FAgentConfiguration> ActualConfigurations;
    TMap<FString,double> SensorRadius;
    TMap<FString,int32> Hops;
    struct FSignal
    {
        FString Upstream;
        double Quality=1,LinkQuality=1,Success=1;
    };
    TMap<FString,FSignal> Signals;
    TMap<FString,int32> LastMotionSequence;
    TMap<FString,int32> LastRelaySequence;
    TSet<FString> RelayingAgents;
    TMap<FString,int32> MedicalKits;
    TMap<int32,int32> ReceivedKits;
    TMap<FString,TArray<TSharedPtr<FJsonObject>>> Inboxes;
    TMap<FString,int32> ComputeCredits;
    TSet<FString> IssuedDirectives;
    TSharedPtr<FJsonObject> PendingOrbital,KnownOrbital;
    double NextOrbitalScan=-1,OrbitalDeliveryAt=-1;
    int32 CommandSequence=0;
    TArray<FReport> Reports;
    TMap<FString,int32> ReportCounts;
    TArray<FCommand> Commands;
    TSharedPtr<FJsonObject> CachedObservation,Accepted,DesiredRoles;
    TMap<FString,TSharedPtr<FJsonObject>> ScenarioCatalog;
    int32 PlanRevision=0;
    // Fixed-size digest -> disk record; bodies/responses are not retained in RAM.
    TMap<FString,int64> ReplayKeys;
    TSharedPtr<FMRCoreResetState> ResetState;
    FString ResetPython,ResetSource,LayoutRequestDirectory;
    FProcHandle LayoutWorker;
    FTSTicker::FDelegateHandle LayoutTickHandle;
    FTSTicker::FDelegateHandle OwnerExitTickHandle;
    double LayoutDeadline=0;
    TArray<FPending> Waiting;
    TArray<FHttpResultCallback> StepCallbacks;
    TArray<uint8> StepBody;
    TSharedPtr<FJsonObject> StepRequest;
    TUniquePtr<FMRCoreDiskRecords> PublicJournal,TruthJournal,ReplayJournal;
    FString StorageError;
    void AfterPhysics(UWorld* InWorld,ELevelTick TickType,float Dt);
    bool Handle(const FString& Endpoint,const FHttpServerRequest& Request,const FHttpResultCallback& Complete);
    void Mutate(FPending Request);
    void Reset(const FPending& Request);
    void BeginEpisode(const FPending& Request);
    void FinalizeReplacement();
    void CompleteResetTravel();
    void CaptureOverviewFrame();
    void DeclareZones();
    void TrackSubsteps();
    void RecordSubstepWindow(const FString& Agent,FSubstepWindow& Window,bool Truncated=false);
    void FlushSubstepWindows();
    void TravelForReset(const FString& LayoutFile,bool Customized);
    void FailReset(const FString& Code,const FString& Message,int32 Status=0);
    bool PollLayout(float Delta);
    void Step(const FPending& Request);
    void FinishStep();
    void UpdateNetwork();
    void UpdateFreshnessEvents();
    void UpdateAgentKnowledge(const FString& Agent,const TSharedPtr<FJsonObject>& Report);
    void PublishEvent(const FString& Id,const FString& Type,double OccurredAt,const FString& Source,
        const TArray<FString>& Subjects,const TSharedPtr<FJsonObject>& Parameters,const FString& State=TEXT("new"),double Confidence=1.);
    void QueueReport(FReport Packet);
    void RemoveReport(int32 Index);
    bool PacketLost(const FString& Agent,EPacket Kind,int64 Sequence,int32 Attempt) const;
    void QueueAck(FCommand& Command,double Delay);
    void GatherReports();
    void DeliverReports();
    void UpdateCommands();
    void ResetTeamActions();
    bool KnownRecipient(const FString& Id) const;
    bool DeliverAid(FCommand& Command,AMRAgent* Agent);
    void ProgressMessage(FCommand& Command);
    void ResetServices();
    void AdvanceServices();
    bool StartCompute(FCommand& Command);
    bool IssueDirective(FCommand& Command);
    FString ValidateDirectiveInstruction(const TSharedPtr<FJsonObject>& Parameters) const;
    void UpdateDirectiveRestriction(const FString& Id,const TSharedPtr<FJsonObject>& Order);
    FString ValidateServiceCommand(const TSharedPtr<FJsonObject>& Command) const;
    bool LoadScenarios();
    FString ValidatePlan(const TSharedPtr<FJsonObject>& Request,FString& Code) const;
    TArray<TSharedPtr<FJsonValue>> AgentScenarios(const FString& AgentId,const FString& Role) const;
    bool LoadResources();
    bool LoadContestTape();
    void ResetContest();
    void AdvanceContest();
    double NextContestBoundary() const;
    void ResolveConflicts(const FString& Target,const FString& Source,double ObservedAt);
    void ResetResources();
    void UpdateResources(double Dt);
    bool CanStartCharge(const FString& StationId,const AMRAgent* Agent) const;
    TSharedPtr<FJsonObject> ChargeState(const FString& StationId) const;
    void Snapshot(const FString& RequestId);
    TSharedPtr<FJsonObject> AgentSnapshot(AMRAgent* Agent,double ObservedAt) const;
    TSharedPtr<FJsonObject> Capabilities() const;
    TSharedPtr<FJsonObject> EpisodeResponse(const FString& RequestId,bool StepResponse) const;
    FString ValidateDecision(const TSharedPtr<FJsonObject>& Request,FString& Code) const;
    FString ValidateCommand(const TSharedPtr<FJsonObject>& Command) const;
    AMRAgent* FindAgent(const FString& Id) const;
    int32 FindTarget(const FString& Id) const;
    void Record(const FString& Type,const TSharedPtr<FJsonObject>& Payload,bool Public=true);
    static FString ReplayKey(const FString& Id);
    bool LoadReplay(const FString& Id,FReplay& Replay,bool& Found);
    bool StoreReplay(const FString& Id,const FReplay& Replay);
    bool FlushArchive();
    void ArchiveFailure(const FString& Message);
    void ArchiveManifest(const FString& State);
    void ConfigureExecutionDelta();
    void RecordTruthSnapshot(const FString& Phase);
    void AdvanceEvents();
    void UpdateEventView();
    void GatherHazardReport(AMRAgent* Agent);
    void DeliverHazardReport(const FReport& Report);
    float SensorQuality(const FVector& Start,const FVector& End) const;
    bool SensorAccepts(AMRAgent* Agent,int32 Target,double Quality,int32 Channel) const;
    void Error(const FHttpResultCallback& Complete,const FString& Code,const FString& Message,const FString& RequestId=TEXT(""),int32 HttpStatus=0) const;
    static void Reply(const FHttpResultCallback& Complete,const FString& Text,int32 HttpStatus=200);
};
