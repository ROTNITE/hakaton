#include "MRMissionSession.h"
#include "MRCoreJson.h"
#include "MRCoreRuntime.h"
#include "MRCoreValues.h"
#include "MRWorld.h"
#include "HttpModule.h"
#include "Interfaces/IHttpRequest.h"
#include "Interfaces/IHttpResponse.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformTime.h"
#include "HAL/PlatformMisc.h"
#include "Serialization/JsonSerializer.h"

using namespace MRCoreValues;

namespace
{
Object DefaultProductConfiguration()
{
    return Obj({{TEXT("format"),Str(TEXT("metarescue.product-request.v1"))},
        {TEXT("settings"),Json(Obj({{TEXT("map_size"),Num(25)},{TEXT("seed"),Num(2026)},
            {TEXT("preset"),Str(TEXT("urban"))},{TEXT("layout"),Str(TEXT("rescue_quarter"))},
            {TEXT("city_revision"),Str(TEXT("2.2"))},{TEXT("scouts"),Num(3)},{TEXT("rescuers"),Num(4)},
            {TEXT("people"),Num(16)},{TEXT("horizon"),Num(480)},{TEXT("event_profile"),Str(TEXT("v052"))},
            {TEXT("resource_profile"),Str(TEXT("contest"))},{TEXT("competition"),Bool(false)},
            {TEXT("ground_battery_wh"),Num(220)},{TEXT("aerial_battery_wh"),Num(120)},
            {TEXT("initial_battery_fraction"),Num(1)},{TEXT("energy_reserve_fraction"),Num(.10)},
            {TEXT("sensor_reliability"),Num(1)},{TEXT("communication_range_m"),Num(180)},
            {TEXT("communication_latency_s"),Num(.2)},{TEXT("communication_loss"),Num(0)},
            {TEXT("probabilities"),Json(Obj({{TEXT("collapse"),Num(20)},{TEXT("fire"),Num(18)},
                {TEXT("flood"),Num(12)},{TEXT("mud"),Num(25)},{TEXT("road_damage"),Num(23)},
                {TEXT("smoke"),Num(28)},{TEXT("appearance"),Num(30)}}))}}))},
        {TEXT("controller"),Json(Obj({{TEXT("policy"),Str(TEXT("nsga2_nsga2"))},{TEXT("optimizer_seed"),Num(2026)},
            {TEXT("ai_mode"),Str(TEXT("OFF"))},{TEXT("ai_scope"),Str(TEXT("global_local"))},
            {TEXT("contest_coordination"),Bool(true)},{TEXT("realtime"),Bool(true)},
            {TEXT("scout_population"),Num(40)},{TEXT("scout_generations"),Num(32)},
            {TEXT("rescue_population"),Num(26)},{TEXT("rescue_generations"),Num(17)}}))}});
}
}

UMRMissionSession* UMRMissionSession::Get(const UWorld* World)
{return World?Cast<UMRMissionSession>(World->GetGameInstance()):nullptr;}

Object UMRMissionSession::ReadObject(const FString& File)
{
    FString Body;Object Result;
    if(!FFileHelper::LoadFileToString(Body,*File)||!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Body),Result))return nullptr;
    return Result;
}

bool UMRMissionSession::SaveObject(const FString& File,const Object& ObjectToSave)
{
    const FString Temporary=File+TEXT(".tmp");
    if(!FFileHelper::SaveStringToFile(MRCoreJson::Write(ObjectToSave),*Temporary,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM)||
        !IFileManager::Get().Move(*File,*Temporary,true,true,false,true))
    {Error=TEXT("Не удалось сохранить управляющий файл. Подробности в журнале приложения.");return false;}
    return true;
}

