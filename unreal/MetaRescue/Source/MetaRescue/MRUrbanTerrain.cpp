#include "MRUrbanTerrain.h"
#include "MRWorld.h"
#include "MRAgent.h"
#include "MRCoreJson.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/World.h"
#include "Materials/MaterialInterface.h"
#include "Engine/StaticMesh.h"
#include "ProceduralMeshComponent.h"
#include "Misc/Crc.h"

double FMRRoadCavity::DropCm(FVector P) const
{
    const FVector Delta=P-Center,Across(-Along.Y,Along.X,0);
    const double U=FVector::DotProduct(Delta,Along)/AlongCm,V=FVector::DotProduct(Delta,Across)/AcrossCm;
    const double Angle=FMath::Atan2(V,U);
    const double Edge=1+.09*FMath::Sin(5*Angle+Phase)+.045*FMath::Sin(9*Angle-Phase);
    const double Radius=FMath::Sqrt(U*U+V*V)/Edge;
    return DepthCm*(1-FMath::SmoothStep(.18,1.,Radius));
}

FBox FMRRoadCavity::Bounds() const
{
    const double Radius=1.15*FMath::Max(AlongCm,AcrossCm);
    return FBox(Center-FVector(Radius,Radius,DepthCm+10),Center+FVector(Radius,Radius,10));
}

double FMRUrbanTerrain::DropCm(FVector P) const
{
    double Drop=0;
    for(const auto& Cavity:Cavities)if(Cavity.Bounds().IsInsideXY(P))Drop=FMath::Max(Drop,Cavity.DropCm(P));
    if(Drop<=0)return 0;
    // Preserve real foundations; the road cavity does not silently excavate
    // beneath a nearby intact house and leave its walls suspended in air.
    const auto* Nearby=Foundations.Find(FIntPoint(FMath::FloorToInt(P.X/3200),FMath::FloorToInt(P.Y/3200)));
    if(!Nearby)return Drop;
    for(const auto& Box:*Nearby)
    {
        const double DX=FMath::Max3(Box.Min.X-P.X,0.,P.X-Box.Max.X);
        const double DY=FMath::Max3(Box.Min.Y-P.Y,0.,P.Y-Box.Max.Y);
        Drop*=FMath::SmoothStep(0.,100.,FMath::Sqrt(DX*DX+DY*DY));
        if(Drop<=0)return 0;
    }
    return Drop;
}

void FMRUrbanTerrain::AddFoundation(FBox Bounds)
{
    const FBox Range=Bounds.ExpandBy(100);
    for(int32 X=FMath::FloorToInt(Range.Min.X/3200);X<=FMath::FloorToInt(Range.Max.X/3200);++X)
        for(int32 Y=FMath::FloorToInt(Range.Min.Y/3200);Y<=FMath::FloorToInt(Range.Max.Y/3200);++Y)
            Foundations.FindOrAdd(FIntPoint(X,Y)).Add(Bounds);
}

