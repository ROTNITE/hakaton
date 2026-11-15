#include "MRHUD.h"
#include "MRMissionSession.h"
#include "MRMissionInterface.h"
#include "MRMissionOverlay.h"
#include "MRCoreRuntime.h"
#include "MRWorld.h"
#include "MRAgent.h"
#include "MRCameraPawn.h"
#include "Components/BoxComponent.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "EngineUtils.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

void AMRHUD::BeginPlay()
{
    Super::BeginPlay();
    if(auto* Session=UMRMissionSession::Get(GetWorld());Session&&Session->Enabled&&GEngine&&GEngine->GameViewport)
    {MissionInterface=MRBuildMissionInterface(Session);GEngine->GameViewport->AddViewportWidgetContent(MissionInterface.ToSharedRef(),10);}
}

void AMRHUD::EndPlay(const EEndPlayReason::Type Reason)
{
    if(MissionInterface&&GEngine&&GEngine->GameViewport)GEngine->GameViewport->RemoveViewportWidgetContent(MissionInterface.ToSharedRef());
    MissionInterface.Reset();MissionOverlay.Reset();Super::EndPlay(Reason);
}

void AMRHUD::DrawHUD()
{
    Super::DrawHUD();if(!Canvas)return;
    if(auto* Session=UMRMissionSession::Get(GetWorld());Session&&Session->Enabled)
    {if(!MissionOverlay)MissionOverlay=MakeShared<FMRMissionOverlay>(this);MissionOverlay->Draw(Session,Canvas);return;}
    if(auto* Session=UMRMissionSession::Get(GetWorld());Session&&Session->CaptureOverview)
    {
        if(!MissionOverlay)MissionOverlay=MakeShared<FMRMissionOverlay>(this);
        MissionOverlay->Draw(Session,Canvas);
        const auto* Mission=Session->Mission.Get();
        if(!Mission||!Mission->CoreRuntime)return;
        const FLinearColor TextColor(.9f,.95f,.93f,1);
        DrawRect(FLinearColor(.02f,.05f,.045f,.9f),24,24,322,73);
        const TCHAR* Title=FParse::Param(FCommandLine::Get(),TEXT("MRVisualShowcase"))?
            TEXT("RESCUE QUARTER  /  SHOWCASE"):TEXT("RESCUE QUARTER");
        DrawText(FString::Printf(TEXT("%s  |  %.1f s"),Title,Mission->CoreRuntime->Time()),TextColor,39,36,GEngine->GetMediumFont(),.9f);
        DrawText(FString::Printf(TEXT("%d FOUND  /  %d AT BASE"),Mission->FoundCount(),Mission->SavedCount()),TextColor,39,69,GEngine->GetSmallFont(),.9f);
        return;
    }
    AMRWorld* Mission=nullptr;for(TActorIterator<AMRWorld> It(GetWorld());It;++It){Mission=*It;break;}
    const FLinearColor White(.88f,.94f,.92f,1),Muted(.5f,.65f,.61f,1),Lime(.77f,.94f,.36f,1);
    DrawRect(FLinearColor(.018f,.04f,.035f,.88f),24,24,325,246);
    DrawRect(Lime,24,24,3,246);
    DrawText(TEXT("META / RESCUE"),White,43,39,GEngine->GetLargeFont(),.78f);
    DrawText(Mission&&Mission->bRescueQuarter?TEXT("RESCUE QUARTER  /  PHYSICAL DEMO"):TEXT("PHYSICS ENVIRONMENT  /  UE 5.8"),Muted,44,72,GEngine->GetSmallFont(),.9f);
    if(Mission)
    {
        DrawText(FString::Printf(TEXT("%02d FOUND     %02d DELIVERED"),Mission->FoundCount(),Mission->SavedCount()),Lime,44,103,GEngine->GetMediumFont(),1.05f);
        DrawText(FString::Printf(TEXT("TIME %.1fs     CONTACTS %d"),Mission->CoreRuntime?Mission->CoreRuntime->Time():GetWorld()->GetTimeSeconds(),Mission->ContactCount),White,44,138,GEngine->GetSmallFont(),1.f);
        DrawText(Mission->bRescueQuarter?FString::Printf(TEXT("ENV %s | REVISION %d"),*Mission->Environment.Mode.ToUpper(),Mission->Environment.Revision):
            Mission->bCollapseReleased?TEXT("COLLAPSE RELEASED / CHAOS ACTIVE"):TEXT("DETACHED SLABS / RELEASE AT 18s"),Muted,44,166,GEngine->GetSmallFont(),.9f);
        DrawText(Mission->bDemoDispatcherEnabled?TEXT("DEMO POLICY / CONTROLLER NOT CONNECTED"):TEXT("EXTERNAL ROUTES / DEMO DISPATCH DISABLED"),Muted,44,196,GEngine->GetSmallFont(),.75f);
        if(Mission->bRescueQuarter)
        {
            DrawText(FString::Printf(TEXT("RELAY %s | QUEUED REPORTS %d"),Mission->bRelayOnline?TEXT("ONLINE"):TEXT("OFFLINE"),Mission->PendingReports()),White,44,219,GEngine->GetSmallFont(),.85f);
            DrawText(FString::Printf(TEXT("ROAD WATER %.0f cm | DUST %s"),Mission->WaterDepth(FVector(14500,12800,0)),Mission->SensorRange(FVector(7800,5950,0))<3000?TEXT("ACTIVE"):TEXT("CLEAR")),Muted,44,243,GEngine->GetSmallFont(),.85f);
        }
    }
    DrawRect(FLinearColor(.018f,.04f,.035f,.84f),24,Canvas->ClipY-57,Canvas->ClipX-48,33);
    DrawText(Mission&&Mission->bRescueQuarter?
        TEXT("1-8 sites | I inspector | Arrows select | R follow | RMB orbit | Wheel zoom | WASD pan | F collapse | SPACE pause | F9 capture"):
        TEXT("RMB orbit  |  Wheel zoom  |  WASD pan  |  TAB overview  |  F collapse  |  SPACE pause  |  F9 capture"),White,40,Canvas->ClipY-48,GEngine->GetSmallFont(),.86f);
    AMRCameraPawn* CameraPawn=nullptr;for(TActorIterator<AMRCameraPawn> It(GetWorld());It;++It){CameraPawn=*It;break;}
    if(Mission&&CameraPawn&&CameraPawn->bShowInspector)
    {
        const float X=Canvas->ClipX-335;
        DrawRect(FLinearColor(.018f,.04f,.035f,.93f),X,24,311,330);
        DrawText(TEXT("AGENT INSPECTOR"),Lime,X+16,38,GEngine->GetMediumFont(),.85f);
        int32 Index=0;
        for(AMRAgent* Agent:Mission->Agents)
        {
            const bool Selected=Index==CameraPawn->ObservedAgent;
            const FString Label=FString::Printf(TEXT("%s %s %d  %s"),Selected?TEXT(">"):TEXT(" "),
                Agent->bAerial?TEXT("DRONE"):TEXT("ROVER"),Agent->AgentId+1,Agent->bRouteBlocked?TEXT("BLOCKED"):*Agent->State);
            DrawText(Label,Selected?Lime:White,X+14,72+Index*24,GEngine->GetSmallFont(),.9f);Index++;
        }
        if(AMRAgent* Agent=CameraPawn->GetObservedAgent())
        {
            DrawText(FString::Printf(TEXT("ENERGY %.1f Wh | MASS %.0f kg"),Agent->Energy,Agent->Body->GetMass()),White,X+16,252,GEngine->GetSmallFont(),.9f);
            DrawText(FString::Printf(TEXT("SPEED %.2f m/s | SUPPORT %d"),Agent->Body->GetPhysicsLinearVelocity().Size()/100,Agent->GroundContacts),White,X+16,278,GEngine->GetSmallFont(),.9f);
            DrawText(FString::Printf(TEXT("MEAN GAME FPS %.1f"),Mission->ProfileFrames/FMath::Max(.001,Mission->ProfileSeconds)),Muted,X+16,308,GEngine->GetSmallFont(),.9f);
        }
    }
    if(UGameplayStatics::IsGamePaused(GetWorld()))DrawText(TEXT("PAUSED"),Lime,Canvas->ClipX*.5f-60,35,GEngine->GetLargeFont(),1.f);
}