void UMRMissionSession::Init()
{
    Super::Init();
    Enabled=FParse::Value(FCommandLine::Get(),TEXT("MRProductSession="),SessionFile);
    if(!Enabled)return;
    Configuration=DefaultProductConfiguration();
    const auto Lease=ReadObject(SessionFile);
    if(!Lease||Text(Lease,TEXT("format"))!=TEXT("metarescue.product-session.v1"))
    {Stage=TEXT("error");Error=TEXT("Не удалось прочитать сеанс запуска приложения.");return;}
    Workspace=Text(Lease,TEXT("workspace"));SourceRoot=Text(Lease,TEXT("source_root"));Python=Text(Lease,TEXT("python"));
    if(Workspace.IsEmpty()||!FPaths::DirectoryExists(Workspace)||!FPaths::FileExists(Python)||!FPaths::FileExists(SourceRoot/TEXT("tools/product_session.py")))
    {Stage=TEXT("error");Error=TEXT("Файлы запуска приложения недоступны. Откройте приложение штатной командой.");return;}
    ConfigurationReady=true;
    Port=Lease->GetIntegerField(TEXT("port"));HealthPort=Lease->GetIntegerField(TEXT("health_port"));
    if(Is(Lease,TEXT("analytics_port"),EJson::Number))AnalyticsPort=Lease->GetIntegerField(TEXT("analytics_port"));
    if(Is(Lease,TEXT("configuration"),EJson::Object))Configuration=MRCoreJson::Copy(Lease->GetObjectField(TEXT("configuration")));
    TickHandle=FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateUObject(this,&UMRMissionSession::TickSession),.1f);
    StartHelper(TEXT("inspect"),Workspace/TEXT("inspect/request.json"));
    LogAction(TEXT("application_opened"));
}

void UMRMissionSession::Shutdown()
{
    if(Enabled)
    {
        if(RunnerProcess.IsValid()&&FPlatformProcess::IsProcRunning(RunnerProcess))WriteControl(TEXT("stopping"));
        LogAction(TEXT("application_closed"));
        if(TickHandle.IsValid())FTSTicker::GetCoreTicker().RemoveTicker(TickHandle);
        if(HelperProcess.IsValid())FPlatformProcess::CloseProc(HelperProcess);
        if(RunnerProcess.IsValid())FPlatformProcess::CloseProc(RunnerProcess);
    }
    Super::Shutdown();
}

void UMRMissionSession::BindWorld(AMRWorld* World)
{Mission=World;if(!LayoutFile.IsEmpty()){Stage=TEXT("warming");Message=TEXT("Подготовка физики и подключение контроллера…");WriteState();}}

bool UMRMissionSession::IsRealtime() const
{return Configuration&&Configuration->GetObjectField(TEXT("controller"))->GetBoolField(TEXT("realtime"));}

bool UMRMissionSession::Busy() const
{return Stage==TEXT("preparing")||Stage==TEXT("loading")||Stage==TEXT("warming")||Stage==TEXT("connecting")||Stage==TEXT("stopping");}

bool UMRMissionSession::CanOperate() const
{return Stage==TEXT("running")||Stage==TEXT("paused")||Stage==TEXT("stepping");}

bool UMRMissionSession::CanPrepare() const
{return ConfigurationReady&&!Busy()&&!RunnerProcess.IsValid()&&!HelperProcess.IsValid();}

bool UMRMissionSession::StartHelper(const FString& Operation,const FString& Request)
{
    if(HelperProcess.IsValid())
    {
        if(FPlatformProcess::IsProcRunning(HelperProcess)){Error=TEXT("Дождитесь завершения текущей подготовки.");return false;}
        FPlatformProcess::CloseProc(HelperProcess);
    }
    IFileManager::Get().MakeDirectory(*FPaths::GetPath(Request),true);
    const FString Parameters=FString::Printf(TEXT("-B -X utf8 -m tools.product_session %s --session \"%s\" --request \"%s\""),*Operation,*SessionFile,*Request);
    HelperProcess=FPlatformProcess::CreateProc(*Python,*Parameters,false,true,true,nullptr,0,*SourceRoot,nullptr);
    if(!HelperProcess.IsValid()){Error=TEXT("Не удалось запустить подготовку. Проверьте установку Python.");return false;}
    HelperOperation=Operation;HelperRequest=Request;return true;
}

void UMRMissionSession::Prepare()
{
    if(!CanPrepare())return;
    Error.Empty();Message=TEXT("Генерация района и проверка свободных выездов…");
    const FString Request=Workspace/TEXT("requests")/FGuid::NewGuid().ToString(EGuidFormats::Digits)/TEXT("request.json");
    IFileManager::Get().MakeDirectory(*FPaths::GetPath(Request),true);
    if(!SaveObject(Request,Configuration))return;
    if(StartHelper(TEXT("prepare"),Request)){Stage=TEXT("preparing");LogAction(TEXT("prepare_requested"));}
}

