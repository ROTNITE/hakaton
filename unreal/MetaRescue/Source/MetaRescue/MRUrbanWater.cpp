#include "MRUrbanWater.h"
#include "MRWorld.h"
#include "MRAgent.h"
#include "MRUrbanTerrain.h"
#include "MRCoreJson.h"
#include "MRCoreValues.h"
#include "Engine/World.h"
#include "Materials/MaterialInterface.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "ProceduralMeshComponent.h"

using namespace MRCoreValues;

bool FMRUrbanWater::FFootprint::Contains(FVector P) const
{
    const double X=P.X-Center.X,Y=P.Y-Center.Y;
    return FMath::Abs(X*Cos+Y*Sin)<=Half.X&&FMath::Abs(-X*Sin+Y*Cos)<=Half.Y;
}

bool FMRUrbanWater::FFootprint::Intersects(FVector A,FVector B) const
{
    auto Local=[&](FVector P)
    {const double X=P.X-Center.X,Y=P.Y-Center.Y;return FVector(X*Cos+Y*Sin,-X*Sin+Y*Cos,0);};
    A=Local(A);B=Local(B);
    const FBox Box(FVector(-Half.X,-Half.Y,-1),FVector(Half.X,Half.Y,1));
    return Box.IsInsideOrOn(A)||Box.IsInsideOrOn(B)||FMath::LineBoxIntersection(Box,A,B,B-A);
}

FVector FMRUrbanWater::Center(int32 X,int32 Y) const
{return Origin+FVector((X+.5)*CellCm,(Y+.5)*CellCm,0);}
int32 FMRUrbanWater::At(FVector P) const
{return Hydro.Index(FMath::FloorToInt((P.X-Origin.X)/CellCm),FMath::FloorToInt((P.Y-Origin.Y)/CellCm));}
double FMRUrbanWater::GroundCm(FVector P) const
{return World->UrbanTerrain?World->UrbanTerrain->GroundHeight(P):0;}

bool FMRUrbanWater::Validate(const Object& Data,int32 GridSize)
{FMRUrbanWater Check(nullptr);return Check.ReadBlueprint(Data,GridSize);}

