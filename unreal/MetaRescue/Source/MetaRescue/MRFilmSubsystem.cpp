#include "MRFilmSubsystem.h"
#include "MRAgent.h"
#include "MRWorld.h"
#include "MRCoreRuntime.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/HUD.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "UnrealClient.h"
#include "HAL/FileManager.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Misc/App.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
bool FilmNumber(const TSharedPtr<FJsonObject>& Object,const TCHAR* Name,double& Value)
{return Object.IsValid()&&Object->TryGetNumberField(Name,Value)&&FMath::IsFinite(Value);}
bool FilmVector(const TSharedPtr<FJsonObject>& Object,const TCHAR* Name,FVector& Value)
{
    const TArray<TSharedPtr<FJsonValue>>* Array=nullptr;
    if(!Object.IsValid()||!Object->TryGetArrayField(Name,Array)||Array->Num()!=3)return false;
    double V[3];for(int32 I=0;I<3;I++)if(!(*Array)[I]->TryGetNumber(V[I])||!FMath::IsFinite(V[I])||FMath::Abs(V[I])>2000000)return false;
    Value=FVector(V[0],V[1],V[2]);return true;
}
TArray<TSharedPtr<FJsonValue>> FilmPoint(const FVector& P)
{return {MakeShared<FJsonValueNumber>(P.X),MakeShared<FJsonValueNumber>(P.Y),MakeShared<FJsonValueNumber>(P.Z)};}
FString FilmJson(const TSharedRef<FJsonObject>& Object)
{FString Text;FJsonSerializer::Serialize(Object,TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Text));return Text;}
bool FilmId(const FString& Id)
{
    if(Id.IsEmpty()||Id.Len()>64)return false;
    for(TCHAR C:Id)if(!(C>='a'&&C<='z')&&!(C>='A'&&C<='Z')&&!(C>='0'&&C<='9')&&C!='-'&&C!='_')return false;
    return true;
}
}

bool UMRFilmSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
    FString Plan;
    const UWorld* FilmWorld=Cast<UWorld>(Outer);
    return FilmWorld&&FilmWorld->IsGameWorld()&&FParse::Value(FCommandLine::Get(),TEXT("MRFilmPlan="),Plan)&&Super::ShouldCreateSubsystem(Outer);
}

TStatId UMRFilmSubsystem::GetStatId() const
{RETURN_QUICK_DECLARE_CYCLE_STAT(UMRFilmSubsystem,STATGROUP_Tickables);}