void UMRMissionSession::ReadHelperResult(int32 Code)
{
    const auto Result=ReadObject(FPaths::GetPath(HelperRequest)/TEXT("result.json"));
    if(Code!=0||!Result||Text(Result,TEXT("state"))==TEXT("failed"))
    {
        Error=Result?Text(Result,TEXT("error")):TEXT("Подготовка завершилась без результата. Откройте журнал приложения.");
        if(HelperOperation==TEXT("prepare"))Stage=TEXT("error");
        Message.Empty();LogAction(TEXT("helper_failed"));return;
    }
    if(Is(Result,TEXT("presets"),EJson::Array))Presets=Result->GetArrayField(TEXT("presets"));
    Error.Empty();
    if(Is(Result,TEXT("availability"),EJson::Object))Availability=Result->GetObjectField(TEXT("availability"));
    if(HelperOperation==TEXT("prepare"))
    {
        ActiveRequest=HelperRequest;LayoutFile=Text(Result,TEXT("layout"));ControlSession=Text(Result,TEXT("control_session"));
        CoreReset.Reset();
        Configuration=Result->GetObjectField(TEXT("configuration"));
        RunDirectory=FPaths::GetPath(FPaths::GetPath(Workspace))/TEXT("missions")/Text(Result,TEXT("run_name"));
        Stage=TEXT("loading");Message=TEXT("Район проверен. Загрузка трёхмерного мира…");SetupOpen=false;
        ControllerStarted=false;ControlRevision=StepTotal=0;DesiredMode=TEXT("paused");Health.Reset();SelectedAgent.Empty();
        // Travel is scheduled for a later engine phase. Never attach a runner
        // to the previous world's still-ready Core during that interval.
        Mission.Reset();HealthPending=false;++HealthPollToken;
        LogAction(TEXT("world_prepared"));
        UGameplayStatics::OpenLevel(this,FName(TEXT("/Game/Maps/RescueQuarter")));
    }
    else if(HelperOperation==TEXT("save-preset")){Message=TEXT("Пресет сохранён.");LogAction(TEXT("preset_saved"));}
}

bool UMRMissionSession::StartController()
{
    if(ControllerStarted)return true;
    if(RunnerProcess.IsValid())FPlatformProcess::CloseProc(RunnerProcess);
    const FString Parameters=FString::Printf(TEXT("-B -X utf8 -m tools.product_session attach --session \"%s\" --request \"%s\""),*SessionFile,*ActiveRequest);
    RunnerProcess=FPlatformProcess::CreateProc(*Python,*Parameters,false,true,true,nullptr,0,*SourceRoot,nullptr);
    if(!RunnerProcess.IsValid()){Stage=TEXT("error");Error=TEXT("Не удалось подключить контроллер.");return false;}
    ControllerStarted=true;Stage=TEXT("connecting");LogAction(TEXT("controller_started"));return true;
}

bool UMRMissionSession::WriteControl(const FString& Mode)
{
    if(ActiveRequest.IsEmpty())return false;
    const auto Control=Obj({{TEXT("format"),Str(TEXT("metarescue.operator-control.v1"))},{TEXT("session_id"),Str(ControlSession)},
        {TEXT("revision"),Num(++ControlRevision)},{TEXT("mode"),Str(Mode)},{TEXT("step_total"),Num(StepTotal)}});
    if(!SaveObject(FPaths::GetPath(ActiveRequest)/TEXT("control.json"),Control))return false;
    DesiredMode=Mode;LogAction(TEXT("control_")+Mode);return true;
}

void UMRMissionSession::Run(){if(CanOperate()&&WriteControl(TEXT("running")))Stage=TEXT("running");}
void UMRMissionSession::Pause(){if(CanOperate()&&WriteControl(TEXT("paused")))Message=TEXT("Пауза после текущей секунды…");}
void UMRMissionSession::Step(){if(Stage==TEXT("paused")){++StepTotal;if(WriteControl(TEXT("paused")))Stage=TEXT("stepping");}}
void UMRMissionSession::Stop(){if(CanOperate()&&WriteControl(TEXT("stopping"))){Stage=TEXT("stopping");Message=TEXT("Ожидание подтверждённого торможения…");}}

