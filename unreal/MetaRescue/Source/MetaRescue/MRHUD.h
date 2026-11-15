#pragma once
#include "CoreMinimal.h"
#include "GameFramework/HUD.h"
#include "MRHUD.generated.h"
UCLASS()
class METARESCUE_API AMRHUD : public AHUD
{
    GENERATED_BODY()
public: virtual void DrawHUD() override;
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type Reason) override;
private:
    TSharedPtr<class SWidget> MissionInterface;
    TSharedPtr<class FMRMissionOverlay> MissionOverlay;
};