bool FMRUrbanWater::ReadBlueprint(const Object& Data,int32 GridSize)
{
    if(!Data)return false;
    if(Text(Data,TEXT("format"))!=TEXT("metarescue.hydrology.v1")||
       Text(Data,TEXT("boundary"))!=TEXT("river_fed_retention_basin"))return false;
    double CellM=0,WidthValue=0,HeightValue=0,Drain=0;
    const TArray<Value>* XY=nullptr;const Object* BasinData=nullptr;
    if(!Data->TryGetNumberField(TEXT("cell_m"),CellM)||CellM!=5||
       !Data->TryGetNumberField(TEXT("width"),WidthValue)||!Data->TryGetNumberField(TEXT("height"),HeightValue)||
       !FMath::IsFinite(WidthValue)||!FMath::IsFinite(HeightValue)||WidthValue<1||HeightValue<1||
       WidthValue>384||HeightValue>384||WidthValue!=FMath::FloorToDouble(WidthValue)||HeightValue!=FMath::FloorToDouble(HeightValue)||
       WidthValue*HeightValue>100000||!Data->TryGetArrayField(TEXT("origin_m"),XY)||XY->Num()!=2||
       (*XY)[0]->Type!=EJson::Number||(*XY)[1]->Type!=EJson::Number||
       !Data->TryGetObjectField(TEXT("basin"),BasinData)||
       !Data->TryGetNumberField(TEXT("initial_stage_m"),InitialStageM)||!FMath::IsFinite(InitialStageM)||
       !Data->TryGetNumberField(TEXT("storm_stage_m"),StormStageM)||!FMath::IsFinite(StormStageM)||
       !Data->TryGetNumberField(TEXT("rise_seconds"),RiseSeconds)||!FMath::IsFinite(RiseSeconds)||
       !Data->TryGetNumberField(TEXT("drain_capacity_m3_s"),Drain)||!FMath::IsFinite(Drain)||
       InitialStageM<0||InitialStageM>.2||StormStageM<=InitialStageM||StormStageM>3||RiseSeconds<30||RiseSeconds>300||Drain<0||Drain>1)return false;
    Origin=FVector((*XY)[0]->AsNumber()*100,(*XY)[1]->AsNumber()*100,0);CellCm=CellM*100;
    if(Origin.ContainsNaN()||Origin.X< -20000||Origin.Y< -20000||Origin.X>0||Origin.Y>0)return false;
    FVector Low,High;
    if(!MRCoreJson::Point(Field(*BasinData,TEXT("min")),Low)||!MRCoreJson::Point(Field(*BasinData,TEXT("max")),High)||
       Low.X>=High.X||Low.Y>=High.Y||Low.Z>=High.Z||Low.Z< -15||High.Z>1)return false;
    Basin=FBox(Low*100,High*100);
    OutletEdges.Empty();const TArray<Value>* Edges=nullptr;
    if(Data->HasField(TEXT("outlet_edges")))
    {
        if(!Data->TryGetArrayField(TEXT("outlet_edges"),Edges)||Edges->IsEmpty()||Edges->Num()>3||
           !Data->TryGetNumberField(TEXT("tailwater_stage_m"),TailwaterStageM)||!FMath::IsFinite(TailwaterStageM)||
           TailwaterStageM< -1||TailwaterStageM>InitialStageM)return false;
        for(const auto& Edge:*Edges)
        {
            if(Edge->Type!=EJson::String)return false;
            const FString Name=Edge->AsString();
            if((Name!=TEXT("east")&&Name!=TEXT("north")&&Name!=TEXT("south"))||OutletEdges.Contains(Name))return false;
            OutletEdges.Add(Name);
        }
    }
    const int32 Width=int32(WidthValue),Height=int32(HeightValue);
    if(Origin.X+Width*CellCm<GridSize*1000||Origin.Y+Height*CellCm<GridSize*1000)return false;
    if(Basin.Min.X<Origin.X||Basin.Min.Y<Origin.Y||Basin.Max.X>Origin.X+Width*CellCm||Basin.Max.Y>Origin.Y+Height*CellCm)return false;
    Columns=Width;Rows=Height;DrainCapacity=Drain;
    return true;
}

