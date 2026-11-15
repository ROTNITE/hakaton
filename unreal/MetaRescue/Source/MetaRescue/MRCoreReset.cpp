#include "MRCoreReset.h"
#include "MRCoreRuntime.h"
#include "MRCoreJson.h"
#include "MRCoreValues.h"
#include "MRWorld.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformTime.h"
#include "Serialization/JsonSerializer.h"

using namespace MRCoreValues;

namespace
{
const FString ResetMap=TEXT("/Game/Maps/RescueQuarter");
}

void FMRCoreRuntime::Reset(const FPending& R)
{
    const FString Id=Text(R.Request,TEXT("request_id"));
    if(ResetState->Pending.IsSet())
    {
        auto& Pending=ResetState->Pending.GetValue();
        if(Id!=Text(Pending.Request,TEXT("request_id")))
            Error(R.Complete,TEXT("CONSTRAINT_VIOLATION"),TEXT("World reset is in progress"),Id);
        else if(R.Body!=Pending.Body)
            Error(R.Complete,TEXT("INVALID_REQUEST"),TEXT("Reset ID body differs from pending request"),Id);
        else if(Pending.Callbacks.Num()>=16)
            Error(R.Complete,TEXT("RESOURCE_EXHAUSTED"),TEXT("Too many pending identical reset retries"),Id);
        else Pending.Callbacks.Add(R.Complete);
        return;
    }
    if(ResetState->AcceptedIds.Contains(ReplayKey(Id)))
    {
        if(Id!=ResetState->LastId||R.Body!=ResetState->LastBody)
            Error(R.Complete,TEXT("INVALID_REQUEST"),TEXT("Reset ID is old or its body differs"),Id);
        else Reply(R.Complete,ResetState->LastResponse);
        return;
    }
    if(ResetState->AcceptedIds.Num()>=4096)
    {Error(R.Complete,TEXT("RESOURCE_EXHAUSTED"),TEXT("Reset registry limit reached; restart required"),Id);return;}

    const auto SeedField=Field(R.Request,TEXT("seed"));
    const auto Mission=Field(R.Request,TEXT("mission"));
    const double Seed=SeedField&&SeedField->Type==EJson::Number?SeedField->AsNumber():-1;
    if(Seed<0||Seed>999999999||!FMath::IsFinite(Seed)||Seed!=int32(Seed)||
       !Mission||Mission->Type!=EJson::Object||Text(Mission->AsObject(),TEXT("id"))!=TEXT("search_and_rescue")||
       !Is(Mission->AsObject(),TEXT("parameters"),EJson::Object))
    {Error(R.Complete,TEXT("INVALID_REQUEST"),TEXT("Expected an integer seed in 0..999999999 and search_and_rescue mission parameters"),Id);return;}
    const auto Parameters=Mission->AsObject()->GetObjectField(TEXT("parameters"));
    if(Seed==World->Seed&&!ResetState->Customized&&Parameters->Values.IsEmpty())
    {BeginEpisode(R);return;}
    if(ResetPython.IsEmpty())
    {Error(R.Complete,TEXT("INVALID_REQUEST"),TEXT("This launch supports the startup configuration only; see capabilities"),Id);return;}
    if(!FPackageName::DoesPackageExist(ResetMap))
    {Error(R.Complete,TEXT("INTERNAL_ERROR"),TEXT("Reset map is unavailable"),Id,500);return;}

    auto& Pending=ResetState->Pending.Emplace();
    Pending.Request=R.Request;
    Pending.Body=R.Body;
    Pending.Callbacks.Add(R.Complete);
    if(Seed==ResetState->StartupSeed&&Parameters->Values.IsEmpty())
    {TravelForReset(FString(),false);return;}

    FString Root=FPlatformMisc::GetEnvironmentVariable(TEXT("METARESCUE_OUTPUT"));
    if(Root.IsEmpty())Root=TEXT("D:/MetaRescue-output");
    LayoutRequestDirectory=FPaths::ConvertRelativePathToFull(Root/TEXT("core-layouts")/FGuid::NewGuid().ToString(EGuidFormats::Digits));
    const auto Job=Obj({{TEXT("seed"),Num(Seed)},{TEXT("base"),Json(ResetState->Defaults)},
                        {TEXT("parameters"),Json(Parameters)},{TEXT("generate_events"),Bool(ResetState->GenerateEvents)}});
    if(!IFileManager::Get().MakeDirectory(*LayoutRequestDirectory,true)||
       !FFileHelper::SaveStringToFile(MRCoreJson::Write(Job),*(LayoutRequestDirectory/TEXT("request.json")),
                                      FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
    {FailReset(TEXT("INTERNAL_ERROR"),TEXT("Cannot persist layout preparation request"),500);return;}
    const FString Args=FString::Printf(TEXT("-B -X utf8 -m environment.reset_layout --directory \"%s\""),*LayoutRequestDirectory);
    LayoutWorker=FPlatformProcess::CreateProc(*ResetPython,*Args,false,true,true,nullptr,0,*ResetSource,nullptr);
    if(!LayoutWorker.IsValid())
    {FailReset(TEXT("INTERNAL_ERROR"),TEXT("Cannot start layout preparation"),500);return;}
    LayoutDeadline=FPlatformTime::Seconds()+45.;
    LayoutTickHandle=FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateRaw(this,&FMRCoreRuntime::PollLayout),.05f);
}

bool FMRCoreRuntime::PollLayout(float Delta)
{
    const bool Expired=FPlatformTime::Seconds()>LayoutDeadline;
    if(FPlatformProcess::IsProcRunning(LayoutWorker))
    {
        if(!Expired)return true;
        FPlatformProcess::TerminateProc(LayoutWorker,true);
    }
    int32 Code=-1;
    FPlatformProcess::GetProcReturnCode(LayoutWorker,&Code);
    FPlatformProcess::CloseProc(LayoutWorker);
    LayoutWorker.Reset();
    LayoutTickHandle.Reset();
    if(Expired){FailReset(TEXT("TIMEOUT"),TEXT("Layout preparation timed out"),503);return false;}

    FString Raw;
    Object Result;
    if(!FFileHelper::LoadFileToString(Raw,*(LayoutRequestDirectory/TEXT("result.json")))||
       !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Raw),Result)||!Result)
    {FailReset(TEXT("INTERNAL_ERROR"),TEXT("Layout worker did not produce a valid result"),500);return false;}
    if(Text(Result,TEXT("state"))==TEXT("failed"))
    {
        const FString ErrorCode=Text(Result,TEXT("code"));
        FailReset(ErrorCode==TEXT("INVALID_REQUEST")||ErrorCode==TEXT("CONSTRAINT_VIOLATION")?
                  ErrorCode:TEXT("INTERNAL_ERROR"),Text(Result,TEXT("message")));
        return false;
    }
    const FString LayoutFile=LayoutRequestDirectory/TEXT("layout.json");
    if(Code!=0||Text(Result,TEXT("state"))!=TEXT("prepared")||!FPaths::FileExists(LayoutFile)||
       Field(Result,TEXT("seed"))==nullptr||Result->GetNumberField(TEXT("seed"))!=
        ResetState->Pending->Request->GetNumberField(TEXT("seed")))
    {FailReset(TEXT("INTERNAL_ERROR"),TEXT("Layout worker result does not match request"),500);return false;}
    TravelForReset(LayoutFile,!ResetState->Pending->Request->GetObjectField(TEXT("mission"))
                       ->GetObjectField(TEXT("parameters"))->Values.IsEmpty());
    return false;
}

