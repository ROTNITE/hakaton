#include "MRStructureState.h"
#include "MRWorld.h"
#include "Components/StaticMeshComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/HierarchicalInstancedStaticMeshComponent.h"
#include "Engine/StaticMesh.h"

double FMRStructureState::RemainingTopCm() const
{
    double Top=Bounds.IsValid?Bounds.Min.Z:0;
    for(const auto& Part:Pieces)if(!Part.Removed)Top=FMath::Max(Top,Part.Bounds.Max.Z);
    return Top;
}

TArray<int32> FMRStructureState::UpperStoreyPieces() const
{
    TArray<int32> Result;
    if(IsRoad||!Bounds.IsValid)return Result;
    // Apartment() authors 300cm storeys. Collapse the unsupported upper
    // storey, retaining the slab on the supported storey beneath it. A later
    // event can remove the next storey; no untouched upper floor floats above
    // a removed lower wall. Ruin assemblies occupy a single remaining storey.
    const double Base=FMath::RoundToDouble(Bounds.Min.Z/300.)*300.;
    const double Top=RemainingTopCm();if(Top-Base<120)return Result;
    const double Cut=Base+FMath::Max(0.,FMath::CeilToDouble((Top-Base-100)/300.)-1)*300.;
    for(int32 I=0;I<Pieces.Num();++I)
    {
        const auto& Part=Pieces[I];
        if(!Part.Removed&&Part.Bounds.Min.Z>=Cut-35&&Part.Bounds.GetCenter().Z>=Cut+30&&Part.Bounds.Max.Z>=Cut+45)
            Result.Add(I);
    }
    return Result;
}

bool FMRStructurePiece::Remove()
{
    auto* Mesh=Component.Get();
    if(!Mesh||Removed)return false;
    if(Instanced)
    {
        auto* Batch=Cast<UInstancedStaticMeshComponent>(Mesh);
        if(!Batch||Cast<UHierarchicalInstancedStaticMeshComponent>(Mesh)||
            Batch->GetInstanceIndexForId(Instance)==INDEX_NONE)return false;
        Batch->RemoveInstanceById(Instance);Instance=FPrimitiveInstanceId();
    }
    else
    {
        Mesh->SetVisibility(false);Mesh->SetHiddenInGame(true);
        Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    }
    Removed=true;return true;
}

bool FMRStructurePiece::Restore()
{
    auto* Mesh=Component.Get();
    if(!Mesh||!Removed)return false;
    if(Instanced)
    {
        auto* Batch=Cast<UInstancedStaticMeshComponent>(Mesh);
        if(!Batch||Cast<UHierarchicalInstancedStaticMeshComponent>(Mesh))return false;
        Instance=Batch->AddInstanceById(InitialTransform,true);
        if(!Instance.IsValid())return false;
    }
    else
    {
        Mesh->SetVisibility(InitiallyVisible);Mesh->SetHiddenInGame(InitiallyHidden);
        Mesh->SetCollisionEnabled(Collision);
    }
    Removed=false;return true;
}

