#pragma once
#include "CoreMinimal.h"
#include "MRHydrology.h"

class AMRWorld;
class UProceduralMeshComponent;
class UMaterialInstanceDynamic;
class FJsonObject;

struct FMRWaterSample
{
    bool InDomain=false;
    double DepthCm=0,StageCm=0,GroundCm=0;
    FVector CurrentCmPerSecond=FVector::ZeroVector;
};

// Authoritative 5m finite-volume field. Visual triangles, road safety,
// observations and buoyancy all sample this field in the same units.
class FMRUrbanWater
{
public:
    explicit FMRUrbanWater(AMRWorld* InWorld):World(InWorld){}
    static bool Validate(const TSharedPtr<FJsonObject>& Data,int32 GridSize);
    bool Build();
    void Reset();
    bool AdvanceTo(double ModelSeconds);
    FMRWaterSample Sample(FVector Position) const;
    bool HasHistory(FIntPoint SurfaceCell) const;
    void TerrainChanged(FBox Bounds);
    TSharedPtr<FJsonObject> PrivateSnapshot() const;
private:
    struct FTile {int32 X=0,Y=0;TWeakObjectPtr<UProceduralMeshComponent> Mesh;};
    struct FFootprint
    {
        FVector2D Center,Half;
        double Cos=1,Sin=0,Top=0;
        FBox Bounds;
        bool Contains(FVector P) const;
        bool Intersects(FVector A,FVector B) const;
    };
    AMRWorld* World;
    FMRHydrology Hydro;
    FVector Origin=FVector::ZeroVector;
    FBox Basin=FBox(ForceInit);
    double CellCm=500,LastTime=0,InitialStageM=.05,StormStageM=2.8,RiseSeconds=70;
    int32 Columns=0,Rows=0;
    double DrainCapacity=0;
    double TailwaterStageM=0;
    TSet<FString> OutletEdges;
    bool ReadBlueprint(const TSharedPtr<FJsonObject>& Data,int32 GridSize);
    TArray<int32> Sources;
    TArray<int32> Outlets;
    TArray<FFootprint> Footprints;
    TMap<FIntPoint,TArray<int32>> FootprintBins;
    TArray<FTile> Tiles;
    TArray<double> VertexBeds,InitialVertexBeds;
    TWeakObjectPtr<UMaterialInstanceDynamic> WaterMaterial;
    TSet<FIntPoint> History;
    double ForcingStage(double At) const;
    FVector Center(int32 X,int32 Y) const;
    int32 At(FVector P) const;
    double GroundCm(FVector P) const;
    double VertexStageCm(int32 X,int32 Y) const;
    FVector VertexCurrentCm(int32 X,int32 Y) const;
    TOptional<double> RenderedHeightCm(FVector Position) const;
    void Render();
};
