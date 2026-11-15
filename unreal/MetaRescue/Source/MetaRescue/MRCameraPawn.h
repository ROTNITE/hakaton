#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Pawn.h"
#include "MRCameraPawn.generated.h"
class USpringArmComponent;
class UCameraComponent;
class AMRAgent;

UCLASS()
class METARESCUE_API AMRCameraPawn : public APawn
{
    GENERATED_BODY()
public:
    AMRCameraPawn();
    virtual void BeginPlay() override;
    virtual void Tick(float Dt) override;
    virtual void SetupPlayerInputComponent(UInputComponent* Input) override;
    UPROPERTY(VisibleAnywhere) TObjectPtr<USpringArmComponent> Arm;
    UPROPERTY(VisibleAnywhere) TObjectPtr<UCameraComponent> Camera;
    void SetPreset(int32 Index);
    void SetInspectionView(FVector Focus,float Distance,float InYaw,float InPitch);
    AMRAgent* GetObservedAgent() const;
    void FollowAgent(const FString& Id);
    bool bShowInspector = false;
    int32 ObservedAgent = 3;
private:
    float Yaw = 45;
    float Pitch = -42;
    bool bOverview = false;
    float MaximumDistance=50000;
    void Overview();
    void ZoomIn();
    void ZoomOut();
    void Collapse();
    void Pause();
    void Screenshot();
    void BaseView();
    void QuarterView();
    void CollapseView();
    void WaterView();
    void TunnelView();
    void FireView();
    void StreetView();
    void VehicleView();
    void GlassView();
    void FaultView();
    void ToggleInspector();
    void PreviousAgent();
    void NextAgent();
    void ToggleFollow();
    void CycleAgent(int32 Delta);
    bool bFollowing = false;
};
