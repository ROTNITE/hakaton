#pragma once
#include "CoreMinimal.h"
#include "UObject/StrongObjectPtr.h"
#include "MRExplorationMemory.h"
#include "ProceduralMeshComponent.h"

class AMRWorld;
class AMRAgent;
class UStaticMesh;
class UStaticMeshComponent;
class UMaterialInterface;
class APlayerController;
class UPostProcessComponent;
class FJsonObject;

struct FMRSceneSection
{
    TStrongObjectPtr<UMaterialInterface> Material;
    FProcMeshSection Geometry;
};
struct FMRSceneMesh
{
    uint64 Key=0;
    FTransform Pose;
    FBox Bounds=FBox(ForceInit);
    TStrongObjectPtr<UStaticMesh> Mesh;
    TArray<TStrongObjectPtr<UMaterialInterface>> Materials;
    TArray<FMRSceneSection> Procedural;
    bool Shadow=true;
};
struct FMRSceneActorState
{
    FString Id;
    double ObservedAt=-1;
    TArray<FMRSceneMesh> Meshes;
};
struct FMRSceneActorReport {TArray<FMRSceneActorState> Actors;};
struct FMRSceneCell
{
    FIntPoint Cell;
    double ObservedAt=-1;
    bool SurfaceVisible=false;
    TArray<FMRSceneSection> Surface;
};
struct FMRSceneReport
{
    double ObservedAt=-1;
    FString Source;
    TArray<FMRSceneCell> Cells;
    TArray<FMRSceneMesh> Objects; // An empty mesh is an optically witnessed removal.
};

// This object never changes physics or sensor queries. True renderers are
// hidden in command view; independent meshes contain only delivered samples.
class FMRExplorationScene
{
public:
    explicit FMRExplorationScene(AMRWorld* InWorld):World(InWorld){}
    ~FMRExplorationScene();
    void Reset(const FMRExplorationMemory& Knowledge);
    TSharedPtr<FMRSceneReport> Capture(const FMRExplorationMemory& Knowledge,
        const TArray<FMRSeenSurface>& Cells,FVector Eye,const FString& Source,double At,
        TFunctionRef<double(FVector,FVector)> Quality,bool Owned=false);
    void Apply(const FMRSceneReport& Report,const FMRExplorationMemory& Knowledge);
    TSharedPtr<FMRSceneActorReport> CaptureActor(AMRAgent* Agent,double At);
    TSharedPtr<FMRSceneActorReport> CaptureTarget(int32 Index,double At);
    void ApplyActors(const TSharedPtr<FMRSceneActorReport>& Report);
    void View(bool KnowledgeView,double At);
    TSharedPtr<FJsonObject> Snapshot() const;
    int32 GetRevision() const {return Revision;}
private:
    struct FSource
    {
        TWeakObjectPtr<UStaticMeshComponent> Mesh;
        TWeakObjectPtr<UProceduralMeshComponent> Procedural;
        uint64 Key=0;FTransform Pose;FBox Bounds=FBox(ForceInit);
        int32 Instance=INDEX_NONE;bool Alive=true;
    };
    struct FRememberedObject {FMRSceneMesh Value;double At=-1;};
    AMRWorld* World;
    FMRExplorationGrid Grid;
    TArray<FSource> Sources;
    TMap<FString,int32> SourceLookup;
    TMap<FIntPoint,TArray<int32>> SourceBins;
    TMap<uint64,FRememberedObject> Objects;
    TMap<int32,FMRSceneCell> Surfaces;
    TMap<FString,FMRSceneActorState> Actors;
    TMap<FString,TArray<TWeakObjectPtr<USceneComponent>>> ActorRenderers;
    TMap<FString,TStrongObjectPtr<UMaterialInterface>> Materials;
    TWeakObjectPtr<AActor> Renderer;
    TWeakObjectPtr<UPostProcessComponent> Matte;
    TArray<TWeakObjectPtr<USceneComponent>> ObjectRenderers;
    TMap<FIntPoint,TWeakObjectPtr<UProceduralMeshComponent>> TerrainRenderers;
    TSet<FIntPoint> DirtyTiles;
    TSet<FString> DirtyActors;
    bool ObjectsDirty=false,Active=false;
    int32 Revision=0,LastSignature=-1;
    double CatalogAt=-1;
    UMaterialInterface* RememberMaterial(UMaterialInterface* Material,double At);
    FMRSceneMesh ReadMesh(const FSource& Source,double At);
    FMRSceneActorState ReadActor(AActor* Actor,const FString& Id,double At,bool Erase=false);
    void RefreshSources(double At);
    void RebuildObjects();
    void RebuildTile(FIntPoint Tile);
    void RenderMeshes(const TArray<FMRSceneMesh>& Meshes,TArray<TWeakObjectPtr<USceneComponent>>& Output);
    void Restore();
};