void UMRMissionSession::NewSetup()
{if(!Busy()&&!CanOperate()){SetupOpen=true;LogAction(TEXT("setup_opened"));}}

void UMRMissionSession::SavePreset(const FString& Title)
{
    if(!ConfigurationReady||Busy()||!SetupOpen)return;
    const FString Request=Workspace/TEXT("presets")/FGuid::NewGuid().ToString(EGuidFormats::Digits)/TEXT("request.json");
    IFileManager::Get().MakeDirectory(*FPaths::GetPath(Request),true);
    if(SaveObject(Request,Obj({{TEXT("title"),Str(Title)},{TEXT("configuration"),Json(Configuration)}})))StartHelper(TEXT("save-preset"),Request);
}

void UMRMissionSession::LoadPreset(const FString& Id)
{
    if(Busy()||!SetupOpen)return;
    for(const auto& Value:Presets)if(Text(Value->AsObject(),TEXT("id"))==Id)
    {Configuration=MRCoreJson::Copy(Value->AsObject()->GetObjectField(TEXT("configuration")));Message=TEXT("Пресет загружен.");LogAction(TEXT("preset_loaded"));break;}
}

Object UMRMissionSession::Observation() const
{return Mission.IsValid()&&Mission->CoreRuntime?Mission->CoreRuntime->ObservationForInterface():nullptr;}

void UMRMissionSession::PollHealth()
{
    if(HealthPending)return;
    HealthPending=true;LastHealthPoll=FPlatformTime::Seconds();
    const int64 Token=++HealthPollToken;
    auto Request=FHttpModule::Get().CreateRequest();Request->SetURL(FString::Printf(TEXT("http://127.0.0.1:%d/v1/controller/health"),HealthPort));
    Request->SetVerb(TEXT("GET"));Request->SetTimeout(1.5f);
    TWeakObjectPtr<UMRMissionSession> Weak(this);
    Request->OnProcessRequestComplete().BindLambda([Weak,Token](FHttpRequestPtr,FHttpResponsePtr Response,bool Success)
    {
        if(!Weak.IsValid())return;auto* Session=Weak.Get();
        if(Token!=Session->HealthPollToken)return;
        Session->HealthPending=false;
        Object Data;
        if(Success&&Response&&Response->GetResponseCode()==200&&FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Response->GetContentAsString()),Data))
        {
            Session->Health=Data;
            if(Is(Data,TEXT("control"),EJson::Object))
            {
                const auto Control=Data->GetObjectField(TEXT("control"));const FString Mode=Text(Control,TEXT("effective_mode"));
                if(Text(Control,TEXT("session_id"))!=Session->ControlSession)return;
                const bool Acknowledged=Control->GetNumberField(TEXT("revision"))>=Session->ControlRevision;
                if(Acknowledged&&Session->Stage!=TEXT("complete")&&Session->Stage!=TEXT("error"))
                {
                    Session->Stage=Mode==TEXT("stopping")?TEXT("stopping"):Mode==TEXT("running")?TEXT("running"):
                        Control->GetNumberField(TEXT("completed_steps"))<Session->StepTotal?TEXT("stepping"):TEXT("paused");
                    if(Mode!=TEXT("stopping"))Session->Message.Empty();
                }
                if(Is(Control,TEXT("error"),EJson::String))Session->Error=Text(Control,TEXT("error"));
            }
            if(Is(Data,TEXT("ai"),EJson::Object))
            {
                const auto AI=Data->GetObjectField(TEXT("ai"));
                if(Session->Availability&&Is(AI,TEXT("budget"),EJson::Object))
                {auto Budget=AI->GetObjectField(TEXT("budget"));Session->Availability->SetField(TEXT("budget_used"),Field(Budget,TEXT("used")));Session->Availability->SetField(TEXT("budget_limit"),Field(Budget,TEXT("limit")));}
            }
        }
    });
    if(!Request->ProcessRequest())HealthPending=false;
}

