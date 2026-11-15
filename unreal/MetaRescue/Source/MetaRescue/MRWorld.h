#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "MRAssetAssembly.h"
#include "MREnvironment.h"
#include "MRWorld.generated.h"

class AMRAgent;
class UProceduralMeshComponent;
class UStaticMeshComponent;
class UMaterialInterface;
class UPrimitiveComponent;
class FJsonObject;
class UNiagaraComponent;
class FMRCoreRuntime;

USTRUCT(BlueprintType)
struct FMRSurfaceState
{
    GENERATED_BODY()
    UPROPERTY(BlueprintReadOnly) float MovementCost=1;
    UPROPERTY(BlueprintReadOnly) float WaterDepthMeters=0;
    UPROPERTY(BlueprintReadOnly) float VisibilityQuality=1;
    UPROPERTY(BlueprintReadOnly) bool Blocked=false;
    UPROPERTY(BlueprintReadOnly) int32 Revision=0;
};

struct FMRTarget
{
    int32 Id = 0;
    FVector Position = FVector::ZeroVector;
    bool bDiscovered = false;
    bool bAssigned = false;
    bool bRescued = false;
    double DiscoveredAt = -1;
    double ObservedAt = -1;
    double AvailableAt = 0;
    double Priority=1;
    int32 Observer = -1;
    FVector ReportOrigin = FVector::ZeroVector;
    bool bAvailabilityReported = false;
    int32 ObservationEpoch = 0;
    TObjectPtr<AActor> Visual = nullptr;
    TArray<FVector> Path;
};

struct FMRRestriction
{
    FBox Bounds;
    TSet<FString> AllowedKinds;
};

struct FMRInspection
{
    float Time=0;
    FVector Focus=FVector::ZeroVector;
    FString Name;
    float Distance=3000;
    float Yaw=225,Pitch=-32,SettleSeconds=.6f;
};

