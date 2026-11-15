#include "MRWorld.h"
#include "Components/StaticMeshComponent.h"
#include "Components/HierarchicalInstancedStaticMeshComponent.h"
#include "Materials/MaterialInterface.h"
#include "Engine/StaticMesh.h"

void AMRWorld::OptimizeDistrictInstances()
{
    // Runtime construction places/grounds/rotates pieces while movable, then
    // commits the final transforms before creating static render instances.
    if(bCityLayout)
    {
        for(USceneComponent* C:Generated)if(C&&C->ComponentHasTag(TEXT("CityStaticPending")))
        {C->SetMobility(EComponentMobility::Static);C->ComponentTags.Remove(TEXT("CityStaticPending"));}
    }
    TArray<UStaticMeshComponent*> Components;
    if(bCityLayout){for(USceneComponent* C:Generated)if(auto* Mesh=Cast<UStaticMeshComponent>(C))Components.Add(Mesh);}
    else GetComponents(Components);
    TMap<FString,TArray<UStaticMeshComponent*>> Groups;
    TMap<FString,UHierarchicalInstancedStaticMeshComponent*> Existing;
    auto KeyFor=[](UStaticMeshComponent* C)
    {
        FString Key=C->GetStaticMesh()->GetPathName()+FString::Printf(TEXT("|%d|%d|%d"),int32(C->GetCollisionEnabled()),C->IsVisible(),C->bHiddenInGame);
        for(int32 Slot=0;Slot<C->GetNumMaterials();Slot++)Key+=TEXT("|")+GetPathNameSafe(C->GetMaterial(Slot));
        Key+=FString::Printf(TEXT("|%d|%d|%d"),int32(C->GetCollisionResponseToChannel(ECC_Visibility)),
            int32(C->CastShadow),int32(C->bAffectDistanceFieldLighting));
        if(C->ComponentHasTag(TEXT("CityVisualHorizon")))Key+=TEXT("|horizon");
        return Key;
    };
    for(auto* C:Components)
    {
        if(C->Mobility!=EComponentMobility::Static||!C->GetStaticMesh())continue;
        if(C->ComponentHasTag(TEXT("CollapseSupport")))
        {if(!bBuildingCity&&!C->IsRegistered())C->RegisterComponent();continue;}
        if(auto* Batch=Cast<UHierarchicalInstancedStaticMeshComponent>(C))
        {if(bCityLayout)Existing.Add(KeyFor(C),Batch);continue;}
        if(C->IsA<UInstancedStaticMeshComponent>())continue;
        // Non-Nanite HISM has no Lumen surface-cache coverage. Keep enclosing
        // room surfaces and window frames as individual static meshes so their
        // indirect daylight and reflections are represented throughout town.
        const FString MeshPath=C->GetStaticMesh()->GetPathName();
        const FString MeshName=C->GetStaticMesh()->GetName();
        if(!bCityLayout&&(C->ComponentHasTag(TEXT("InteriorLightingSurface"))||MeshPath.Contains(TEXT("/GlazingKit/"))||
            MeshPath.Contains(TEXT("/SceneryKit/SM_room_"))||MeshPath.Contains(TEXT("/UrbanKit/SM_wall_"))||
            MeshName.StartsWith(TEXT("SM_window_"))||MeshName.StartsWith(TEXT("SM_wall_"))))continue;
        Groups.FindOrAdd(KeyFor(C)).Add(C);
    }
    int32 Instances=0;
    for(auto& Pair:Groups)
    {
        auto& Group=Pair.Value;if(Group.Num()<3&&!bCityLayout)continue;
        auto* Source=Group[0];auto* Batch=Existing.FindRef(Pair.Key);
        if(!Batch)
        {
        Batch=NewObject<UHierarchicalInstancedStaticMeshComponent>(this);
        AddInstanceComponent(Batch);Batch->SetupAttachment(GetRootComponent());Batch->SetMobility(EComponentMobility::Static);
        Batch->SetStaticMesh(Source->GetStaticMesh());
        for(int32 I=0;I<Source->GetNumMaterials();I++)Batch->SetMaterial(I,Source->GetMaterial(I));
        Batch->SetCollisionProfileName(Source->GetCollisionProfileName());Batch->SetCollisionEnabled(Source->GetCollisionEnabled());
        Batch->SetCollisionResponseToChannels(Source->GetCollisionResponseToChannels());
        Batch->SetVisibility(Source->IsVisible());Batch->SetHiddenInGame(Source->bHiddenInGame);
        Batch->SetCastShadow(Source->CastShadow);
        Batch->SetAffectDistanceFieldLighting(Source->bAffectDistanceFieldLighting);
        Generated.Add(Batch);
        }
        Batch->bAutoRebuildTreeOnInstanceChanges=false;
        for(auto* C:Group)
        {
            Batch->AddInstance(C->GetComponentTransform(),true);
            for(FName Tag:C->ComponentTags)Batch->ComponentTags.AddUnique(Tag);
            Generated.Remove(C);RemoveInstanceComponent(C);C->DestroyComponent();Instances++;
        }
        if(!bBuildingCity)
        {
            Batch->bAutoRebuildTreeOnInstanceChanges=true;Batch->BuildTreeIfOutdated(false,true);
            if(!Batch->IsRegistered())Batch->RegisterComponent();
        }
        Batch->ComponentTags.Add(TEXT("V3InstancedGeometry"));
    }
    if(bCityLayout)for(int32 I=Generated.Num()-1;I>=0;I--)
    {
        auto* C=Generated[I].Get();
        if(C&&!C->IsRegistered()&&C->GetClass()==USceneComponent::StaticClass()&&C->GetAttachChildren().IsEmpty())
        {Generated.RemoveAt(I);RemoveInstanceComponent(C);C->DestroyComponent();}
    }
    UE_LOG(LogTemp,Display,TEXT("MR_V3_INSTANCES %d source components batched"),Instances);
}