void FMRUrbanTerrain::Grid(FVector Origin,FVector X,FVector Y,int32 NX,int32 NY,double Offset,UMaterialInterface* Material,bool Soil)
{
    FPatch Patch;Patch.Offset=Offset;Patch.Soil=Soil;Patch.Collision=true;
    Patch.GridOrigin=Origin;Patch.GridX=X;Patch.GridY=Y;Patch.InitialNX=NX;Patch.InitialNY=NY;
    auto* Mesh=NewObject<UProceduralMeshComponent>(World);World->AddInstanceComponent(Mesh);Mesh->SetupAttachment(World->GetRootComponent());
    Mesh->SetMobility(EComponentMobility::Static);Mesh->SetWorldLocation(Origin);
    Mesh->bUseComplexAsSimpleCollision=true;Mesh->bUseAsyncCooking=false;
    Mesh->SetCollisionProfileName(TEXT("BlockAll"));Mesh->SetCollisionResponseToChannel(ECC_Camera,ECR_Ignore);
    Mesh->SetMaterial(0,Material);
    Mesh->SetMaterial(1,LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/EffectsV3/Revision5/M_EventMud.M_EventMud")));
    Mesh->ComponentTags={Soil?TEXT("UrbanPhysicalTerrain"):TEXT("UrbanRoadSurface")};Mesh->RegisterComponent();
    Patch.Mesh=Mesh;
    Tessellate(Patch,NX,NY);
    Patches.Add(MoveTemp(Patch));Update(Patches.Last());World->Generated.Add(Mesh);
}

void FMRUrbanTerrain::Tessellate(FPatch& Patch,int32 NX,int32 NY)
{
    Patch.XY.Empty();Patch.Triangles.Empty();Patch.Bounds=FBox(ForceInit);
    for(int32 J=0;J<=NY;++J)for(int32 I=0;I<=NX;++I)
    {
        const FVector P=Patch.GridOrigin+Patch.GridX*(double(I)/NX)+Patch.GridY*(double(J)/NY);
        Patch.XY.Add(P);Patch.Bounds+=P;
    }
    for(int32 J=0;J<NY;++J)for(int32 I=0;I<NX;++I)
    {const int32 A=J*(NX+1)+I;Patch.Triangles.Append({A,A+NX+1,A+1,A+1,A+NX+1,A+NX+2});}
}

void FMRUrbanTerrain::Update(FPatch& Patch)
{
    auto* Mesh=Patch.Mesh.Get();if(!Mesh)return;
    TArray<FVector> Vertices,Normals;TArray<FVector2D> UV;TArray<int32> Intact,Broken;
    const FVector Origin=Mesh->GetComponentLocation();Vertices.Reserve(Patch.XY.Num());Normals.Reserve(Patch.XY.Num());
    TArray<double> Drops;Drops.Reserve(Patch.XY.Num());
    for(const auto& XY:Patch.XY)
    {
        const double Drop=DropCm(XY);Drops.Add(Drop);
        Vertices.Add(XY-Origin+FVector(0,0,Patch.Offset-(Patch.Soil?Drop:0)));
        const double DX=DropCm(XY+FVector(50,0,0))-DropCm(XY-FVector(50,0,0));
        const double DY=DropCm(XY+FVector(0,50,0))-DropCm(XY-FVector(0,50,0));
        Normals.Add(Patch.Soil?FVector(DX/100,DY/100,1).GetSafeNormal():FVector::UpVector);
        UV.Add(FVector2D(XY.X/500.,XY.Y/500.));
    }
    for(int32 I=0;I<Patch.Triangles.Num();I+=3)
    {
        const int32 A=Patch.Triangles[I],B=Patch.Triangles[I+1],C=Patch.Triangles[I+2];
        const double Drop=FMath::Max3(Drops[A],Drops[B],Drops[C]);
        if(!Patch.Soil&&Drop>5)continue;
        (Patch.Soil&&Drop>.2?Broken:Intact).Append({A,B,C});
    }
    Mesh->ClearAllMeshSections();
    Mesh->CreateMeshSection_LinearColor(0,Vertices,Intact,Normals,UV,{}, {},Patch.Collision);
    if(!Broken.IsEmpty())Mesh->CreateMeshSection_LinearColor(1,Vertices,Broken,Normals,UV,{}, {},Patch.Collision);
}

void FMRUrbanTerrain::Update(FOverlay& Overlay)
{
    auto* Mesh=Overlay.Mesh.Get();if(!Mesh)return;
    TArray<int32> Triangles;
    for(int32 I=0;I<Overlay.Triangles.Num();I+=3)
    {
        const int32 A=Overlay.Triangles[I],B=Overlay.Triangles[I+1],C=Overlay.Triangles[I+2];
        if(FMath::Max3(DropCm(Mesh->GetComponentTransform().TransformPosition(Overlay.Positions[A])),
            DropCm(Mesh->GetComponentTransform().TransformPosition(Overlay.Positions[B])),
            DropCm(Mesh->GetComponentTransform().TransformPosition(Overlay.Positions[C])))>5)continue;
        Triangles.Append({A,B,C});
    }
    Mesh->CreateMeshSection_LinearColor(Overlay.Section,Overlay.Positions,Triangles,Overlay.Normals,Overlay.UV,Overlay.Colors,{},Overlay.Collision);
}

void FMRUrbanTerrain::CutOverlays(const FMRRoadCavity& Cavity)
{
    for(USceneComponent* Component:World->Generated)
    {
        auto* Mesh=Cast<UProceduralMeshComponent>(Component);
        if(!Mesh||Mesh->ComponentHasTag(TEXT("UrbanPhysicalTerrain"))||Mesh->ComponentHasTag(TEXT("UrbanRoadSurface"))||
            World->PhysicsPieces.Contains(Mesh)||!Mesh->Bounds.GetBox().IntersectXY(Cavity.Bounds()))continue;
        for(int32 Section=0;Section<Mesh->GetNumSections();++Section)
        {
            auto* Source=Mesh->GetProcMeshSection(Section);if(!Source)continue;
            auto* Cached=Overlays.FindByPredicate([&](const auto& Item){return Item.Mesh.Get()==Mesh&&Item.Section==Section;});
            if(!Cached)
            {
                FOverlay Overlay;Overlay.Mesh=Mesh;Overlay.Section=Section;Overlay.Collision=Source->bEnableCollision;
                for(const auto& Vertex:Source->ProcVertexBuffer)
                {Overlay.Positions.Add(Vertex.Position);Overlay.Normals.Add(Vertex.Normal);Overlay.UV.Add(Vertex.UV0);Overlay.Colors.Add(Vertex.Color.ReinterpretAsLinear());}
                for(uint32 Index:Source->ProcIndexBuffer)Overlay.Triangles.Add(int32(Index));
                Overlays.Add(MoveTemp(Overlay));Cached=&Overlays.Last();
            }
            Update(*Cached);
        }
    }
}

void FMRUrbanTerrain::Build()
{
    for(const auto& Entry:World->CityLayout->GetArrayField(TEXT("buildings")))
    {
        const auto Bounds=Entry->AsObject()->GetObjectField(TEXT("bounds"));FVector Min,Max;
        MRCoreJson::Point(Bounds->TryGetField(TEXT("min")),Min);MRCoreJson::Point(Bounds->TryGetField(TEXT("max")),Max);
        AddFoundation(FBox(Min*100,Max*100));
    }
    const auto Base=World->CityLayout->GetObjectField(TEXT("base"));FVector Min,Max;
    MRCoreJson::Point(Base->TryGetField(TEXT("min")),Min);MRCoreJson::Point(Base->TryGetField(TEXT("max")),Max);
    AddFoundation(FBox(Min*100,Max*100));
    const double Size=World->GridSize*1000.;
    auto* Material=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/RescueAssets/CityV2/SurfacesR4/M_Verge.M_Verge"));
    for(double X=-6400;X<Size+6400;X+=6400)for(double Y=-6400;Y<Size+6400;Y+=6400)
    {
        const double W=FMath::Min(6400.,Size+6400-X),H=FMath::Min(6400.,Size+6400-Y);
        Grid(FVector(X,Y,0),FVector(W,0,0),FVector(0,H,0),FMath::CeilToInt(W/200),FMath::CeilToInt(H/200),0,Material,true);
    }
}

void FMRUrbanTerrain::RoadPatch(FVector Start,FVector End,double Width,double Offset,UMaterialInterface* Material)
{
    const FVector Delta=End-Start;const double Length=Delta.Size2D();if(Length<2)return;
    const FVector Along=Delta/Length,Across(-Along.Y,Along.X,0);
    Grid(Start-Across*Width*.5,Delta,Across*Width,FMath::CeilToInt(Length/200),FMath::CeilToInt(Width/100),Offset,Material,false);
}

bool FMRUrbanTerrain::Damage(const FMRDisturbance& Event)
{
    if(Cavities.ContainsByPredicate([&](const auto& C){return C.Id==Event.Id;}))return false;
    FMRRoadCavity Cavity;Cavity.Id=Event.Id;Cavity.Center=Event.Source;Cavity.Center.Z=0;
    const auto Graph=World->CityLayout->GetObjectField(TEXT("road_graph"));TMap<FString,FVector> Nodes;
    for(const auto& Entry:Graph->GetArrayField(TEXT("nodes")))
    {const auto Node=Entry->AsObject();FVector P;MRCoreJson::Point(Node->TryGetField(TEXT("position")),P);Nodes.Add(Node->GetStringField(TEXT("id")),P*100);}
    double Best=MAX_dbl;
    for(const auto& Entry:Graph->GetArrayField(TEXT("edges")))
    {
        const auto Edge=Entry->AsObject();const FVector A=Nodes.FindChecked(Edge->GetStringField(TEXT("from"))),B=Nodes.FindChecked(Edge->GetStringField(TEXT("to")));
        const double Distance=FVector::DistSquared2D(Cavity.Center,FMath::ClosestPointOnSegment(Cavity.Center,A,B));
        if(Distance<Best)
        {
            Best=Distance;Cavity.Along=(B-A).GetSafeNormal2D();Cavity.AcrossCm=Edge->GetNumberField(TEXT("width_m"))*65+100;
            Cavity.RoadId=TEXT("road-")+Edge->GetStringField(TEXT("from"))+TEXT("-")+Edge->GetStringField(TEXT("to"));
        }
    }
    FRandomStream Rng(FCrc::StrCrc32(*Event.Id)^uint32(World->Seed));
    Cavity.AlongCm=Rng.FRandRange(400,650);Cavity.DepthCm=Rng.FRandRange(180,240);Cavity.Phase=Rng.FRandRange(0,2*PI);
    Cavities.Add(Cavity);
    for(auto& Patch:Patches)if(Patch.Bounds.IntersectXY(Cavity.Bounds()))
    {
        // Refine only the few patches touched by damage. A half-metre rim
        // has visible fractured edges without tessellating a 1.5km city so
        // densely before anything has happened.
        if(!Patch.Refined)
        {Tessellate(Patch,FMath::CeilToInt(Patch.GridX.Size()/50),FMath::CeilToInt(Patch.GridY.Size()/50));Patch.Refined=true;}
        Update(Patch);
    }
    CutOverlays(Cavity);
    for(auto& Pair:World->CityStructures)if(Pair.Value.IsRoad)
        for(auto& Part:Pair.Value.Pieces)if(!Part.Removed)
        {
            const FVector Closest=Part.Bounds.GetClosestPointTo(Cavity.Center);
            if(DropCm(Closest)>5||DropCm(Part.Bounds.GetCenter())>5)Part.Remove();
        }
    UE_LOG(LogTemp,Display,TEXT("MR_ROAD_CAVITY %s source=%s depth_cm=%.2f radius_along_cm=%.2f radius_across_cm=%.2f"),
        *Event.Id,*Event.Source.ToString(),DropCm(Event.Source),Cavity.AlongCm,Cavity.AcrossCm);
    return true;
}

void FMRUrbanTerrain::Reset()
{
    if(Cavities.IsEmpty())return;
    TArray<FBox> Changed;for(const auto& Cavity:Cavities)Changed.Add(Cavity.Bounds());Cavities.Empty();
    for(auto& Patch:Patches)if(Changed.ContainsByPredicate([&](const FBox& Box){return Box.IntersectXY(Patch.Bounds);}))
    {
        if(Patch.Refined){Tessellate(Patch,Patch.InitialNX,Patch.InitialNY);Patch.Refined=false;}
        Update(Patch);
    }
    for(auto& Overlay:Overlays)Update(Overlay);Overlays.Empty();
}

void AMRWorld::BuildUrbanTerrain()
{UrbanTerrain=MakeShared<FMRUrbanTerrain>(this);UrbanTerrain->Build();}
void AMRWorld::UrbanRoadPatch(FVector Start,FVector End,double Width,double Offset,const FString& Material)
{
    const FString Path=TEXT("/Game/Materials/")+Material+TEXT(".")+Material;
    if(UrbanTerrain)UrbanTerrain->RoadPatch(Start,End,Width,Offset,MRSceneMaterial(LoadObject<UMaterialInterface>(nullptr,*Path)));
}
void AMRWorld::DamageUrbanRoad(const FMRDisturbance& Event)
{
    if(!UrbanTerrain||!UrbanTerrain->Damage(Event))return;
    const auto Cavity=UrbanTerrain->Cavities.Last();const int32 First=Generated.Num();
    FRandomStream Rng(FCrc::StrCrc32(*Event.Id)^uint32(Seed));
    auto* Asphalt=MRSceneMaterial(LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/Materials/M_QuarterAsphalt.M_QuarterAsphalt")));
    FCollisionQueryParams Query(SCENE_QUERY_STAT(MRRoadRimDeposit),false);
    for(AMRAgent* Agent:Agents)Query.AddIgnoredActor(Agent);
    for(UProceduralMeshComponent* Piece:PhysicsPieces)Query.AddIgnoredComponent(Piece);
    const FVector Across(-Cavity.Along.Y,Cavity.Along.X,0);
    int32 Placed=0;
    for(int32 I=0;I<32;++I)
    {
        const double Angle=I*2*PI/32+Rng.FRandRange(-.04,.04);
        const FVector Spot=Cavity.Center+Cavity.Along*(FMath::Cos(Angle)*Cavity.AlongCm*1.3)+Across*(FMath::Sin(Angle)*Cavity.AcrossCm*1.3);
        FHitResult Support;
        if(!GetWorld()->LineTraceSingleByChannel(Support,Spot+FVector(0,0,180),Spot-FVector(0,0,600),ECC_Visibility,Query)||
            Support.ImpactNormal.Z<.9||UrbanTerrain->DropCm(Spot)>5)continue;
        if(Placed<4)
        {
            auto* Piece=Chunk(Rng,Support.ImpactPoint+FVector(0,0,45),FVector(Rng.FRandRange(40,90),Rng.FRandRange(35,70),Rng.FRandRange(8,16)),true);
            Piece->SetMaterial(0,Asphalt);Piece->ComponentTags={FName(*Event.Id),TEXT("StructuralDebris"),FName(*Cavity.RoadId)};
        }
        else
        {
            auto* Root=GroundedAssembly(TEXT("SceneryKit"),Support.ImpactPoint,FRotator(0,Rng.FRandRange(-180,180),0),
                FVector(Rng.FRandRange(.35,.75)),FString::Printf(TEXT("fragment_%d"),I%4));
            if(Root&&I%3)for(USceneComponent* Child:Root->GetAttachChildren())
                if(auto* Mesh=Cast<UStaticMeshComponent>(Child))
                    for(int32 Slot=0;Slot<Mesh->GetNumMaterials();++Slot)Mesh->SetMaterial(Slot,Asphalt);
        }
        ++Placed;
    }
    BatchDisasterDebris(First,Event);
    UE_LOG(LogTemp,Display,TEXT("MR_ROAD_DEBRIS event=%s source=%s grounded_fragments=%d"),*Event.Id,*Cavity.RoadId,Placed);
}
void AMRWorld::ResetUrbanTerrain()
{if(UrbanTerrain)UrbanTerrain->Reset();}
