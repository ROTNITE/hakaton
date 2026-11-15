#pragma once
#include "CoreMinimal.h"

class UStaticMeshComponent;
class USceneComponent;
class AActor;
class UMaterialInterface;
UMaterialInterface* MRSceneMaterial(UMaterialInterface* Source);

struct FMRAssemblyPart
{
    UStaticMeshComponent* Mesh = nullptr;
    FTransform Rest;
    FString Name;
    FString Role;
    float Radius = 1;
    float Spin = 1;
    float Side = 0;
    float Phase = 0;
};

// Shared by prepared scenery and physical agents. Blender XY is converted to UE
// handedness here once; separate pivot-local meshes retain their own transforms.
USceneComponent* MRBuildAssembly(AActor* Owner, USceneComponent* Parent, const FString& Asset,
    const FVector& Location, const FRotator& Rotation, const FVector& Scale,
    bool Collision, bool Movable, TArray<FMRAssemblyPart>& Parts, const FString& Module = TEXT(""),bool CityAssets=false,bool DeferredStatic=false);