void AMRWorld::RecordCityStructure(FName Id,int32 FirstGenerated)
{
    if(!bDisasterCity)return;
    FMRStructureState Building;Building.Id=Id;
    TMap<UStaticMeshComponent*,int32> PartIndices;
    for(int32 I=FirstGenerated;I<Generated.Num();++I)
    {
        auto* Mesh=Cast<UStaticMeshComponent>(Generated[I]);
        if(!Mesh||!Mesh->GetStaticMesh()||Mesh->IsA<UInstancedStaticMeshComponent>())continue;
        FMRStructurePiece Piece;Piece.Component=Mesh;Piece.InitialTransform=Mesh->GetComponentTransform();
        Piece.Bounds=Mesh->GetStaticMesh()->GetBounds().TransformBy(Piece.InitialTransform).GetBox();
        Piece.Collision=Mesh->GetCollisionEnabled();Piece.InitiallyVisible=Mesh->IsVisible();Piece.InitiallyHidden=Mesh->bHiddenInGame;
        const int32 Index=Building.Pieces.Add(Piece);PartIndices.Add(Mesh,Index);
        CityPartOwners.Add(Mesh,{Id,Index});Building.Bounds+=Piece.Bounds;
        Mesh->ComponentTags.AddUnique(TEXT("CityStructurePart"));
    }
    for(int32 I=FirstGenerated;I<Generated.Num();++I)
    {
        auto* Root=Generated[I].Get();if(!Root)continue;
        if(Root->ComponentHasTag(TEXT("RoofFireAnchor")))
        {
            auto* Mesh=Cast<UStaticMeshComponent>(Root);const auto* Part=PartIndices.Find(Mesh);
            if(!Part)continue;
            const auto Box=Building.Pieces[*Part].Bounds;
            for(int32 Bay=-1;Bay<=1;++Bay)
            {
                FMRFireAnchor Anchor;Anchor.OwnerPiece=*Part;Anchor.Roof=true;Anchor.Delay=28;
                Anchor.Position=Box.GetCenter()+Root->GetForwardVector()*Bay*200;
                Anchor.Position.Z=Box.Max.Z+8;Anchor.Scale=FVector(1.6,1.6,1.8);
                Building.FireAnchors.Add(Anchor);
            }
        }
        if(!Root->ComponentHasTag(TEXT("WindowFireAnchor")))continue;
        TArray<USceneComponent*> AnchorParts;Root->GetChildrenComponents(true,AnchorParts);
        FBox Box(ForceInit);int32 Parent=INDEX_NONE;
        for(auto* Child:AnchorParts)if(auto* Mesh=Cast<UStaticMeshComponent>(Child))
            if(const auto* Index=PartIndices.Find(Mesh))
            {Box+=Building.Pieces[*Index].Bounds;if(Parent==INDEX_NONE)Parent=*Index;}
        if(!Box.IsValid||Parent==INDEX_NONE)continue;
        FMRFireAnchor Anchor;Anchor.OwnerPiece=Parent;
        Anchor.Normal=Root->GetComponentQuat().RotateVector(FVector(0,-1,0));
        Anchor.Position=Box.GetCenter()+Anchor.Normal*24;Anchor.Position.Z=Box.Min.Z-28;
        const float Width=FMath::Max(Box.GetSize().X,Box.GetSize().Y);
        Anchor.Scale=FVector(FMath::Clamp(Width/235.f,.55f,1.1f));
        for(const auto& Tag:Root->ComponentTags)
        {
            const FString Text=Tag.ToString();
            if(Text.StartsWith(TEXT("WindowFireDelay_")))Anchor.Delay=FCString::Atof(*Text.RightChop(16));
        }
        Building.FireAnchors.Add(Anchor);
    }
    UE_LOG(LogTemp,Verbose,TEXT("MR_STRUCTURE %s parts=%d fire_anchors=%d"),*Id.ToString(),Building.Pieces.Num(),Building.FireAnchors.Num());
    CityStructures.Add(Id,MoveTemp(Building));
}

void AMRWorld::RebindCityStructurePart(UStaticMeshComponent* Previous,UInstancedStaticMeshComponent* Batch,FPrimitiveInstanceId Id)
{
    const auto* PartOwner=CityPartOwners.Find(Previous);if(!PartOwner)return;
    auto* Building=CityStructures.Find(PartOwner->Structure);
    if(Building&&Building->Pieces.IsValidIndex(PartOwner->Piece))
    {
        auto& Part=Building->Pieces[PartOwner->Piece];Part.Component=Batch;Part.Instance=Id;Part.Instanced=true;
    }
    CityPartOwners.Remove(Previous);
}

void AMRWorld::ResetCityStructures()
{
    for(auto& Pair:CityStructures)for(auto& Part:Pair.Value.Pieces)if(Part.Removed)Part.Restore();
}
