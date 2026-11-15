#pragma once
#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MRAssetTools.generated.h"
class UNiagaraSystem;
class UMaterialInterface;
class UStaticMesh;

UCLASS()
class METARESCUE_API UMRAssetTools : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()
public:
    // Reads source vertices/topology, not Nanite-expanded render bounds.
    UFUNCTION(BlueprintCallable,Category="Rescue|Asset Preparation")
    static FString DescribeMeshGeometry(UStaticMesh* Mesh);
    // Editor-only derivatives: split opaque and translucent triangles, never
    // feed unsupported translucent sections to Nanite or change an original.
    UFUNCTION(BlueprintCallable,Category="Rescue|Asset Preparation")
    static FString PrepareCityMesh(UStaticMesh* Source,const FString& PackageBase,FVector BakedScale);
    UFUNCTION(BlueprintCallable,Category="Rescue|Asset Preparation")
    static void FinishAssetCompilation();
    UFUNCTION(BlueprintCallable,Category="Rescue|Asset Preparation")
    static UNiagaraSystem* CreateEffect(const FString& EmitterPath,const FString& PackagePath,UMaterialInterface* Material);
    UFUNCTION(BlueprintCallable,Category="Rescue|Asset Preparation")
    static FString DescribeEffect(UNiagaraSystem* System);
    UFUNCTION(BlueprintCallable,Category="Rescue|Asset Preparation")
    static void ConfigureEffect(UNiagaraSystem* System,float Rate,float LifetimeMin,float LifetimeMax,
        float SizeMin,float SizeMax,float SpeedMin,float SpeedMax,FVector Gravity,float Spread);
};
