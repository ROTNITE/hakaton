#include "MRCameraPawn.h"
#include "MRWorld.h"
#include "MRMissionSession.h"
#include "MRCoreValues.h"
#include "MRCoreJson.h"
#include "MRAgent.h"
#include "Camera/CameraComponent.h"
#include "GameFramework/SpringArmComponent.h"
#include "GameFramework/PlayerController.h"
#include "Components/InputComponent.h"
#include "Kismet/GameplayStatics.h"
#include "EngineUtils.h"
#include "Engine/World.h"
#include "UnrealClient.h"
#include "Misc/Paths.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

AMRCameraPawn::AMRCameraPawn()
{
    PrimaryActorTick.bCanEverTick=true;PrimaryActorTick.bTickEvenWhenPaused=true;
    SetRootComponent(CreateDefaultSubobject<USceneComponent>(TEXT("CameraFocus")));
    Arm=CreateDefaultSubobject<USpringArmComponent>(TEXT("OrbitArm"));Arm->SetupAttachment(GetRootComponent());
    Arm->PrimaryComponentTick.bTickEvenWhenPaused=true;
    Arm->TargetArmLength=6500;Arm->bDoCollisionTest=false;Arm->SetRelativeRotation(FRotator(Pitch,Yaw,0));
    Camera=CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));Camera->SetupAttachment(Arm);
    Camera->PrimaryComponentTick.bTickEvenWhenPaused=true;
    Camera->FieldOfView=48;
}

void AMRCameraPawn::BeginPlay()
{
    Super::BeginPlay();SetActorLocation(FVector(1500,2000,0));
    // The operator can move the camera and change knowledge layers while the
    // physical world is paused. Let the renderer refresh temporal histories;
    // this flag does not unpause any simulation tick or advance episode time.
    GetWorld()->bIsCameraMoveableWhenPaused=true;
    for(TActorIterator<AMRWorld> It(GetWorld());It;++It)if(It->bRescueQuarter)
    {
        if(It->bCityLayout)
        {MaximumDistance=It->GridSize*3000;SetPreset(1);}
        else {SetActorLocation(FVector(2600,2500,120));Arm->TargetArmLength=10500;}
        break;
    }
    float DiagnosticEV=0;
    if(FParse::Value(FCommandLine::Get(),TEXT("MRDiagnosticEV="),DiagnosticEV))
    {
        if(FMath::IsFinite(DiagnosticEV)&&DiagnosticEV>=-4&&DiagnosticEV<=16)
        {
            // Explicit renderer diagnosis only: keep the authored map unchanged
            // while comparing the exact same interior at known exposure values.
            auto& Post=Camera->PostProcessSettings;
            Post.bOverride_AutoExposureMethod=true;Post.AutoExposureMethod=AEM_Histogram;
            Post.bOverride_AutoExposureMinBrightness=true;Post.AutoExposureMinBrightness=DiagnosticEV;
            Post.bOverride_AutoExposureMaxBrightness=true;Post.AutoExposureMaxBrightness=DiagnosticEV;
            Post.bOverride_AutoExposureBias=true;Post.AutoExposureBias=0;
            Camera->PostProcessBlendWeight=1;
            UE_LOG(LogTemp,Display,TEXT("MR_RENDER_DIAGNOSTIC FixedEV100=%.2f"),DiagnosticEV);
        }
        else UE_LOG(LogTemp,Error,TEXT("MRDiagnosticEV must be finite and in [-4,16]"));
    }
    if(auto* PC=Cast<APlayerController>(GetController()))
    {PC->bShowMouseCursor=true;PC->SetInputMode(FInputModeGameAndUI());}
}

