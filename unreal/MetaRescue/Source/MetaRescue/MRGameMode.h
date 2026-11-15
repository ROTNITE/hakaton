#pragma once
#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "GameFramework/PlayerController.h"
#include "MRGameMode.generated.h"
UCLASS()
class METARESCUE_API AMRPlayerController : public APlayerController
{
    GENERATED_BODY()
public:
    AMRPlayerController();
};
UCLASS()
class METARESCUE_API AMRGameMode : public AGameModeBase
{
    GENERATED_BODY()
public:
    AMRGameMode();
    virtual void BeginPlay() override;
};