void UMRFilmSubsystem::Fail(const FString& Reason)
{
    if(Failed)return;Failed=true;Ready=false;
    UE_LOG(LogTemp,Error,TEXT("MR_FILM failed: %s"),*Reason);
    if(!Output.IsEmpty())FFileHelper::SaveStringToFile(Reason,*(Output/TEXT("failure.txt")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
    FPlatformMisc::RequestExitWithStatus(false,1);
}

bool UMRFilmSubsystem::ReadPlan(const FString& Path)
{
    FString Text;TSharedPtr<FJsonObject> Root;
    if(!FFileHelper::LoadFileToString(Text,*Path)||!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Root)||!Root.IsValid())return false;
    FString Format;double Rate=0,Pre=0;
    if(!Root->TryGetStringField(TEXT("format"),Format)||Format!=TEXT("metarescue.film.v1")||
       !FilmNumber(Root,TEXT("fps"),Rate)||Rate!=30||!FilmNumber(Root,TEXT("warmup_frames"),Pre)||Pre<0||Pre>3600||Pre!=FMath::FloorToDouble(Pre))return false;
    Fps=30;Warmup=static_cast<int32>(Pre);
    if(Root->HasField(TEXT("exit_on_finish"))&&!Root->TryGetBoolField(TEXT("exit_on_finish"),ExitOnFinish))return false;
    const TArray<TSharedPtr<FJsonValue>>* Items=nullptr;
    if(!Root->TryGetArrayField(TEXT("shots"),Items)||Items->IsEmpty()||Items->Num()>100)return false;
    TSet<FString> Ids;int64 Total=0;
    for(const auto& Item:*Items)
    {
        const auto Object=Item->AsObject();FMRFilmShot Shot;double Count=0,Wait=0;
        if(!Object.IsValid()||!Object->TryGetStringField(TEXT("id"),Shot.Id)||!FilmId(Shot.Id)||Ids.Contains(Shot.Id.ToLower())||
           !FilmNumber(Object,TEXT("frames"),Count)||Count<2||Count>18000||Count!=FMath::FloorToDouble(Count))return false;
        if(Object->HasField(TEXT("wait_frames"))&&(!FilmNumber(Object,TEXT("wait_frames"),Wait)||Wait<0||Wait>54000||Wait!=FMath::FloorToDouble(Wait)))return false;
        Shot.Frames=static_cast<int32>(Count);Shot.WaitFrames=static_cast<int32>(Wait);Total+=Shot.Frames+Shot.WaitFrames;
        if(Total>108000)return false;
        if(Object->HasField(TEXT("wait_until_s"))&&(!FilmNumber(Object,TEXT("wait_until_s"),Shot.WaitUntil)||Shot.WaitUntil<0||Shot.WaitUntil>3600))return false;
        double Delivered=0;
        if(Object->HasField(TEXT("wait_for_delivered"))&&(!FilmNumber(Object,TEXT("wait_for_delivered"),Delivered)||Delivered<0||Delivered>600||Delivered!=FMath::FloorToDouble(Delivered)))return false;
        Shot.WaitForDelivered=static_cast<int32>(Delivered);
        Object->TryGetStringField(TEXT("follow"),Shot.Follow);FString Space;
        Object->TryGetStringField(TEXT("follow_space"),Space);
        if(!Space.IsEmpty()&&Space!=TEXT("world")&&Space!=TEXT("heading"))return false;
        Shot.HeadingSpace=Space==TEXT("heading");Object->TryGetBoolField(TEXT("collision_test"),Shot.CollisionTest);
        const TArray<TSharedPtr<FJsonValue>>* Keys=nullptr;
        if(!Object->TryGetArrayField(TEXT("keys"),Keys)||Keys->Num()<2||Keys->Num()>64)return false;
        for(const auto& Entry:*Keys)
        {
            const auto KeyObject=Entry->AsObject();FMRFilmKey Key;
            if(!FilmNumber(KeyObject,TEXT("u"),Key.U)||Key.U<0||Key.U>1||
               !FilmNumber(KeyObject,TEXT("fov"),Key.Fov)||Key.Fov<15||Key.Fov>100||
               !FilmVector(KeyObject,TEXT("eye_cm"),Key.Eye)||!FilmVector(KeyObject,TEXT("look_cm"),Key.Look)||
               Key.Eye.Equals(Key.Look,1)||(!Shot.Keys.IsEmpty()&&Key.U<=Shot.Keys.Last().U))return false;
            Shot.Keys.Add(Key);
        }
        if(Shot.Keys[0].U!=0||Shot.Keys.Last().U!=1)return false;
        Ids.Add(Shot.Id.ToLower());Shots.Add(MoveTemp(Shot));
    }
    return true;
}

void UMRFilmSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);FString Plan;
    FParse::Value(FCommandLine::Get(),TEXT("MRFilmPlan="),Plan);
    if(!FParse::Value(FCommandLine::Get(),TEXT("MRFilmOutput="),Output)||FPaths::IsRelative(Output))
    {Output.Empty();Fail(TEXT("MRFilmOutput must be an absolute new directory"));return;}
    FPaths::NormalizeDirectoryName(Output);
    if(IFileManager::Get().DirectoryExists(*Output)){Output.Empty();Fail(TEXT("Film output already exists; refusing overwrite"));return;}
    if(!ReadPlan(Plan)){Fail(TEXT("Invalid film plan; expected metarescue.film.v1, finite keys and 30 fps"));return;}
    if(!IFileManager::Get().MakeDirectory(*Output,true)){Fail(TEXT("Cannot create film output"));return;}
    FilmCamera=InWorld.SpawnActor<ACameraActor>();
    if(!FilmCamera){Fail(TEXT("Cannot create presentation camera"));return;}
    FilmCamera->SetActorEnableCollision(false);
    UCameraComponent* Component=FilmCamera->GetCameraComponent();
    Component->bConstrainAspectRatio=false;Component->PostProcessBlendWeight=1;
    auto& Post=Component->PostProcessSettings;
    Post.bOverride_VignetteIntensity=true;Post.VignetteIntensity=.24f;
    Post.bOverride_BloomIntensity=true;Post.BloomIntensity=.35f;
    Post.bOverride_MotionBlurAmount=true;Post.MotionBlurAmount=.2f;
    ProcessedHandle=FScreenshotRequest::OnScreenshotRequestProcessed().AddUObject(this,&UMRFilmSubsystem::ScreenshotProcessed);
    Waiting=Shots[0].WaitFrames;Ready=true;
    UE_LOG(LogTemp,Display,TEXT("MR_FILM ready: %d shots, %d fps -> %s"),Shots.Num(),Fps,*Output);
}