void AMRCameraPawn::SetupPlayerInputComponent(UInputComponent* Input)
{
    Super::SetupPlayerInputComponent(Input);
    Input->BindKey(EKeys::Tab,IE_Pressed,this,&AMRCameraPawn::Overview).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::MouseScrollUp,IE_Pressed,this,&AMRCameraPawn::ZoomIn).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::MouseScrollDown,IE_Pressed,this,&AMRCameraPawn::ZoomOut).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::F,IE_Pressed,this,&AMRCameraPawn::Collapse);
    Input->BindKey(EKeys::SpaceBar,IE_Pressed,this,&AMRCameraPawn::Pause).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::F9,IE_Pressed,this,&AMRCameraPawn::Screenshot).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::One,IE_Pressed,this,&AMRCameraPawn::BaseView).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::Two,IE_Pressed,this,&AMRCameraPawn::QuarterView).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::Three,IE_Pressed,this,&AMRCameraPawn::CollapseView).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::Four,IE_Pressed,this,&AMRCameraPawn::WaterView).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::Five,IE_Pressed,this,&AMRCameraPawn::TunnelView).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::Six,IE_Pressed,this,&AMRCameraPawn::FireView).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::Seven,IE_Pressed,this,&AMRCameraPawn::StreetView).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::Eight,IE_Pressed,this,&AMRCameraPawn::VehicleView).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::Nine,IE_Pressed,this,&AMRCameraPawn::GlassView).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::Zero,IE_Pressed,this,&AMRCameraPawn::FaultView).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::I,IE_Pressed,this,&AMRCameraPawn::ToggleInspector).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::Left,IE_Pressed,this,&AMRCameraPawn::PreviousAgent).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::Right,IE_Pressed,this,&AMRCameraPawn::NextAgent).bExecuteWhenPaused=true;
    Input->BindKey(EKeys::R,IE_Pressed,this,&AMRCameraPawn::ToggleFollow).bExecuteWhenPaused=true;
}

