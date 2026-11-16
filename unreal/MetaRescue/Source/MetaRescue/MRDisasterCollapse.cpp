#include "MRWorld.h"
#include "MRAgent.h"
#include "Components/HierarchicalInstancedStaticMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Materials/MaterialInterface.h"
#include "ProceduralMeshComponent.h"
#include "Misc/Crc.h"

void AMRWorld::RefreshCitySmokeHeights()
{
    if(!bDisasterCity)return;
    bool Changed=false;
    for(auto& Event:Environment.Applied)if(Event.Kind==EMRDisturbance::Fire)
        if(const auto* Building=CityStructures.Find(FName(*Event.SiteId)))
        {
            const float Height=float(Building->RemainingTopCm());
            if(!FMath::IsNearlyEqual(Event.SmokeEmissionHeightCm,Height))
            {Event.SmokeEmissionHeightCm=Height;Changed=true;}
        }
    if(Changed)++Environment.Revision;
}

void AMRWorld::BatchDisasterDebris(int32 First,const FMRDisturbance& Event)
{
    // Event-owned batches never append to the initial city's batches: reset
    // must remove debris without deleting an intact neighbor's geometry.
    TMap<FString,TArray<UStaticMeshComponent*>> Groups;
    for(int32 I=First;I<Generated.Num();++I)
        if(auto* Mesh=Cast<UStaticMeshComponent>(Generated[I]))
            if(!Mesh->IsA<UInstancedStaticMeshComponent>()&&Mesh->GetStaticMesh()&&Mesh->Mobility==EComponentMobility::Static)
            {
                FString Key=Mesh->GetStaticMesh()->GetPathName()+FString::Printf(TEXT("|%d"),int32(Mesh->GetCollisionEnabled()));
                for(int32 Slot=0;Slot<Mesh->GetNumMaterials();++Slot)Key+=TEXT("|")+GetPathNameSafe(Mesh->GetMaterial(Slot));
                Groups.FindOrAdd(Key).Add(Mesh);
            }
    for(auto& Pair:Groups)
    {
        auto* Source=Pair.Value[0];auto* Batch=NewObject<UHierarchicalInstancedStaticMeshComponent>(this);
        AddInstanceComponent(Batch);Batch->SetupAttachment(GetRootComponent());Batch->SetMobility(EComponentMobility::Static);
        Batch->SetStaticMesh(Source->GetStaticMesh());
        for(int32 Slot=0;Slot<Source->GetNumMaterials();++Slot)Batch->SetMaterial(Slot,Source->GetMaterial(Slot));
        Batch->SetCollisionProfileName(Source->GetCollisionProfileName());Batch->SetCollisionEnabled(Source->GetCollisionEnabled());
        Batch->SetCollisionResponseToChannels(Source->GetCollisionResponseToChannels());
        Batch->bAutoRebuildTreeOnInstanceChanges=false;
        Batch->ComponentTags={FName(*Event.Id),TEXT("StructuralDebris"),FName(*Event.SiteId)};
        for(auto* Mesh:Pair.Value)
        {
            Batch->AddInstance(Mesh->GetComponentTransform(),true);
            Generated.Remove(Mesh);RemoveInstanceComponent(Mesh);Mesh->DestroyComponent();
        }
        Batch->bAutoRebuildTreeOnInstanceChanges=true;Batch->BuildTreeIfOutdated(false,true);Batch->RegisterComponent();Generated.Add(Batch);
    }
    for(int32 I=Generated.Num()-1;I>=First;--I)
    {
        auto* Component=Generated[I].Get();
        if(Component&&Component->GetClass()==USceneComponent::StaticClass()&&Component->GetAttachChildren().IsEmpty())
        {Generated.RemoveAt(I);RemoveInstanceComponent(Component);Component->DestroyComponent();}
    }
}

