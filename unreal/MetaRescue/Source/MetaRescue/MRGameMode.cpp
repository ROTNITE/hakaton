#include "MRGameMode.h"
#include "MRWorld.h"
#include "MRCameraPawn.h"
#include "MRHUD.h"
#include "EngineUtils.h"
#include "Engine/World.h"
AMRPlayerController::AMRPlayerController(){bShouldPerformFullTickWhenPaused=true;PrimaryActorTick.bTickEvenWhenPaused=true;}
AMRGameMode::AMRGameMode(){DefaultPawnClass=AMRCameraPawn::StaticClass();HUDClass=AMRHUD::StaticClass();PlayerControllerClass=AMRPlayerController::StaticClass();}
void AMRGameMode::BeginPlay()
{
    Super::BeginPlay();
    for(TActorIterator<AMRWorld> It(GetWorld());It;++It)return;
    GetWorld()->SpawnActor<AMRWorld>();
}