void AMRCameraPawn::ZoomIn(){if(auto* Session=UMRMissionSession::Get(GetWorld());Session&&Session->Enabled&&Session->SetupOpen)return;Arm->TargetArmLength=FMath::Max(900.f,Arm->TargetArmLength*.85f);}
void AMRCameraPawn::ZoomOut(){if(auto* Session=UMRMissionSession::Get(GetWorld());Session&&Session->Enabled&&Session->SetupOpen)return;Arm->TargetArmLength=FMath::Min(MaximumDistance,Arm->TargetArmLength/ .85f);}
void AMRCameraPawn::Overview()
{
    bFollowing=false;
    bOverview=!bOverview;
    for(TActorIterator<AMRWorld> It(GetWorld());It;++It)
    {
        if(It->bRescueQuarter)
        {
            if(It->bCityLayout)
            {SetPreset(bOverview?1:0);break;}
            SetActorLocation(bOverview?FVector(7200,7200,0):FVector(2600,2500,120));
            Arm->TargetArmLength=bOverview?26500:10500;break;
        }
        SetActorLocation(bOverview?FVector((It->GridSize-1)*500,(It->GridSize-1)*500,0):FVector(1500,2000,0));
        Arm->TargetArmLength=bOverview?It->GridSize*1300:6500;break;
    }
}
void AMRCameraPawn::Collapse()
{
    for(TActorIterator<AMRWorld> It(GetWorld());It;++It)if(!It->bCoreControlled)It->ReleaseCollapse();
}
void AMRCameraPawn::Pause()
{
    if(auto* Session=UMRMissionSession::Get(GetWorld());Session&&Session->Enabled)
    {if(Session->Stage==TEXT("running"))Session->Pause();else if(Session->Stage==TEXT("paused"))Session->Run();return;}
    for(TActorIterator<AMRWorld> It(GetWorld());It;++It)if(It->bCoreControlled)return;
    UGameplayStatics::SetGamePaused(GetWorld(),!UGameplayStatics::IsGamePaused(GetWorld()));
}
void AMRCameraPawn::Screenshot(){FScreenshotRequest::RequestScreenshot(FPaths::ProjectSavedDir()/TEXT("Screenshots/manual.png"),true,true);}
void AMRCameraPawn::BaseView(){SetPreset(0);}
void AMRCameraPawn::QuarterView(){SetPreset(1);}
void AMRCameraPawn::CollapseView(){SetPreset(2);}
void AMRCameraPawn::WaterView(){SetPreset(3);}
void AMRCameraPawn::TunnelView(){SetPreset(4);}
void AMRCameraPawn::FireView(){SetPreset(5);}
void AMRCameraPawn::StreetView(){SetPreset(6);}
void AMRCameraPawn::VehicleView(){SetPreset(7);}
void AMRCameraPawn::GlassView(){SetInspectionView(FVector(1850,1730,180),1200,90,-8);}
void AMRCameraPawn::FaultView(){SetInspectionView(FVector(7800,14500,-50),2400,-90,-48);}
void AMRCameraPawn::SetInspectionView(FVector Focus,float Distance,float InYaw,float InPitch)
{
    bFollowing=false;bOverview=false;Yaw=InYaw;Pitch=InPitch;
    SetActorLocation(Focus);Arm->TargetArmLength=Distance;Arm->SetRelativeRotation(FRotator(Pitch,Yaw,0));
}
void AMRCameraPawn::SetPreset(int32 Index)
{
    for(TActorIterator<AMRWorld> It(GetWorld());It;++It)if(It->bCityLayout)
    {
        const float Size=It->GridSize*1000.f;FVector Focus=It->Base;float Distance=6000;
        if(Index==1){Focus=FVector(Size/2,Size/2,0);Distance=Size*2.12f;}
        else if(Index==2){Focus=FVector(Size-3500,Size-3500,400);Distance=6500;}
        else if(Index>=3&&Index<7){Focus=FVector(Size*(Index%2?.35f:.7f),Size*(Index<5?.35f:.7f),150);Distance=8500;}
        SetInspectionView(Focus,Distance,Index==1?0:Index==0?150:45,Index==1?-80:-38);
        bOverview=Index==1;
        if(Index==7)for(int32 I=0;I<It->Agents.Num();I++)if(!It->Agents[I]->bAerial)
        {ObservedAgent=I;bFollowing=true;bShowInspector=true;SetActorLocation(It->Agents[I]->GetActorLocation());Arm->TargetArmLength=1900;break;}
        return;
    }
    const FVector Locations[]={FVector(-1100,1400,80),FVector(6500,6500,0),FVector(7800,5950,80),FVector(13600,13000,100),FVector(12400,3050,100),FVector(10900,7950,100),FVector(2450,2450,400),FVector(-750,200,80)};
    const float Distances[]={4200,22000,5900,6500,5000,2900,3500,1500};
    bFollowing=false;Index=FMath::Clamp(Index,0,7);SetActorLocation(Locations[Index]);Arm->TargetArmLength=Distances[Index];
    Yaw=Index==0?160:45;Pitch=Index==1?-50:-38;Arm->SetRelativeRotation(FRotator(Pitch,Yaw,0));bOverview=Index==1;
    if(Index==5){Yaw=225;Pitch=-48;Arm->SetRelativeRotation(FRotator(Pitch,Yaw,0));}
    if(Index==7)
    {
        ObservedAgent=3;bFollowing=true;bShowInspector=true;
        if(auto* Agent=GetObservedAgent())SetActorLocation(Agent->GetActorLocation());
    }
}
void AMRCameraPawn::ToggleInspector(){bShowInspector=!bShowInspector;}
void AMRCameraPawn::PreviousAgent(){CycleAgent(-1);}
void AMRCameraPawn::NextAgent(){CycleAgent(1);}
void AMRCameraPawn::CycleAgent(int32 Delta)
{
    for(TActorIterator<AMRWorld> It(GetWorld());It;++It)if(It->Agents.Num()>0)
    {ObservedAgent=(ObservedAgent+Delta+It->Agents.Num())%It->Agents.Num();if(auto* Session=UMRMissionSession::Get(GetWorld());Session&&Session->Enabled)Session->SelectedAgent=It->Agents[ObservedAgent]->AgentKey();break;}
    bShowInspector=true;
}
void AMRCameraPawn::ToggleFollow(){bFollowing=!bFollowing;bShowInspector=true;if(bFollowing)Arm->TargetArmLength=1900;}
void AMRCameraPawn::FollowAgent(const FString& Id)
{
    for(TActorIterator<AMRWorld> It(GetWorld());It;++It)for(int32 I=0;I<It->Agents.Num();I++)if(It->Agents[I]->AgentKey()==Id&&It->Agents[I]->IsSpatial())
    {
        ObservedAgent=I;bFollowing=true;bOverview=false;Arm->TargetArmLength=1900;
        auto* Session=UMRMissionSession::Get(GetWorld());
        if(Session&&Session->Enabled&&!Session->ObserverView)
        {if(auto O=Session->Observation())for(const auto& Value:O->GetArrayField(TEXT("agents")))if(MRCoreValues::Text(Value->AsObject(),TEXT("id"))==Id)
            {FVector P;if(MRCoreJson::Point(MRCoreValues::Field(Value->AsObject(),TEXT("position")),P))SetActorLocation(P*100.);}}
        else SetActorLocation(It->Agents[I]->GetActorLocation());
        return;
    }
}
AMRAgent* AMRCameraPawn::GetObservedAgent() const
{
    for(TActorIterator<AMRWorld> It(GetWorld());It;++It)
        return It->Agents.IsValidIndex(ObservedAgent)?It->Agents[ObservedAgent].Get():nullptr;
    return nullptr;
}