bool FMRUrbanWater::Build()
{
    if(!World->bDisasterCity||!Is(World->CityLayout,TEXT("hydrology"),EJson::Object))return false;
    const auto Data=World->CityLayout->GetObjectField(TEXT("hydrology"));
    if(!ReadBlueprint(Data,World->GridSize))return false;
    const int32 Width=Columns,Height=Rows;const double Drain=DrainCapacity,CellM=CellCm/100;
    for(const FString& Key:{TEXT("buildings"),TEXT("facilities"),TEXT("fixed_obstacles")})
        for(const auto& Value:World->CityLayout->GetArrayField(Key))
        {
            const auto Row=Value->AsObject(),Box=Row->GetObjectField(TEXT("bounds"));FVector Min,Max;
            MRCoreJson::Point(Field(Box,TEXT("min")),Min);MRCoreJson::Point(Field(Box,TEXT("max")),Max);
            FFootprint F;F.Bounds=FBox(Min*100,Max*100);F.Top=Max.Z*100;
            F.Center=FVector2D(F.Bounds.GetCenter());F.Half=FVector2D(F.Bounds.GetSize())*.5;
            if(Is(Row,TEXT("footprint"),EJson::Object))
            {
                const auto Shape=Row->GetObjectField(TEXT("footprint"));
                const auto& C=Shape->GetArrayField(TEXT("center"));const auto& H=Shape->GetArrayField(TEXT("half"));
                F.Center=FVector2D(C[0]->AsNumber(),C[1]->AsNumber())*100;
                F.Half=FVector2D(H[0]->AsNumber(),H[1]->AsNumber())*100;
                const double Yaw=FMath::DegreesToRadians(Shape->GetNumberField(TEXT("yaw")));F.Cos=FMath::Cos(Yaw);F.Sin=FMath::Sin(Yaw);
            }
            const int32 Id=Footprints.Add(F);
            for(int32 X=FMath::FloorToInt(F.Bounds.Min.X/3200);X<=FMath::FloorToInt(F.Bounds.Max.X/3200);++X)
                for(int32 Y=FMath::FloorToInt(F.Bounds.Min.Y/3200);Y<=FMath::FloorToInt(F.Bounds.Max.Y/3200);++Y)
                    FootprintBins.FindOrAdd(FIntPoint(X,Y)).Add(Id);
        }
    TArray<double> Bed,Water;TBitArray<> Solid(false,Width*Height);Bed.Reserve(Width*Height);Water.Reserve(Width*Height);
    for(int32 Y=0;Y<Height;++Y)for(int32 X=0;X<Width;++X)
    {
        const FVector P=Center(X,Y);const int32 I=Y*Width+X;
        if(const auto* Nearby=FootprintBins.Find(FIntPoint(FMath::FloorToInt(P.X/3200),FMath::FloorToInt(P.Y/3200))))
            for(int32 Id:*Nearby)if(Footprints[Id].Contains(P)){Solid[I]=true;break;}
        const double Z=GroundCm(P)/100;Bed.Add(Z);Water.Add(Basin.IsInsideXY(P)&&!Solid[I]?FMath::Max(0.,InitialStageM-Z):0);
    }
    if(!Hydro.Configure(Width,Height,CellM,Bed,Solid,Water))return false;
    VertexBeds.SetNum((Width+1)*(Height+1));
    for(int32 Y=0;Y<=Height;++Y)for(int32 X=0;X<=Width;++X)
        VertexBeds[Y*(Width+1)+X]=GroundCm(Origin+FVector(X*CellCm,Y*CellCm,0));
    InitialVertexBeds=VertexBeds;
    auto Crest=[&](FVector A,FVector B)
    {
        double Z=Basin.IsInsideXY(A)!=Basin.IsInsideXY(B)?Basin.Max.Z/100:-MAX_dbl;
        // Exact rotated wall intersections prevent a diagonal facade from
        // leaking through the gap between two exterior cell centres.
        const FVector M=(A+B)*.5;
        for(int32 BX=FMath::FloorToInt((M.X-CellCm)/3200);BX<=FMath::FloorToInt((M.X+CellCm)/3200);++BX)
            for(int32 BY=FMath::FloorToInt((M.Y-CellCm)/3200);BY<=FMath::FloorToInt((M.Y+CellCm)/3200);++BY)
                if(const auto* Nearby=FootprintBins.Find(FIntPoint(BX,BY)))
                    for(int32 Id:*Nearby)if(Footprints[Id].Intersects(A,B))Z=FMath::Max(Z,Footprints[Id].Top/100);
        return Z;
    };
    for(int32 Y=0;Y<Height;++Y)for(int32 X=0;X<Width;++X)
    {
        const FVector P=Center(X,Y);
        if(X+1<Width)Hydro.SetCrestX(X,Y,Crest(P,Center(X+1,Y)),true);
        if(Y+1<Height)Hydro.SetCrestY(X,Y,Crest(P,Center(X,Y+1)),true);
        if(Basin.IsInsideXY(P)&&P.X<Basin.Min.X+1000&&P.Y>Basin.Min.Y+500&&P.Y<Basin.Max.Y-500)Sources.Add(Y*Width+X);
        if(!Solid[Y*Width+X]&&((X==Width-1&&OutletEdges.Contains(TEXT("east")))||
            (Y==Height-1&&OutletEdges.Contains(TEXT("north")))||(Y==0&&OutletEdges.Contains(TEXT("south")))))Outlets.Add(Y*Width+X);
    }
    for(const auto& Value:World->CityLayout->GetObjectField(TEXT("road_graph"))->GetArrayField(TEXT("nodes")))
    {
        FVector P;MRCoreJson::Point(Field(Value->AsObject(),TEXT("position")),P);Hydro.SetDrain(At(P*100),Drain);
    }
    for(int32 Y=0;Y<Height;Y+=16)for(int32 X=0;X<Width;X+=16)Tiles.Add({X,Y,{}});
    LastTime=0;Render();
    UE_LOG(LogTemp,Display,TEXT("MR_HYDROLOGY built %dx%d cell_m=%.1f source_cells=%d volume_m3=%.3f"),Width,Height,CellM,Sources.Num(),Hydro.VolumeM3());
    return Sources.Num()>0;
}

