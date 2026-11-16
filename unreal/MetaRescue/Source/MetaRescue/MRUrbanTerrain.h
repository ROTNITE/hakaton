#pragma once
#include "CoreMinimal.h"
#include "MRGradedTerrain.h"

class AMRWorld;
class UProceduralMeshComponent;
class UMaterialInterface;
struct FMRDisturbance;

struct FMRRoadCavity
{
    FString Id;
    FString RoadId;
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
    void BaseApron(FBox Bounds,UMaterialInterface* Material);
    bool Damage(const FMRDisturbance& Event);
    void Reset();
    double DropCm(FVector Position) const;
    double InitialHeight(FVector Position) const {return Topography.Height(Position);}
    double GroundHeight(FVector Position) const;
private:
    friend class AMRWorld;
    struct FPatch
    {
        TWeakObjectPtr<UProceduralMeshComponent> Mesh;
        TArray<FVector> XY;
        TArray<int32> Triangles;
        FBox Bounds=FBox(ForceInit);
        double Offset=0,EdgeFeatherCm=0;
        FVector GridOrigin=FVector::ZeroVector,GridX=FVector::ZeroVector,GridY=FVector::ZeroVector;
        int32 InitialNX=0,InitialNY=0,NX=0,NY=0;
        bool Refined=false;
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
    FMRGradedTerrain Topography;
    TArray<FPatch> Patches;
    TMap<FIntPoint,TArray<int32>> PatchBins;
    TArray<FOverlay> Overlays;
    TArray<FMRRoadCavity> Cavities;
    TMap<FIntPoint,TArray<FBox>> Foundations;
    void AddFoundation(FBox Bounds);
    double HeightAt(const FPatch& Patch,FVector Position) const;
    void Update(FPatch& Patch);
    void Tessellate(FPatch& Patch,int32 NX,int32 NY);
    void Update(FOverlay& Overlay);
    void CutOverlays(const FMRRoadCavity& Cavity);
    void Grid(FVector Origin,FVector X,FVector Y,int32 NX,int32 NY,double Offset,UMaterialInterface* Material,bool Soil,double EdgeFeatherCm=0);
};