bool UMRMissionSession::TickSession(float)
{
    if(!Enabled)return false;
    if(HelperProcess.IsValid()&&!FPlatformProcess::IsProcRunning(HelperProcess))
    {int32 Code=1;FPlatformProcess::GetProcReturnCode(HelperProcess,&Code);FPlatformProcess::CloseProc(HelperProcess);ReadHelperResult(Code);}
    if(Mission.IsValid()&&Mission->CoreRuntime&&Mission->CoreRuntime->ReadyForInterface()&&!ControllerStarted&&!LayoutFile.IsEmpty())StartController();
    if(RunnerProcess.IsValid())
    {
        if(FPlatformProcess::IsProcRunning(RunnerProcess))
        {if(FPaths::FileExists(RunDirectory/TEXT("controller/manifest.json"))&&FPlatformTime::Seconds()-LastHealthPoll>.35)PollHealth();}
        else
        {
            int32 Code=1;FPlatformProcess::GetProcReturnCode(RunnerProcess,&Code);FPlatformProcess::CloseProc(RunnerProcess);
            const auto Result=ReadObject(FPaths::GetPath(ActiveRequest)/TEXT("attach-result.json"));
            if(Code==0&&Result&&Text(Result,TEXT("state"))==TEXT("complete"))
            {Stage=TEXT("complete");Message=TEXT("Эпизод завершён. Журналы и аналитика сохранены.");}
            else {Stage=TEXT("error");Error=Result?Text(Result,TEXT("error")):TEXT("Контроллер завершился с ошибкой. Откройте журнал запуска.");}
            LogAction(TEXT("controller_finished"));
        }
    }
    if(FPlatformTime::Seconds()-LastStateWrite>=1)WriteState();
    return true;
}

void UMRMissionSession::LogAction(const FString& Action)
{
    if(Workspace.IsEmpty())return;
    const auto Data=Obj({{TEXT("wall_utc"),Str(FDateTime::UtcNow().ToIso8601())},{TEXT("action"),Str(Action)},
        {TEXT("stage"),Str(Stage)},{TEXT("error"),Error.IsEmpty()?Null():Str(Error)},
        {TEXT("episode_time"),Observation()?Field(Observation(),TEXT("time")):Num(0)}});
    if(!FFileHelper::SaveStringToFile(MRCoreJson::Write(Data)+TEXT("\n"),*(Workspace/TEXT("ui.jsonl")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,
        &IFileManager::Get(),FILEWRITE_Append))Error=TEXT("Ошибка записи журнала действий интерфейса.");
    WriteState();
}

void UMRMissionSession::WriteState()
{
    LastStateWrite=FPlatformTime::Seconds();
    SaveObject(Workspace/TEXT("product-state.json"),Obj({{TEXT("stage"),Str(Stage)},{TEXT("message"),Str(Message)},
        {TEXT("error"),Str(Error)},{TEXT("layout"),Str(LayoutFile)},{TEXT("active_request"),Str(ActiveRequest)},
        {TEXT("run_directory"),Str(RunDirectory)},{TEXT("control_session"),Str(ControlSession)},
        {TEXT("control_revision"),Num(ControlRevision)},{TEXT("step_total"),Num(StepTotal)},
        {TEXT("configuration"),Json(Configuration)},{TEXT("health"),Health?Json(Health):Null()},
        {TEXT("display"),DisplayMetrics?Json(DisplayMetrics):Null()},
        {TEXT("episode_time"),Observation()?Field(Observation(),TEXT("time")):Num(0)}}));
}

void UMRMissionSession::OpenAnalytics()
{
    FString Url=FString::Printf(TEXT("http://127.0.0.1:%d/"),AnalyticsPort);
    if(!RunDirectory.IsEmpty())Url+=TEXT("?run=mission-")+FPaths::GetCleanFilename(RunDirectory);
    FPlatformProcess::LaunchURL(*Url,nullptr,nullptr);LogAction(TEXT("analytics_opened"));
}

FString UMRMissionSession::StageLabel() const
{
    if(Stage==TEXT("setup"))return TEXT("Новая миссия");
    if(Stage==TEXT("paused"))return TEXT("Пауза");
    if(Stage==TEXT("running"))return TEXT("Миссия выполняется");
    if(Stage==TEXT("stepping"))return TEXT("Одиночный шаг");
    if(Stage==TEXT("complete"))return TEXT("Эпизод завершён");
    if(Stage==TEXT("error"))return TEXT("Нужна проверка");
    if(Stage==TEXT("stopping"))return TEXT("Безопасная остановка");
    return TEXT("Подготовка миссии");
}