void FMRUrbanWater::Reset()
{
    Hydro.Reset();LastTime=0;History.Empty();VertexBeds=InitialVertexBeds;
    // Configure owns initial geometry/crests. Drains are runtime controls and
    // must be reattached after Reset clears them.
    const double Drain=World->CityLayout->GetObjectField(TEXT("hydrology"))->GetNumberField(TEXT("drain_capacity_m3_s"));
    for(const auto& Value:World->CityLayout->GetObjectField(TEXT("road_graph"))->GetArrayField(TEXT("nodes")))
    {FVector P;MRCoreJson::Point(Field(Value->AsObject(),TEXT("position")),P);Hydro.SetDrain(At(P*100),Drain);}
    Render();
}

double FMRUrbanWater::ForcingStage(double AtTime) const
{
    double Stage=InitialStageM;
    for(const auto& Event:World->Environment.Applied)
        if(Event.Kind==EMRDisturbance::Flood&&!Event.bPropagation)
        {
            const double Age=AtTime-Event.Time;
            if(Age>=0)Stage=FMath::Max(Stage,InitialStageM+(StormStageM-InitialStageM)*FMath::Clamp(Age/RiseSeconds,0.,1.));
        }
    return Stage;
}

bool FMRUrbanWater::AdvanceTo(double ModelSeconds)
{
    bool Changed=false;
    while(LastTime+.1<=ModelSeconds+1.e-9)
    {
        const double Stage=ForcingStage(LastTime+.1);
        for(int32 I:Sources)if(!Hydro.SetBoundaryStage(I,Stage))return false;
        for(int32 I:Outlets)if(!Hydro.SetBoundaryStage(I,TailwaterStageM))return false;
        if(!Hydro.Advance(.1))return false;
        LastTime+=.1;Changed=true;
    }
    if(Changed)Render();return Hydro.IsHealthy();
}

double FMRUrbanWater::VertexStageCm(int32 X,int32 Y) const
{
    double Sum=0;int32 Count=0;
    for(int32 DY=-1;DY<=0;++DY)for(int32 DX=-1;DX<=0;++DX)
    {const int32 I=Hydro.Index(X+DX,Y+DY);if(I!=INDEX_NONE&&Hydro.DepthM(I)>.001){Sum+=Hydro.StageM(I);++Count;}}
    return Count?100*Sum/Count:VertexBeds[Y*(Hydro.GetWidth()+1)+X];
}

FVector FMRUrbanWater::VertexCurrentCm(int32 X,int32 Y) const
{
    FVector Sum=FVector::ZeroVector;int32 Count=0;
    for(int32 DY=-1;DY<=0;++DY)for(int32 DX=-1;DX<=0;++DX)
    {const int32 I=Hydro.Index(X+DX,Y+DY);if(I!=INDEX_NONE&&Hydro.DepthM(I)>.02){Sum+=Hydro.CurrentMPerSecond(I)*100;++Count;}}
    return Count?Sum/Count:FVector::ZeroVector;
}