void UMRFilmSubsystem::ApplyCamera(const FMRFilmShot& Shot,double U,float DeltaTime)
{
    int32 Index=0;while(Index+1<Shot.Keys.Num()-1&&U>Shot.Keys[Index+1].U)Index++;
    const auto& A=Shot.Keys[Index];const auto& B=Shot.Keys[Index+1];
    double Blend=FMath::Clamp((U-A.U)/(B.U-A.U),0.,1.);Blend=Blend*Blend*(3-2*Blend);
    FVector Eye=FMath::Lerp(A.Eye,B.Eye,Blend),Look=FMath::Lerp(A.Look,B.Look,Blend);
    AMRAgent* Followed=nullptr;
    if(!Shot.Follow.IsEmpty())
    {
        for(TActorIterator<AMRAgent> It(GetWorld());It;++It)if(It->AgentKey()==Shot.Follow){Followed=*It;break;}
        if(!Followed){Fail(TEXT("Follow agent is missing: ")+Shot.Follow);return;}
        const FVector Actual=Followed->GetActorLocation();
        if(!AnchorReady){Anchor=Actual;AnchorReady=true;}
        else Anchor=FMath::Lerp(Anchor,Actual,1.-FMath::Exp(-DeltaTime*8.));
        if(Shot.HeadingSpace){const FRotator Heading(0,Followed->GetActorRotation().Yaw,0);Eye=Heading.RotateVector(Eye);Look=Heading.RotateVector(Look);}
        Eye+=Anchor;Look+=Anchor;
    }
    if(Shot.CollisionTest)
    {
        FHitResult Hit;FCollisionQueryParams Params(SCENE_QUERY_STAT(MRFilmCamera),false,FilmCamera);
        if(Followed)Params.AddIgnoredActor(Followed);
        if(GetWorld()->SweepSingleByChannel(Hit,Look,Eye,FQuat::Identity,ECC_Visibility,FCollisionShape::MakeSphere(18),Params)&&Hit.Distance>180)
            Eye=Hit.Location+(Look-Eye).GetSafeNormal()*24;
    }
    FilmCamera->SetActorLocationAndRotation(Eye,(Look-Eye).Rotation());
    FilmCamera->GetCameraComponent()->SetFieldOfView(FMath::Lerp(A.Fov,B.Fov,Blend));
}

void UMRFilmSubsystem::Tick(float DeltaTime)
{
    Super::Tick(DeltaTime);if(!Ready||Failed)return;
    if(Finishing){Finish();return;}
    AMRWorld* Mission=nullptr;for(TActorIterator<AMRWorld> It(GetWorld());It;++It){Mission=*It;break;}
    const bool Core=Mission&&Mission->bCoreControlled&&Mission->CoreRuntime;
    const FMRFilmShot& Shot=Shots[ShotIndex];
    const bool HeldTail=Core&&GetWorld()->IsPaused();
    // Core pauses between external steps and at the terminal boundary. Only
    // an explicitly delivery-gated closing shot may record a held scene.
    if(HeldTail&&!(Shot.WaitForDelivered>0&&Mission->SavedCount()>=Shot.WaitForDelivered))return;
    float CameraDelta=DeltaTime;
    if(Core)
    {
        // Core owns its variable <=1/60 physics quantum. Sample its real frames
        // near 30 Hz without changing the authoritative clock or any step.
        CadenceClock+=DeltaTime>0?DeltaTime:FApp::GetDeltaTime();if(CadenceClock+1.e-7<1./Fps)return;
        CameraDelta=static_cast<float>(CadenceClock);CadenceClock=FMath::Max(0.,CadenceClock-1./Fps);
    }
    else if(FMath::Abs(DeltaTime-1.f/Fps)>.0001f){Fail(TEXT("Legacy recorder requires -UseFixedTimeStep -FPS=30"));return;}
    auto* PC=GetWorld()->GetFirstPlayerController();if(!PC)return;
    PC->SetViewTarget(FilmCamera);PC->bShowMouseCursor=false;
    if(auto* Hud=PC->GetHUD())Hud->bShowHUD=false;
    ApplyCamera(Shot,static_cast<double>(ShotFrame)/(Shot.Frames-1),CameraDelta);if(Failed)return;
    if(TickNumber++<Warmup)return;
    if(Waiting>0){Waiting--;return;}
    const double MissionTime=Core?Mission->CoreRuntime->Time():GetWorld()->GetTimeSeconds();
    if(Shot.WaitUntil>=0&&MissionTime+1.e-7<Shot.WaitUntil)return;
    if(Shot.WaitForDelivered>0&&(!Mission||Mission->SavedCount()<Shot.WaitForDelivered))return;
    if(Pending){Fail(TEXT("Screenshot was not completed before the next fixed frame"));return;}
    const FString Folder=Output/Shot.Id;
    if(ShotFrame==0&&!IFileManager::Get().MakeDirectory(*Folder,true)){Fail(TEXT("Cannot create shot directory"));return;}
    PendingFile=Folder/FString::Printf(TEXT("frame-%06d.png"),ShotFrame);
    auto Row=MakeShared<FJsonObject>();Row->SetStringField(TEXT("shot"),Shot.Id);Row->SetNumberField(TEXT("frame"),ShotFrame);
    Row->SetNumberField(TEXT("world_time_s"),GetWorld()->GetTimeSeconds());
    Row->SetNumberField(TEXT("capture_time_s"),static_cast<double>(Written)/Fps);
    Row->SetBoolField(TEXT("held_tail"),HeldTail);
    Row->SetArrayField(TEXT("camera_cm"),FilmPoint(FilmCamera->GetActorLocation()));
    Row->SetNumberField(TEXT("fov"),FilmCamera->GetCameraComponent()->FieldOfView);
    Row->SetStringField(TEXT("follow"),Shot.Follow);
    PendingRow=FilmJson(Row)+TEXT("\n");Pending=true;
    FScreenshotRequest::RequestScreenshot(PendingFile,false,false);
}

