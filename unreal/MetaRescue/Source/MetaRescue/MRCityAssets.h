#pragma once
#include "CoreMinimal.h"
class UStaticMesh;
class UMaterialInterface;

struct FMRCityMeshPart
{
    UStaticMesh* Mesh=nullptr;
    bool bGlass=false;
};

bool MRCityAssetsReady();
TArray<FMRCityMeshPart> MRCityMeshParts(UStaticMesh* Source);
UStaticMesh* MRCityBakedBox(FVector SizeCm);
UMaterialInterface* MRCityMaterial(UMaterialInterface* Source);
UStaticMesh* MRCityFoliage(int32 Model);
UStaticMesh* MRCityVegetation(const FString& AssetId,int32 Revision);
UStaticMesh* MRCityProp(const FString& AssetId);