FMRWaterSample FMRUrbanWater::Sample(FVector P) const
{
    FMRWaterSample Result;const int32 I=At(P);if(I==INDEX_NONE)return Result;
    Result.InDomain=true;Result.GroundCm=GroundCm(P);Result.StageCm=Result.GroundCm;
    if(Hydro.DepthM(I)<=.001)return Result;
    const int32 X=I%Hydro.GetWidth(),Y=I/Hydro.GetWidth();
    const double U=(P.X-Origin.X)/CellCm-X,V=(P.Y-Origin.Y)/CellCm-Y;
    const double A=VertexStageCm(X,Y),B=VertexStageCm(X+1,Y),C=VertexStageCm(X+1,Y+1),D=VertexStageCm(X,Y+1);
    // Match the mesh's A-C diagonal, rather than a different bilinear surface.
    Result.StageCm=U>=V?A*(1-U)+B*(U-V)+C*V:A*(1-V)+C*U+D*(V-U);
    Result.DepthCm=FMath::Max(0.,Result.StageCm-Result.GroundCm);
    if(Result.DepthCm>.1)Result.CurrentCmPerSecond=Hydro.CurrentMPerSecond(I)*100;
    return Result;
}

bool FMRUrbanWater::HasHistory(FIntPoint Cell) const
{return History.Contains(Cell);}

void FMRUrbanWater::TerrainChanged(FBox Bounds)
{
    const int32 X0=FMath::Max(0,FMath::FloorToInt((Bounds.Min.X-Origin.X)/CellCm)),Y0=FMath::Max(0,FMath::FloorToInt((Bounds.Min.Y-Origin.Y)/CellCm));
    const int32 X1=FMath::Min(Hydro.GetWidth()-1,FMath::FloorToInt((Bounds.Max.X-Origin.X)/CellCm)),Y1=FMath::Min(Hydro.GetHeight()-1,FMath::FloorToInt((Bounds.Max.Y-Origin.Y)/CellCm));
    for(int32 Y=Y0;Y<=Y1;++Y)for(int32 X=X0;X<=X1;++X)Hydro.SetBed(Hydro.Index(X,Y),GroundCm(Center(X,Y))/100);
    for(int32 Y=Y0;Y<=FMath::Min(Hydro.GetHeight(),Y1+1);++Y)for(int32 X=X0;X<=FMath::Min(Hydro.GetWidth(),X1+1);++X)
        VertexBeds[Y*(Hydro.GetWidth()+1)+X]=GroundCm(Origin+FVector(X*CellCm,Y*CellCm,0));
    Render();
}