bool AMRWorld::CollapseCityStructure(const FMRDisturbance& Event)
{
    if(!bDisasterCity||Event.bPropagation)return false;
    auto* Building=CityStructures.Find(FName(*Event.SiteId));if(!Building)return false;
    TArray<int32> Removed=Building->UpperStoreyPieces();if(Removed.IsEmpty())return true;
    Removed.Sort([&](int32 A,int32 B){return Building->Pieces[A].Bounds.GetVolume()>Building->Pieces[B].Bounds.GetVolume();});
    const int32 First=Generated.Num();int32 Bodies=0,LostParts=0;
    const FName StructureTag(*(FString(TEXT("SourceStructure_"))+Event.SiteId));
    TSet<FName> LostTags;
    for(int32 Index:Removed)
    {
        auto& Part=Building->Pieces[Index];auto* Source=Part.Component.Get();
        if(!Source||!Source->GetStaticMesh()||!Part.Remove())continue;
        ++LostParts;LostTags.Add(FName(*FString::Printf(TEXT("SourcePiece_%d"),Index)));
        // Only a bounded set of the largest real pieces is dynamic. Fine
        // material becomes detailed static fragments below, preserving city
        // frame time instead of simulating thousands of individual bricks.
        if(Bodies>=12||Part.Collision==ECollisionEnabled::NoCollision)continue;
        const auto Local=Source->GetStaticMesh()->GetBounds();
        const FVector Size=Local.BoxExtent*Part.InitialTransform.GetScale3D().GetAbs();
        if(Size.GetMin()<1||Size.GetMax()>700)continue;
        const FVector Center=Part.InitialTransform.TransformPosition(Local.Origin);
        auto* Body=NewObject<UProceduralMeshComponent>(this);AddInstanceComponent(Body);Body->SetupAttachment(GetRootComponent());
        Body->SetMobility(EComponentMobility::Movable);Body->bUseComplexAsSimpleCollision=false;Body->bUseAsyncCooking=false;
        Body->SetWorldLocationAndRotation(Center,Part.InitialTransform.GetRotation());
        Body->SetCollisionProfileName(TEXT("PhysicsActor"));Body->SetCollisionResponseToChannel(ECC_Camera,ECR_Ignore);
        Body->RegisterComponent();
        TArray<FVector> Corners;
        for(int32 Corner=0;Corner<8;++Corner)Corners.Add(FVector((Corner&1?1:-1)*Size.X,(Corner&2?1:-1)*Size.Y,(Corner&4?1:-1)*Size.Z));
        Body->AddCollisionConvexMesh(Corners);
        // An explicit bulk-density model, including openings, rather than
        // identical masses for a 9m roof and a small facade fragment.
        const double VolumeM3=8*Size.X*Size.Y*Size.Z/1.e6;
        Body->SetMassOverrideInKg(NAME_None,float(FMath::Clamp(VolumeM3*1600.,2.,60000.)));
        Body->SetLinearDamping(.35f);Body->SetAngularDamping(.8f);
        Body->ComponentTags={FName(*Event.Id),TEXT("StructuralDebris"),FName(*Event.SiteId)};
        auto* Visual=NewObject<UStaticMeshComponent>(this);AddInstanceComponent(Visual);Visual->SetupAttachment(Body);
        Visual->SetMobility(EComponentMobility::Movable);Visual->SetStaticMesh(Source->GetStaticMesh());
        for(int32 Slot=0;Slot<Source->GetNumMaterials();++Slot)Visual->SetMaterial(Slot,Source->GetMaterial(Slot));
        Visual->SetCollisionEnabled(ECollisionEnabled::NoCollision);Visual->SetWorldTransform(Part.InitialTransform);Visual->RegisterComponent();
        Body->SetNotifyRigidBodyCollision(true);Body->OnComponentHit.AddDynamic(this,&AMRWorld::OnRubbleHit);
        Body->SetSimulatePhysics(true);
        Generated.Add(Body);Generated.Add(Visual);PhysicsPieces.Add(Body);InitialPiecePositions.Add(Center);++Bodies;
    }
    for(int32 I=HazardVisuals.Num()-1;I>=0;--I)
    {
        auto* Effect=HazardVisuals[I].Get();if(!Effect||!Effect->ComponentHasTag(StructureTag))continue;
        if(!Effect->ComponentTags.ContainsByPredicate([&](FName Tag){return LostTags.Contains(Tag);}))continue;
        // ApplyCoreDisturbance records the first appended visual before this
        // call. Preserve indices until its tracking pass has registered the
        // new dust and smoke; TickHazardVisuals compacts these empty slots.
        CoreEventComponents.Remove(Effect);HazardVisuals[I]=nullptr;Effect->DestroyComponent();
    }
    FRandomStream Rng(FCrc::StrCrc32(*Event.Id)^uint32(Seed));
    FVector Out=(Event.Source-Building->Bounds.GetCenter()).GetSafeNormal2D();if(Out.IsNearlyZero())Out=FVector(1,0,0);
    const FVector Along(-Out.Y,Out.X,0);const FVector Center=Building->Bounds.GetCenter();
    FCollisionQueryParams Query(SCENE_QUERY_STAT(MRCollapseDeposit),false);
    for(AMRAgent* Agent:Agents)Query.AddIgnoredActor(Agent);
    for(UProceduralMeshComponent* Piece:PhysicsPieces)Query.AddIgnoredComponent(Piece);
    int32 Detailed=0;const int32 Count=FMath::Clamp(LostParts,36,80);
    for(int32 I=0;I<Count;++I)
    {
        FVector Spot=I%3==0?Center+FVector(Rng.FRandRange(-340,340),Rng.FRandRange(-340,340),0):
            Center+Out*Rng.FRandRange(460,1050)+Along*Rng.FRandRange(-550,550);
        if(I%3!=0&&!Event.Cells.Contains(FMRDistrictEnvironment::Cell(Spot)))continue;
        FHitResult Support;
        if(!GetWorld()->LineTraceSingleByChannel(Support,FVector(Spot.X,Spot.Y,Building->Bounds.Max.Z+1000),
            FVector(Spot.X,Spot.Y,Building->Bounds.Min.Z-1000),ECC_Visibility,Query)||Support.ImpactNormal.Z<.8)continue;
        const FRotator Turn(Rng.FRandRange(-13,13),Rng.FRandRange(-180,180),Rng.FRandRange(-10,10));
        GroundedAssembly(TEXT("SceneryKit"),Support.ImpactPoint,Turn,FVector(Rng.FRandRange(.7,1.35)),
            FString::Printf(TEXT("fragment_%d"),I%5));++Detailed;
        if(I==1)GroundedAssembly(TEXT("Rubble"),Support.ImpactPoint,FRotator(0,Turn.Yaw,0),FVector(.5,.55,.5));
        if(I==4)GroundedAssembly(TEXT("Slab"),Support.ImpactPoint,Turn,FVector(.55));
        if(I==7)GroundedAssembly(TEXT("Beam"),Support.ImpactPoint,FRotator(0,Turn.Yaw,0),FVector(.65));
    }
    BatchDisasterDebris(First,Event);RefreshCitySmokeHeights();
    UE_LOG(LogTemp,Display,TEXT("MR_STRUCTURE_COLLAPSE event=%s source=%s removed=%d bodies=%d detailed_fragments=%d remaining_top_cm=%.2f"),
        *Event.Id,*Event.SiteId,LostParts,Bodies,Detailed,Building->RemainingTopCm());
    return true;
}
