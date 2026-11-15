#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "MRAssetAssembly.h"
#include "MRAgent.generated.h"
class UBoxComponent;
class UStaticMeshComponent;
class UPrimitiveComponent;
class UNiagaraComponent;
class AMRWorld;

UCLASS()
class METARESCUE_API AMRAgent : public AActor
{
    GENERATED_BODY()
public:
    AMRAgent();
    void Initialize(AMRWorld* InWorld, int32 InId, bool Aerial, const TArray<FVector>& InitialPath);
    void InitializeCompetition(AMRWorld* InWorld,int32 InId,const FString& Kind,const FString& Site,const FBox& Limits);
    virtual void Tick(float Dt) override;
    // Flush real movement through the same sampling instant as a pose read.
    // Calling twice without intervening physics is deliberately a no-op.
    void AccountExecutedMovement();
    UFUNCTION(BlueprintCallable, Category="Rescue") void SetWaypoints(const TArray<FVector>& Waypoints);
    bool IsIdle() const { return State == "idle"; }
    void StartRescue(int32 TargetIndex);
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly) TObjectPtr<UBoxComponent> Body;
    UPROPERTY() TObjectPtr<AMRWorld> Mission;
    UPROPERTY() TArray<TObjectPtr<UStaticMeshComponent>> Parts;
    bool bAerial = false;
    int32 AgentId = 0;
    FString PublicId;
    FString Category,InfrastructureSite;
    FBox MediumLimits=FBox(ForceInit);
    FString Kind() const {return Category.IsEmpty()?(bAerial?TEXT("aerial"):TEXT("ground")):Category;}
    bool IsSpatial() const {return Category!=TEXT("digital")&&Category!=TEXT("operator");}
    bool CanMove() const {return Category.IsEmpty()||MediumLimits.IsValid;}
    bool CanCarry() const {return Category.IsEmpty()&&!bAerial;}
    bool CanSense() const {return IsSpatial();}
    bool MediumPointAllowed(const FVector& Position) const;
    int32 TargetIndex = -1;
    FString State = "idle";
    double Energy=220, BatteryCapacityWh=220, EnergyReserveWh=0;
    double ConsumedWh=0, MotionWh=0, StandbyWh=0, SensorWh=0, ServiceWh=0, ChargedWh=0;
    bool bUnlimitedEnergy=false;
    bool bFaulted=false;
    float SpeedFactor=1, SensorFactor=1;
    FString FailureReason;
    bool IsOperational() const {return !bFaulted&&Energy>0;}
    float DistanceTravelled = 0;
    float MaxSpeed = 620;
    FVector Dock;
    int32 GroundContacts = 0;
    bool bRouteBlocked = false;
    float RotorRPM = 0;
    float RampDeployment = 0;
    FString CommandId;
    FString StopReason;
    FString StopObstacle;
    // Last obstacle actually intersected by this agent's safety sensor, in cm.
    FBox SensedBlocker=FBox(ForceInit);
    bool bExternalHold=false;
    float WaitingSince=-1;
    int32 AgentContacts=0;
    bool bCarrying=false;
    void ResetTestPose(FVector Position,FRotator Rotation);
    float SafetyRadius() const { return bAerial?165.f:145.f+80.f*RampDeployment; }
    FString AgentKey() const { return PublicId.IsEmpty()?FString::Printf(TEXT("%s_%d"),bAerial?TEXT("aerial"):TEXT("ground"),AgentId):PublicId; }
    bool AcceptRoute(const FString& Id,const TArray<FVector>& PointsCm,bool PreciseStop=false);
    bool Hold(const FString& Id);
    bool IsHoldingStable() const;
    void ResetForEpisode(const FTransform& Pose,bool UnlimitedEnergy);
    bool BeginPickup(int32 Index,const FString& Id);
    bool BeginHandover(const FString& Id);
    void AccountPoweredTime(double Dt);
    bool ChargeDocked(const FVector& Position,double RadiusCm) const;
    bool BeginCharge(const FString& Id);
    bool IsCharging() const {return State==TEXT("charging")||State==TEXT("charge_wait");}
    double ReceiveCharge(double AvailableWh);
    void EndCharge();
    int32 StopAndRelease(const FString& Reason);
    bool RouteFinished() const {return PathIndex>=Path.Num();}
    float RemainingServiceSeconds() const {return State==TEXT("loading")||State==TEXT("unloading")?FMath::Max(0.f,ServiceRemaining):0.f;}
    void ForgetCompletedCoreCommand(const FString& Id);
    int32 PendingCommandDigestCount() const {return AcceptedCommands.Num();}
    FVector IntendedVelocity=FVector::ZeroVector;
    FVector PlannedVelocity() const;
    FVector ActiveWaypoint() const {return Path.IsValidIndex(PathIndex)?Path[PathIndex]:GetActorLocation();}
    TArray<FVector> RemainingRouteForInterface() const
    {TArray<FVector> Result;if(Path.IsValidIndex(PathIndex))Result.Append(Path.GetData()+PathIndex,Path.Num()-PathIndex);return Result;}
private:
    // Only a digest is retained. The Core server owns exact-body HTTP replay.
    TMap<FString,FString> AcceptedCommands;
    UPROPERTY() TObjectPtr<UNiagaraComponent> SurfaceSpray;
    TArray<FVector> Path;
    int32 PathIndex = 0;
    float ServiceRemaining = 0;
    float ServiceElapsed = 0;
    float ServiceHeading = 0;
    FVector PickupStart;
    FQuat PickupRotation;
    float FlightAltitude = 2000;
    float ObstructionTime = 0;
    float DepartAt = 0;
    // Crossing priority uses a fixed pose for this route, never a changing tick
    // order or the speed of an already yielding vehicle.
    FVector RoutePriorityOrigin=FVector::ZeroVector;
    bool bReverseInitialLeg=false;
    bool bPreciseFinalStop=false;
    FVector Previous;
    TArray<FMRAssemblyPart> Mechanisms;
    void AnimateMechanisms(float Dt);
    UStaticMeshComponent* Part(const FString& Mesh, FVector Position, FVector Size,
        const FString& Material, FRotator Rotation = FRotator::ZeroRotator);
    void Arrived();
    void Spend(double Wh,double& Category);
    void InitializeDistrictVisual();
    void DriveDistrictGround(const FVector& Desired);
    bool IsDockEntryLeg() const;
    void DriveCompetitionMedium(float Dt);
    FVector SafeVelocity(const FVector& Desired,float Dt);
    UFUNCTION() void OnAgentHit(UPrimitiveComponent* HitComponent,AActor* OtherActor,UPrimitiveComponent* OtherComponent,FVector Impulse,const FHitResult& Hit);
};
