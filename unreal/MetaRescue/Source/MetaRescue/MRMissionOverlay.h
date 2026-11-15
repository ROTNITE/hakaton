#pragma once
#include "CoreMinimal.h"
#include "MRDisplayTrace.h"
class AMRHUD;
class UMRMissionSession;
class UProceduralMeshComponent;
class UStaticMeshComponent;
class APlayerController;
class AActor;
class UCanvas;
struct FBatchedLine;

class FMRMissionOverlay
{
public:
    explicit FMRMissionOverlay(AMRHUD* Owner):HUD(Owner){}
    ~FMRMissionOverlay();
    void Draw(UMRMissionSession* Session,UCanvas* Canvas);
private:
    TWeakObjectPtr<AMRHUD> HUD;
    TWeakObjectPtr<AActor> VisualActor;
    TWeakObjectPtr<UProceduralMeshComponent> Ribbons;
    TWeakObjectPtr<UStaticMeshComponent> KnowledgeFloor;
    TArray<TWeakObjectPtr<AActor>> HiddenByView;
    TMap<FString,FMRDisplayTrace> TruthTraces,PublicTraces;
    FString Episode;
    double LastTruthSample=-1;
    bool LastObserver=true;
    int32 Frames=0;
    int32 RibbonLineCount=-1;
    void RestoreVisibility();
};
