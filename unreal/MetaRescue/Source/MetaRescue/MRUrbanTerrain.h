#pragma once
#include "CoreMinimal.h"

class AMRWorld;
class UProceduralMeshComponent;
class UMaterialInterface;
struct FMRDisturbance;

struct FMRRoadCavity
{
    FString Id;
    FVector Center=FVector::ZeroVector,Along=FVector::ForwardVector;
    double AlongCm=500,AcrossCm=600,DepthCm=200,Phase=0;
    double DropCm(FVector P) const;
    FBox Bounds() const;
};

// Geometry owns the physical support. Road markings and the environment's
// conservative danger cells do not provide invisible flat collision planes.
class FMRUrbanTerrain
{
public:
    explicit FMRUrbanTerrain(AMRWorld* InWorld):World(InWorld){}
    void Build();
    void RoadPatch(FVector Start,FVector End,double Width,double Offset,UMaterialInterface* Material);
    void Damage(const FMRDisturbance& Event);
    void Reset();
    double DropCm(FVector Position) const;
private:
    struct FPatch
    {
        TWeakObjectPtr<UProceduralMeshComponent> Mesh;
        TArray<FVector> XY;
        TArray<int32> Triangles;
        FBox Bounds=FBox(ForceInit);
        double Offset=0;
        bool Soil=false,Collision=false;
    };
    struct FOverlay
    {
        TWeakObjectPtr<UProceduralMeshComponent> Mesh;
        int32 Section=0;
        TArray<FVector> Positions,Normals;
        TArray<FVector2D> UV;
        TArray<FLinearColor> Colors;
        TArray<int32> Triangles;
        bool Collision=false;
    };
    AMRWorld* World;
    TArray<FPatch> Patches;
    TArray<FOverlay> Overlays;
    TArray<FMRRoadCavity> Cavities;
    TMap<FIntPoint,TArray<FBox>> Foundations;
    void AddFoundation(FBox Bounds);
    void Update(FPatch& Patch);
    void Update(FOverlay& Overlay);
    void CutOverlays(const FMRRoadCavity& Cavity);
    void Grid(FVector Origin,FVector X,FVector Y,int32 NX,int32 NY,double Offset,UMaterialInterface* Material,bool Soil);
};