void UMRFilmSubsystem::ScreenshotProcessed()
{
    if(!Pending||Failed)return;
    if(IFileManager::Get().FileSize(*PendingFile)<=0){Fail(TEXT("Screenshot was not written: ")+PendingFile);return;}
    // Screenshot processing follows Core's post-actor tick: metadata describes
    // the image's physical state, including pickup/handover on this very frame.
    TSharedPtr<FJsonObject> Row;
    if(!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(PendingRow),Row)||!Row){Fail(TEXT("Invalid pending frame record"));return;}
    Row->SetStringField(TEXT("record_phase"),TEXT("screenshot_processed_after_core"));
    for(TActorIterator<AMRWorld> It(GetWorld());It;++It)
    {
        Row->SetNumberField(TEXT("found"),It->FoundCount());Row->SetNumberField(TEXT("delivered"),It->SavedCount());
        Row->SetBoolField(TEXT("core_controlled"),It->bCoreControlled);
        if(It->bCoreControlled&&It->CoreRuntime)Row->SetNumberField(TEXT("core_time_s"),It->CoreRuntime->Time());
        TArray<TSharedPtr<FJsonValue>> Agents;
        for(const auto& Agent:It->Agents)if(Agent)
        {auto J=MakeShared<FJsonObject>();J->SetStringField(TEXT("id"),Agent->AgentKey());J->SetArrayField(TEXT("position_cm"),FilmPoint(Agent->GetActorLocation()));J->SetStringField(TEXT("state"),Agent->State);J->SetBoolField(TEXT("carrying"),Agent->bCarrying);Agents.Add(MakeShared<FJsonValueObject>(J));}
        Row->SetArrayField(TEXT("agents"),Agents);break;
    }
    PendingRow=FilmJson(Row.ToSharedRef())+TEXT("\n");
    if(!FFileHelper::SaveStringToFile(PendingRow,*(Output/TEXT("frames.jsonl")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,&IFileManager::Get(),FILEWRITE_Append))
    {Fail(TEXT("Cannot append frame journal"));return;}
    Pending=false;Written++;ShotFrame++;
    if(ShotFrame==Shots[ShotIndex].Frames)
    {
        UE_LOG(LogTemp,Display,TEXT("MR_FILM shot complete: %s (%d frames)"),*Shots[ShotIndex].Id,ShotFrame);
        ShotIndex++;ShotFrame=0;AnchorReady=false;
        if(ShotIndex==Shots.Num())Finishing=true;else Waiting=Shots[ShotIndex].WaitFrames;
    }
}

void UMRFilmSubsystem::Finish()
{
    auto Result=MakeShared<FJsonObject>();Result->SetStringField(TEXT("format"),TEXT("metarescue.film-capture.v1"));
    Result->SetBoolField(TEXT("complete"),true);Result->SetNumberField(TEXT("frames"),Written);Result->SetNumberField(TEXT("fps"),Fps);
    Result->SetStringField(TEXT("provenance"),TEXT("Native Unreal frame sequence; presentation camera; scenario and controller mode recorded per frame"));
    if(!FFileHelper::SaveStringToFile(FilmJson(Result),*(Output/TEXT("capture.json")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
    {Fail(TEXT("Cannot write completion manifest"));return;}
    Ready=false;UE_LOG(LogTemp,Display,TEXT("MR_FILM complete: %d frames"),Written);
    if(ExitOnFinish)FPlatformMisc::RequestExitWithStatus(false,0);
}

void UMRFilmSubsystem::Deinitialize()
{
    if(ProcessedHandle.IsValid())FScreenshotRequest::OnScreenshotRequestProcessed().Remove(ProcessedHandle);
    Ready=false;Super::Deinitialize();
}