void FMRUrbanWater::Render()
{
    if(auto* Material=WaterMaterial.Get())Material->SetScalarParameterValue(TEXT("ModelTime"),LastTime);
    for(auto& Tile:Tiles)
    {
        const int32 W=FMath::Min(16,Hydro.GetWidth()-Tile.X),H=FMath::Min(16,Hydro.GetHeight()-Tile.Y);
        TArray<int32> Triangles;
        for(int32 Y=0;Y<H;++Y)for(int32 X=0;X<W;++X)
        {
            const int32 I=Hydro.Index(Tile.X+X,Tile.Y+Y);if(Hydro.DepthM(I)<=.001)continue;
            const int32 A=Y*(W+1)+X;Triangles.Append({A,A+W+2,A+1,A,A+W+1,A+W+2});
            const FVector P=Center(Tile.X+X,Tile.Y+Y);History.Add(FMRDistrictEnvironment::Cell(P));
        }
        auto* Mesh=Tile.Mesh.Get();if(Triangles.IsEmpty()){if(Mesh)Mesh->ClearAllMeshSections();continue;}
        if(!Mesh)
        {
            Mesh=NewObject<UProceduralMeshComponent>(World);World->AddInstanceComponent(Mesh);Mesh->SetupAttachment(World->GetRootComponent());
            Mesh->SetMobility(EComponentMobility::Movable);Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
            Mesh->SetCastShadow(false);Mesh->SetAffectDistanceFieldLighting(false);Mesh->ComponentTags={TEXT("UrbanFlood")};
            auto* Material=WaterMaterial.Get();
            if(!Material)
            {
                Material=UMaterialInstanceDynamic::Create(LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/EffectsV3/Revision5/M_UrbanFlood.M_UrbanFlood")),World);
                WaterMaterial=Material;if(Material)Material->SetScalarParameterValue(TEXT("ModelTime"),LastTime);
            }
            Mesh->SetMaterial(0,Material);
            Mesh->RegisterComponent();World->Generated.Add(Mesh);Tile.Mesh=Mesh;
        }
        const FVector TileOrigin=Origin+FVector(Tile.X*CellCm,Tile.Y*CellCm,0);Mesh->SetWorldLocation(TileOrigin);
        TArray<FVector> Vertices,Normals;TArray<FVector2D> UV;TArray<FLinearColor> Colors;
        for(int32 Y=0;Y<=H;++Y)for(int32 X=0;X<=W;++X)
        {
            const int32 VX=Tile.X+X,VY=Tile.Y+Y;
            const double Stage=VertexStageCm(VX,VY);const FVector Flow=VertexCurrentCm(VX,VY);
            Vertices.Add(FVector(X*CellCm,Y*CellCm,Stage));Normals.Add(FVector::UpVector);
            const double Depth=FMath::Max(0.,Stage-VertexBeds[VY*(Hydro.GetWidth()+1)+VX]);
            Colors.Emplace(float((128+FMath::Clamp(Flow.X/800.,-1.,1.)*127)/255.),
                float((128+FMath::Clamp(Flow.Y/800.,-1.,1.)*127)/255.),float(FMath::Clamp(Depth/400.,0.,1.)),1.f);
            UV.Add(FVector2D((Tile.X+X)*CellCm,(Tile.Y+Y)*CellCm)/500.);
        }
        Mesh->CreateMeshSection_LinearColor(0,Vertices,Triangles,Normals,UV,Colors, {},false);
    }
}

TOptional<double> FMRUrbanWater::RenderedHeightCm(FVector P) const
{
    // Read the actual procedural section buffers, independently of the
    // sampler's interpolation. This is private verification, never a sensor.
    for(const auto& Tile:Tiles)
    {
        auto* Mesh=Tile.Mesh.Get();if(!Mesh||!Mesh->Bounds.GetBox().IsInsideXY(P))continue;
        const auto* Section=Mesh->GetProcMeshSection(0);if(!Section)continue;
        for(int32 I=0;I<Section->ProcIndexBuffer.Num();I+=3)
        {
            FVector V[3];for(int32 K=0;K<3;++K)V[K]=Mesh->GetComponentTransform().TransformPosition(Section->ProcVertexBuffer[Section->ProcIndexBuffer[I+K]].Position);
            const double DX1=V[1].X-V[0].X,DY1=V[1].Y-V[0].Y,DX2=V[2].X-V[0].X,DY2=V[2].Y-V[0].Y;
            const double Den=DX1*DY2-DY1*DX2;if(FMath::Abs(Den)<1.e-9)continue;
            const double U=((P.X-V[0].X)*DY2-(P.Y-V[0].Y)*DX2)/Den;
            const double W=(DX1*(P.Y-V[0].Y)-DY1*(P.X-V[0].X))/Den;
            if(U>=-1.e-8&&W>=-1.e-8&&U+W<=1+1.e-8)return V[0].Z*(1-U-W)+V[1].Z*U+V[2].Z*W;
        }
    }
    return {};
}

Object FMRUrbanWater::PrivateSnapshot() const
{
    TArray<Value> Samples;double Maximum=0,CityMaximum=0;int32 Wet=0,CityWet=0;
    for(int32 I=0;I<Hydro.GetWidth()*Hydro.GetHeight();++I)
    {
        Maximum=FMath::Max(Maximum,Hydro.DepthM(I));Wet+=Hydro.DepthM(I)>.001;
        const FVector P=Center(I%Hydro.GetWidth(),I/Hydro.GetWidth());
        if(P.X>=0){CityMaximum=FMath::Max(CityMaximum,Hydro.DepthM(I));CityWet+=Hydro.DepthM(I)>.001;}
    }
    FCollisionQueryParams Query(SCENE_QUERY_STAT(MRHydraulicBedVerification),false);
    for(AMRAgent* Agent:World->Agents)Query.AddIgnoredActor(Agent);
    for(FVector P:{FVector(-8100,4300,0),FVector(500,7000,0),FVector(1000,10000,0),
                   World->Base-FVector(0,370,0),FVector(9350,1000,0),FVector(5000,1000,0)})
    {
        const auto S=Sample(P);const auto Surface=RenderedHeightCm(P);FHitResult Hit;
        const bool Found=World->GetWorld()->LineTraceSingleByChannel(Hit,P+FVector(0,0,1000),P-FVector(0,0,2000),ECC_Visibility,Query);
        Samples.Add(Json(Obj({{TEXT("position_m"),Point(P/100)},
            {TEXT("depth_m"),Num(S.DepthCm/100)},{TEXT("stage_m"),Num(S.StageCm/100)},
            {TEXT("bed_m"),Num(S.GroundCm/100)},{TEXT("current_m_s"),Point(S.CurrentCmPerSecond/100)},
            {TEXT("water_surface_buffer_m"),Surface.IsSet()?Num(Surface.GetValue()/100):Null()},
            {TEXT("physical_ground_m"),Found?Num(Hit.ImpactPoint.Z/100):Null()},
            {TEXT("physical_ground_component"),Found?Str(GetNameSafe(Hit.GetComponent())):Null()}})));
    }
    return Obj({{TEXT("format"),Str(TEXT("metarescue.hydrology-state.v1"))},{TEXT("time_s"),Num(LastTime)},
        {TEXT("volume_m3"),Num(Hydro.VolumeM3())},{TEXT("inflow_m3"),Num(Hydro.AddedM3())},
        {TEXT("open_outlet_cells"),Num(Outlets.Num())},{TEXT("tailwater_stage_m"),Num(TailwaterStageM)},
        {TEXT("outflow_and_drain_m3"),Num(Hydro.RemovedM3())},{TEXT("balance_error_m3"),Num(Hydro.BalanceErrorM3())},
        {TEXT("healthy"),Bool(Hydro.IsHealthy())},{TEXT("wet_cells"),Num(Wet)},{TEXT("maximum_depth_m"),Num(Maximum)},
        {TEXT("flooded_city_cells"),Num(CityWet)},{TEXT("city_max_depth_m"),Num(CityMaximum)},
        {TEXT("samples"),Arr(Samples)}});
}

bool AMRWorld::BuildUrbanWater()
{
    UrbanWater.Reset();
    if(!bDisasterCity||!CityLayout->HasField(TEXT("hydrology")))return true;
    UrbanWater=MakeShared<FMRUrbanWater>(this);
    if(UrbanWater->Build())return true;
    UrbanWater.Reset();return false;
}
bool AMRWorld::TickUrbanWater(double ModelSeconds)
{return !UrbanWater||UrbanWater->AdvanceTo(ModelSeconds);}
void AMRWorld::ResetUrbanWater()
{if(UrbanWater)UrbanWater->Reset();}
FMRWaterSample AMRWorld::WaterAtCm(FVector P) const
{return UrbanWater?UrbanWater->Sample(P):FMRWaterSample();}
