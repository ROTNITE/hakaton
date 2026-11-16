#pragma once
#include "CoreMinimal.h"
#include "Engine/GameInstance.h"
#include "Dom/JsonObject.h"
#include "HAL/PlatformProcess.h"
#include "MRMissionSession.generated.h"

class AMRWorld;
struct FMRCoreResetState;

// UI/session orchestration only. The independent controller still owns decisions.
UCLASS()
class METARESCUE_API UMRMissionSession : public UGameInstance
{
    GENERATED_BODY()
public:
    virtual void Init() override;
    virtual void Shutdown() override;
    static UMRMissionSession* Get(const UWorld* World);
    bool Enabled=false,ConfigurationReady=false,SetupOpen=true,InspectorOpen=true;
    bool CaptureOverview=false;
    bool ObserverView=false,ShowTrails=true,ShowRoutes=true,ShowNetwork=false;
    bool ShowHazards=true,ShowCoverage=false,ShowScenarios=false;
    FString Stage=TEXT("setup"),Message,Error,LayoutFile,RunDirectory,SelectedAgent;
    FString ActiveRequest,ControlSession;
    int32 Port=8130,HealthPort=8131,AnalyticsPort=8140;
    TSharedPtr<FJsonObject> Configuration,Health,Availability;
    TSharedPtr<FJsonObject> DisplayMetrics;
    TArray<TSharedPtr<FJsonValue>> Presets;
    TWeakObjectPtr<AMRWorld> Mission;
    TSharedPtr<FMRCoreResetState> CoreReset;
    void BindWorld(AMRWorld* World);
    bool IsRealtime() const;
    bool Busy() const;
    bool CanOperate() const;
    bool CanPrepare() const;
    void Prepare();
    void Run();
    void Pause();
    void Step();
    void Stop();
    void NewSetup();
    void SavePreset(const FString& Title);
    void LoadPreset(const FString& Id);
    void OpenAnalytics();
    void LogAction(const FString& Action);
    TSharedPtr<FJsonObject> Observation() const;
    FString StageLabel() const;
private:
    FTSTicker::FDelegateHandle TickHandle;
    FProcHandle HelperProcess,RunnerProcess;
    FString SessionFile,Workspace,SourceRoot,Python,HelperOperation,HelperRequest;
    FString DesiredMode=TEXT("paused");
    int64 ControlRevision=0,StepTotal=0;
    int64 HealthPollToken=0;
    bool ControllerStarted=false,HealthPending=false;
    double LastHealthPoll=0,LastStateWrite=0;
    bool TickSession(float Delta);
    bool StartHelper(const FString& Operation,const FString& Request);
    bool StartController();
    void ReadHelperResult(int32 Code);
    bool WriteControl(const FString& Mode);
    void PollHealth();
    void WriteState();
    static TSharedPtr<FJsonObject> ReadObject(const FString& File);
    bool SaveObject(const FString& File,const TSharedPtr<FJsonObject>& Object);
};