void AMRCameraPawn::Tick(float Dt)
{
    Super::Tick(Dt);auto* PC=Cast<APlayerController>(GetController());if(!PC)return;
    if(auto* Session=UMRMissionSession::Get(GetWorld());Session&&Session->Enabled&&Session->SetupOpen)return;
    auto* DisplaySession=UMRMissionSession::Get(GetWorld());const bool KnowledgeView=DisplaySession&&DisplaySession->Enabled&&!DisplaySession->ObserverView;
    Arm->bDoCollisionTest=bFollowing&&!KnowledgeView;
    if(bFollowing)if(AMRAgent* Agent=GetObservedAgent())
    {
        if(KnowledgeView)
        {if(auto O=DisplaySession->Observation())for(const auto& Value:O->GetArrayField(TEXT("agents")))if(MRCoreValues::Text(Value->AsObject(),TEXT("id"))==Agent->AgentKey())
            {FVector P;if(MRCoreJson::Point(MRCoreValues::Field(Value->AsObject(),TEXT("position")),P))SetActorLocation(FMath::VInterpTo(GetActorLocation(),P*100.,Dt,4));}}
        else SetActorLocation(FMath::VInterpTo(GetActorLocation(),Agent->GetActorLocation(),Dt,4));
    }
    if(PC->IsInputKeyDown(EKeys::RightMouseButton))
    {
        float DX=0,DY=0;PC->GetInputMouseDelta(DX,DY);Yaw+=DX*.25f;Pitch=FMath::Clamp(Pitch-DY*.2f,-85.f,-12.f);
        Arm->SetRelativeRotation(FRotator(Pitch,Yaw,0));
    }
    FVector Movement=FVector::ZeroVector;
    FVector Forward=Camera->GetForwardVector();Forward.Z=0;Forward.Normalize();
    const FVector Right=Camera->GetRightVector();
    if(PC->IsInputKeyDown(EKeys::W))Movement+=Forward;
    if(PC->IsInputKeyDown(EKeys::S))Movement-=Forward;
    if(PC->IsInputKeyDown(EKeys::D))Movement+=Right;
    if(PC->IsInputKeyDown(EKeys::A))Movement-=Right;
    if(!Movement.IsNearlyZero())bFollowing=false;
    AddActorWorldOffset(Movement*Dt*Arm->TargetArmLength*.4f);
}
