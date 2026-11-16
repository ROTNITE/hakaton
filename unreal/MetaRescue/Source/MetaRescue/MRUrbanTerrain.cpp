#include "MRUrbanTerrain.h"
#include "MRWorld.h"
#include "MRUrbanWater.h"
#include "MRAgent.h"
#include "MRCoreJson.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/World.h"
#include "Materials/MaterialInterface.h"
#include "Materials/MaterialInstanceDynamic.h"
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

void FMRUrbanTerrain::Grid(FVector Origin,FVector X,FVector Y,int32 NX,int32 NY,double Offset,UMaterialInterface* Material,bool Soil,double EdgeFeatherCm)
{
    FPatch Patch;Patch.Offset=Offset;Patch.Soil=Soil;Patch.Collision=true;Patch.EdgeFeatherCm=EdgeFeatherCm;
    Patch.GridOrigin=Origin;Patch.GridX=X;Patch.GridY=Y;Patch.InitialNX=NX;Patch.InitialNY=NY;
    auto* Mesh=NewObject<UProceduralMeshComponent>(World);World->AddInstanceComponent(Mesh);Mesh->SetupAttachment(World->GetRootComponent());
    Mesh->SetMobility(EComponentMobility::Static);Mesh->SetWorldLocation(Origin);
    Mesh->bUseComplexAsSimpleCollision=true;Mesh->bUseAsyncCooking=false;
    Mesh->SetCollisionProfileName(TEXT("BlockAll"));Mesh->SetCollisionResponseToChannel(ECC_Camera,ECR_Ignore);
    Mesh->SetMaterial(0,Material);
    auto* BankMaterial=UMaterialInstanceDynamic::Create(LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/EffectsV3/Revision5/M_EventMud.M_EventMud")),Mesh);
    BankMaterial->SetVectorParameterValue(TEXT("MudTint"),FLinearColor(.42f,.32f,.22f));
    Mesh->SetMaterial(1,BankMaterial);Mesh->SetMaterial(2,Material);
    Mesh->SetMaterial(3,LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/Materials/MI_Concrete.MI_Concrete")));
    Mesh->ComponentTags={Soil?TEXT("UrbanPhysicalTerrain"):TEXT("UrbanRoadSurface")};Mesh->RegisterComponent();
    Patch.Mesh=Mesh;
    Tessellate(Patch,NX,NY);
    const int32 Id=Patches.Add(MoveTemp(Patch));const auto& Bounds=Patches[Id].Bounds;
    for(int32 XBin=FMath::FloorToInt(Bounds.Min.X/3200);XBin<=FMath::FloorToInt(Bounds.Max.X/3200);++XBin)
        for(int32 YBin=FMath::FloorToInt(Bounds.Min.Y/3200);YBin<=FMath::FloorToInt(Bounds.Max.Y/3200);++YBin)
            PatchBins.FindOrAdd(FIntPoint(XBin,YBin)).Add(Id);
    Update(Patches[Id]);World->Generated.Add(Mesh);
}

void FMRUrbanTerrain::Tessellate(FPatch& Patch,int32 NX,int32 NY)
{
    Patch.XY.Empty();Patch.Triangles.Empty();Patch.Bounds=FBox(ForceInit);
    Patch.NX=NX;Patch.NY=NY;
    for(int32 J=0;J<=NY;++J)for(int32 I=0;I<=NX;++I)
    {
        const FVector P=Patch.GridOrigin+Patch.GridX*(double(I)/NX)+Patch.GridY*(double(J)/NY);
        Patch.XY.Add(P);Patch.Bounds+=P;
    }
    for(int32 J=0;J<NY;++J)for(int32 I=0;I<NX;++I)
    {const int32 A=J*(NX+1)+I;Patch.Triangles.Append({A,A+NX+1,A+1,A+1,A+NX+1,A+NX+2});}
}

double FMRUrbanTerrain::HeightAt(const FPatch& Patch,FVector P) const
{
    double Layer=Patch.Offset;
    if(Patch.EdgeFeatherCm>0)
    {
        const double Edge=FMath::Min(FMath::Min(P.X-Patch.Bounds.Min.X,Patch.Bounds.Max.X-P.X),
            FMath::Min(P.Y-Patch.Bounds.Min.Y,Patch.Bounds.Max.Y-P.Y));
        Layer*=FMath::Clamp(Edge/Patch.EdgeFeatherCm,0.,1.);
    }
    return InitialHeight(P)+Layer-(Patch.Soil?DropCm(P):0);
}

double FMRUrbanTerrain::GroundHeight(FVector P) const
{
    double Highest=-MAX_dbl;
    const auto* Nearby=PatchBins.Find(FIntPoint(FMath::FloorToInt(P.X/3200),FMath::FloorToInt(P.Y/3200)));
    if(!Nearby)return InitialHeight(P)-DropCm(P);
    for(int32 Id:*Nearby)
    {
        const auto& Patch=Patches[Id];const FVector Delta=P-Patch.GridOrigin;
        const double U=(Delta.X*Patch.GridX.X+Delta.Y*Patch.GridX.Y)/Patch.GridX.SizeSquared2D();
        const double V=(Delta.X*Patch.GridY.X+Delta.Y*Patch.GridY.Y)/Patch.GridY.SizeSquared2D();
        if(U< -1.e-8||V< -1.e-8||U>1+1.e-8||V>1+1.e-8)continue;
        const double GX=FMath::Clamp(U,0.,1.)*Patch.NX,GY=FMath::Clamp(V,0.,1.)*Patch.NY;
        const int32 X=FMath::Min(Patch.NX-1,FMath::FloorToInt(GX)),Y=FMath::Min(Patch.NY-1,FMath::FloorToInt(GY));
        const double FX=GX-X,FY=GY-Y;const int32 A=Y*(Patch.NX+1)+X;
        int32 Indices[3];double Weights[3];
        if(FX+FY<=1)
        {Indices[0]=A;Indices[1]=A+1;Indices[2]=A+Patch.NX+1;Weights[0]=1-FX-FY;Weights[1]=FX;Weights[2]=FY;}
        else
        {Indices[0]=A+Patch.NX+2;Indices[1]=A+1;Indices[2]=A+Patch.NX+1;Weights[0]=FX+FY-1;Weights[1]=1-FY;Weights[2]=1-FX;}
        if(!Patch.Soil&&FMath::Max3(DropCm(Patch.XY[Indices[0]]),DropCm(Patch.XY[Indices[1]]),DropCm(Patch.XY[Indices[2]]))>20)continue;
        const FVector Q0=Patch.XY[Indices[0]],Q1=Patch.XY[Indices[1]],Q2=Patch.XY[Indices[2]];
        const double H0=HeightAt(Patch,Q0),H1=HeightAt(Patch,Q1),H2=HeightAt(Patch,Q2);
        const double Span=FMath::Max3(FVector::Dist2D(Q0,Q1),FVector::Dist2D(Q0,Q2),FVector::Dist2D(Q1,Q2));
        if(!Patch.Soil&&FMath::Max3(H0,H1,H2)-FMath::Min3(H0,H1,H2)>.3*Span)continue;
        Highest=FMath::Max(Highest,H0*Weights[0]+H1*Weights[1]+H2*Weights[2]);
    }
    return Highest== -MAX_dbl?InitialHeight(P)-DropCm(P):Highest;
}

void FMRUrbanTerrain::Update(FPatch& Patch)
{
    auto* Mesh=Patch.Mesh.Get();if(!Mesh)return;
    TArray<FVector> Vertices,Normals;TArray<FVector2D> UV;TArray<int32> Intact,Broken;
    const FVector Origin=Mesh->GetComponentLocation();Vertices.Reserve(Patch.XY.Num());Normals.Reserve(Patch.XY.Num());
    TArray<double> Drops;Drops.Reserve(Patch.XY.Num());
    auto Height=[&](FVector Q){return HeightAt(Patch,Q);};
    for(const auto& XY:Patch.XY)
    {
        const double Drop=DropCm(XY);Drops.Add(Drop);
        const FVector P(XY.X,XY.Y,Height(XY));
        Vertices.Add(P-Origin);
        const double DX=Height(XY+FVector(50,0,0))-Height(XY-FVector(50,0,0));
        const double DY=Height(XY+FVector(0,50,0))-Height(XY-FVector(0,50,0));
        Normals.Add(FVector(-DX/100,-DY/100,1).GetSafeNormal());
        UV.Add(FVector2D(XY.X/500.,XY.Y/500.));
    }
    TMap<FIntPoint,uint8> Edges;
    for(int32 I=0;I<Patch.Triangles.Num();I+=3)
    {
        const int32 A=Patch.Triangles[I],B=Patch.Triangles[I+1],C=Patch.Triangles[I+2];
        const double Drop=FMath::Max3(Drops[A],Drops[B],Drops[C]);
        if(!Patch.Soil)
        {
            const double Span=FMath::Max3(FVector::Dist2D(Patch.XY[A],Patch.XY[B]),FVector::Dist2D(Patch.XY[A],Patch.XY[C]),FVector::Dist2D(Patch.XY[B],Patch.XY[C]));
            const double Rise=FMath::Max3(Vertices[A].Z,Vertices[B].Z,Vertices[C].Z)-FMath::Min3(Vertices[A].Z,Vertices[B].Z,Vertices[C].Z);
            if(Rise>.3*Span)continue; // no asphalt painted vertically up a retaining edge
        }
        if(!Patch.Soil&&Drop>0)
        {
            const uint8 State=Drop>20?2:1;
            for(const auto& Pair:{FIntPoint(A,B),FIntPoint(B,C),FIntPoint(C,A)})
                Edges.FindOrAdd(FIntPoint(FMath::Min(Pair.X,Pair.Y),FMath::Max(Pair.X,Pair.Y)))|=State;
            if(State==2)continue;
        }
        (Patch.Soil&&Drop>.2?Broken:Intact).Append({A,B,C});
    }
    Mesh->ClearAllMeshSections();
    Mesh->CreateMeshSection_LinearColor(0,Vertices,Intact,Normals,UV,{}, {},Patch.Collision);
    if(!Broken.IsEmpty())Mesh->CreateMeshSection_LinearColor(1,Vertices,Broken,Normals,UV,{}, {},Patch.Collision);
    if(!Patch.Soil)
    {
        // Expose the asphalt course and its aggregate base along the broken
        // boundary. These are actual vertical faces with collision, not a
        // floating shader displacement across the whole event perimeter.
        for(int32 Layer=0;Layer<2;++Layer)
        {
            TArray<FVector> Faces,FaceNormals;TArray<FVector2D> Tex;TArray<int32> Indices;
            const double Top=Layer==0?0:20,Bottom=Layer==0?20:45;
            for(const auto& Edge:Edges)if(Edge.Value==3)
            {
                const FVector A=Vertices[Edge.Key.X]-FVector(0,0,Top),B=Vertices[Edge.Key.Y]-FVector(0,0,Top);
                const FVector Down(0,0,Top-Bottom);const int32 I=Faces.Num();
                const FVector Normal=FVector(B.Y-A.Y,A.X-B.X,0).GetSafeNormal();
                Faces.Append({A,B,A+Down,B+Down});FaceNormals.Append({Normal,Normal,Normal,Normal});
                Tex.Append({FVector2D(0,0),FVector2D((B-A).Size()/100,0),FVector2D(0,.25),FVector2D((B-A).Size()/100,.25)});
                // Both sides are visible when a thin asphalt edge overhangs
                // the failed subgrade; material normals remain well defined.
                Indices.Append({I,I+2,I+1,I+1,I+2,I+3,I+1,I+2,I,I+3,I+2,I+1});
            }
            if(!Faces.IsEmpty())Mesh->CreateMeshSection_LinearColor(2+Layer,Faces,Indices,FaceNormals,Tex,{}, {},Patch.Collision);
        }
    }
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
    const auto Profile=World->CityLayout->HasTypedField<EJson::Object>(TEXT("terrain"))?World->CityLayout->GetObjectField(TEXT("terrain")):nullptr;
    if(!Topography.Read(Profile))
    {UE_LOG(LogTemp,Error,TEXT("MR_TERRAIN invalid initial height blueprint"));return;}
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
    const double West=Topography.IsEnabled()?-12800.:-6400.;
    for(double X=West;X<Size+6400;X+=6400)for(double Y=-6400;Y<Size+6400;Y+=6400)
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

void FMRUrbanTerrain::BaseApron(FBox Bounds,UMaterialInterface* Material)
{
    const FVector Size=Bounds.GetSize();
    // A real two-metre asphalt transition replaces the old seven-centimetre
    // vertical slab edge. The collision triangles and visible edge agree.
    Grid(FVector(Bounds.Min.X,Bounds.Min.Y,0),FVector(Size.X,0,0),FVector(0,Size.Y,0),
        FMath::CeilToInt(Size.X/100),FMath::CeilToInt(Size.Y/100),7,Material,false,200);
}

bool FMRUrbanTerrain::Damage(const FMRDisturbance& Event)
{
    if(Cavities.ContainsByPredicate([&](const auto& C){return C.Id==Event.Id;}))return false;
    FMRRoadCavity Cavity;Cavity.Id=Event.Id;Cavity.Center=Event.Source;Cavity.Center.Z=InitialHeight(Event.Source);
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
    if(UrbanWater)UrbanWater->TerrainChanged(Cavity.Bounds());
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
                FVector(Rng.FRandRange(.9,1.7)),FString::Printf(TEXT("fragment_%d"),I%4));
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
double AMRWorld::InitialGroundHeightCm(FVector Position) const
{return UrbanTerrain?UrbanTerrain->InitialHeight(Position):0;}