UCLASS()
class METARESCUE_API AMRWorld : public AActor
{
    GENERATED_BODY()
public:
    AMRWorld();
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Rescue") bool bRescueQuarter = false;
    UPROPERTY(BlueprintReadOnly,Category="Rescue") bool bCityLayout=false;
    bool bIrregularCity=false;
    bool bDecoratedCity=false;
    bool bCityProps=false;
    UFUNCTION(CallInEditor, BlueprintCallable, Category="Rescue") void BuildScene();
    UFUNCTION(BlueprintCallable, Category="Rescue") void ReleaseCollapse();
    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;
    virtual void EndPlay(const EEndPlayReason::Type Reason) override;
    bool bCoreControlled=false;
    TMap<FString,FMRRestriction> CoreRestrictions;
    bool RestrictionOnRoute(const FVector& Start,const FVector& End,const FString& Kind,double Radius,double HalfHeight,FBox& Blocker) const;
    TSharedPtr<FMRCoreRuntime> CoreRuntime;
    int32 FoundCount() const;
    int32 SavedCount() const;
    int32 ContactCount = 0;
    double ProfileSeconds = 0;
    int32 ProfileFrames = 0;
    float WorstFrameSeconds = 0;
    double MissionStartWall=0,WarmStartWall=0;
    float ModelDeltaMin=MAX_flt,ModelDeltaMax=0;
    int32 GridSize = 25;
    int32 Seed = 2026;
    bool bCollapseReleased = false;
    FVector Base = FVector(1000,1000,0);
    TArray<FMRTarget> Targets;
    UPROPERTY() TArray<TObjectPtr<AMRAgent>> Agents;
    UPROPERTY() TArray<TObjectPtr<USceneComponent>> Generated;
    UPROPERTY() TArray<TObjectPtr<UProceduralMeshComponent>> PhysicsPieces;
    UPROPERTY() TArray<TObjectPtr<UProceduralMeshComponent>> CollapsePieces;
    TArray<FVector> InitialPiecePositions;
    TSharedPtr<FJsonObject> Scenario;
    TSharedPtr<FJsonObject> CityLayout;
    void AppendEvent(const FString& Type, int32 Id = -1);
    void WriteTelemetry();
    float GroundSpeedFactor(const FVector& Position) const;
    bool IsUnsafeGround(const FVector& Position) const;
    bool HasRadio(const FVector& Position) const;
    float WaterDepth(const FVector& Position) const;
    float MovementCost(const FVector& Position) const;
    float SensorRange(const FVector& Position) const;
    int32 PendingReports() const;
    bool bRelayOnline = true;
    bool bFloodActive = false;
    FMRDistrictEnvironment Environment;
    UPROPERTY(EditAnywhere,BlueprintReadWrite,Category="Rescue|Integration") bool bDemoDispatcherEnabled=true;
    UFUNCTION(BlueprintPure,Category="Rescue|Integration") FMRSurfaceState QuerySurfaceMeters(FVector PositionMeters) const;
    UFUNCTION(BlueprintCallable,Category="Rescue|Integration") bool SubmitRouteMeters(const FString& AgentKey,const FString& CommandId,const TArray<FVector>& PointsMeters);
    UFUNCTION(BlueprintCallable,Category="Rescue|Integration") bool HoldAgent(const FString& AgentKey,const FString& CommandId);
    UFUNCTION(BlueprintPure,Category="Rescue|Integration") FString PublicObservationJson() const;
    float VisibilityQuality(const FVector& Position) const;
    void RecordEnvironmentEvent(const FMRDisturbance& Event);
private:
    friend class FMRCoreRuntime;
    bool ReadCoreEventTape();
    void ResetCoreEventEffects();
    int32 ApplyCoreDisturbance(const FMRDisturbance& Event);
    FString CoreEventProfile;
    UPROPERTY() TArray<TObjectPtr<USceneComponent>> CoreEventComponents;
    bool ReadCityLayout(const FString& File);
    bool ValidateCompetitionLayout() const;
    void BuildCompetitionAnnex();
    void SpawnCompetitionUnits();
    void BuildIrregularStreets(const FBox& BaseBox);
    void BuildCityYards();
    void BuildCityHorizon();
    void BuildCityFeature(const TSharedPtr<FJsonObject>& Feature);
    void ApplyCityDaylight();
    void PrepareCityAssetViews();
    void PrepareCityBuildingViews();
    void BuildCity();
    bool bBuildingCity=false;
    int32 CityVegetationRevision=1;
    double CityBuildWallSeconds=0;
    float CityGroundCost(const FVector& Position) const;
    TMap<FIntPoint,TArray<int32>> CitySurfaceIndex;
    void InitializeEnvironment();
    void ApplyDisturbance(const FMRDisturbance& Event);
    void TickHazardVisuals(float Dt);
    void ExportEnvironmentManifest() const;
    UPROPERTY() TArray<TObjectPtr<USceneComponent>> HazardVisuals;
    UPROPERTY() TArray<FBox> StructureFootprints;
    TMap<FIntPoint,float> FloodGroundHeights;
    TSet<FIntPoint> SurfaceCells[3];
    void BuildHazardSurface(const FMRDisturbance& Event,FIntPoint Cell,int32 Layer);
    TMap<FString,int32> EventTargetIndices;
    TArray<FMREventSite> EventSites;
    FString TrafficProbe;
    FString VisualProbe;
    TArray<FMRInspection> EventInspections;
    TSet<int32> InspectedEventKinds;
    bool bProbeRouteReplaced=false;
    void InitializeTrafficProbe();
    void TickTrafficProbe();
    bool bCaptureFrames=false;
    int32 CaptureFrame=0;
    float CaptureClock=0;
    bool bRuntimeReady=false;
    int32 ProfileMsHistogram[1000]={};
    void BuildDistrict();
    void OptimizeDistrictInstances();
    USceneComponent* DistrictAssembly(const FString& Name, const FVector& Position,
        const FRotator& Rotation = FRotator::ZeroRotator, const FVector& Scale = FVector::OneVector,
        bool Collision = true, bool Movable = false, const FString& Module = TEXT(""));
    void Apartment(const FVector& Position, int32 Floors, int32 Variant, int32 Damage);
    USceneComponent* GroundedAssembly(const FString& Name,const FVector& Position,
        const FRotator& Rotation=FRotator::ZeroRotator,const FVector& Scale=FVector::OneVector,
        const FString& Module=TEXT(""),bool Collision=true);
    void GroundedChunk(FRandomStream& Rng,const FVector& Position,const FVector& Size,bool Physics=false);
    void TickDistrict(float Dt);
    TArray<FMRAssemblyPart> DistrictMechanisms;
    TObjectPtr<USceneComponent> ServiceVan = nullptr;
    FVector VanPark;
    float VanWheelTravel=0;
    bool bDustActive = false;
    UPROPERTY() TObjectPtr<UNiagaraComponent> DustEffect;
    UPROPERTY() TObjectPtr<UNiagaraComponent> FireEffect;
    UPROPERTY() TObjectPtr<UNiagaraComponent> LeakEffect;
    UPROPERTY() TArray<TObjectPtr<AMRAgent>> MechanicsProbes;
    bool bMechanicsProbe = false;
    bool bProbeSpawned = false;
    UStaticMeshComponent* DistrictMesh(const FString& Name, const FVector& Position,
        const FRotator& Rotation = FRotator::ZeroRotator, const FVector& Scale = FVector::OneVector, bool Collision = true);
    void DistrictLabel(const FString& Text, const FVector& Position, float Size = 45);
    float SensorClock = 0;
    float TelemetryClock = 0;
    float QuitAfter = 0;
    bool bSmoke = false;
    bool bScreenshotTaken = false;
    bool bStartScreenshotTaken = false;
    bool bPhotoTour = false;
    int32 PhotoStage = 0;
    bool bPhotoPending = false;
    float PhotoRequestedAt = 0;
    float ProbeWarmup = 0;
    TArray<TArray<int32>> Grid;
    UStaticMeshComponent* Shape(const FString& Mesh, const FVector& Position,
        const FVector& Size, const FString& Material, const FRotator& Rotation = FRotator::ZeroRotator, bool Collision = true);
    UProceduralMeshComponent* Chunk(FRandomStream& Rng, const FVector& Position,
        const FVector& Size, bool Physics, bool Collapse = false);
    void Building(FRandomStream& Rng, int32 X, int32 Y);
    void Checkpoint();
    void SpawnAgents();
    void SpawnTargets();
    void SenseAndDispatch(float Dt);
    bool ReadScenario();
    UFUNCTION() void OnRubbleHit(UPrimitiveComponent* HitComponent, AActor* OtherActor,
        UPrimitiveComponent* OtherComponent, FVector NormalImpulse, const FHitResult& Hit);
};