void FMRCoreRuntime::FailReset(const FString& Code,const FString& Message,int32 HttpStatus)
{
    if(!ResetState||!ResetState->Pending.IsSet())return;
    auto Pending=MoveTemp(ResetState->Pending.GetValue());
    ResetState->Pending.Reset();
    for(const auto& Complete:Pending.Callbacks)
        Error(Complete,Code,Message,Text(Pending.Request,TEXT("request_id")),HttpStatus);
}

void FMRCoreRuntime::TravelForReset(const FString& LayoutFile,bool Customized)
{
    FinalizeReplacement();
    ResetState->LayoutFile=LayoutFile;
    ResetState->Customized=Customized;
    ResetState->Pending->TravelScheduled=true;
    UGameplayStatics::OpenLevel(World,FName(*ResetMap));
}

void FMRCoreRuntime::CompleteResetTravel()
{
    if(!ResetState->Pending.IsSet()||!ResetState->Pending->TravelScheduled)return;
    auto Pending=MoveTemp(ResetState->Pending.GetValue());
    ResetState->Pending.Reset();
    FPending ResetRequest;
    ResetRequest.Request=MoveTemp(Pending.Request);
    ResetRequest.Body=MoveTemp(Pending.Body);
    ResetRequest.Complete=[Callbacks=MoveTemp(Pending.Callbacks)](TUniquePtr<FHttpServerResponse>&& Response)
    {
        for(int32 Index=0;Index<Callbacks.Num()-1;++Index)
            Callbacks[Index](MakeUnique<FHttpServerResponse>(*Response));
        Callbacks.Last()(MoveTemp(Response));
    };
    BeginEpisode(ResetRequest);
}

void FMRCoreRuntime::FinalizeReplacement()
{
    if(Episode.IsEmpty()||Closed)return;
    if(Status==TEXT("running")){Status=TEXT("failed");OutcomeReason=TEXT("replaced_by_reset");}
    Closed=true;
    FlushSubstepWindows();
    RecordTruthSnapshot(TEXT("replaced"));
    Record(TEXT("outcome"),Obj({{TEXT("status"),Str(Status)},{TEXT("reason"),Str(OutcomeReason)}}));
    FlushArchive();
    ArchiveManifest(TEXT("complete"));
}
