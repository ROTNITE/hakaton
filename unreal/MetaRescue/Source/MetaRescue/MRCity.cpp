#include "MRWorld.h"
#include "MRBuildingWindows.h"
#include "MRCityAssets.h"
#include "MRCoreJson.h"
#include "MRCoreValues.h"
#include "Components/BoxComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/HierarchicalInstancedStaticMeshComponent.h"
#include "Engine/DirectionalLight.h"
#include "Engine/ExponentialHeightFog.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/SkyLight.h"
#include "EngineUtils.h"
#include "HAL/PlatformTime.h"
#include "Engine/StaticMesh.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Misc/FileHelper.h"
#include "Materials/MaterialInterface.h"
#include "Misc/App.h"
#include "ProceduralMeshComponent.h"

namespace
{
FVector CityPoint(const TArray<TSharedPtr<FJsonValue>>& A)
{return FVector(A[0]->AsNumber(),A[1]->AsNumber(),A[2]->AsNumber())*100;}
FBox CityBox(const TSharedPtr<FJsonObject>& J)
{return FBox(CityPoint(J->GetArrayField(TEXT("min"))),CityPoint(J->GetArrayField(TEXT("max"))));}
TSharedPtr<FJsonValue> CityValue(const TSharedPtr<FJsonObject>& J)
{return MakeShared<FJsonValueObject>(J);}
TSharedPtr<FJsonValue> CityXY(FVector P)
{return MakeShared<FJsonValueArray>(TArray<TSharedPtr<FJsonValue>>{MakeShared<FJsonValueNumber>(P.X/1000),MakeShared<FJsonValueNumber>(P.Y/1000)});}

UMaterialInterface* CityYardMaterial(const FString& Name)
{
    const FString Path=TEXT("/Game/RescueAssets/CityV2/SurfacesR4/")+Name+TEXT(".")+Name;
    return LoadObject<UMaterialInterface>(nullptr,*Path);
}

struct FCityCoverMesh
{
    TArray<FVector> Vertices,Normals;
    TArray<FVector2D> UV;
    TArray<int32> Triangles;
};
}

bool AMRWorld::ReadCityLayout(const FString& File)
{
    FString Text;
    if(!FFileHelper::LoadFileToString(Text,*File)||!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),CityLayout)||!CityLayout)
    {UE_LOG(LogTemp,Error,TEXT("MR_CITY invalid layout file"));return false;}
    const FString Format=CityLayout->GetStringField(TEXT("format"));
    bCityProps=Format==TEXT("rescue-city-2.2");
    bDecoratedCity=bCityProps||Format==TEXT("rescue-city-2.1");
    bIrregularCity=bDecoratedCity||Format==TEXT("rescue-city-2.0");
    if(!CityLayout->HasTypedField<EJson::Object>(TEXT("settings"))||
       (!bIrregularCity&&Format!=TEXT("rescue-city-1.0")&&Format!=TEXT("rescue-city-1.1"))||
       !CityLayout->HasTypedField<EJson::Object>(TEXT("preflight"))||
       !CityLayout->GetObjectField(TEXT("preflight"))->GetBoolField(TEXT("passed")))return false;
    auto Settings=CityLayout->GetObjectField(TEXT("settings"));GridSize=Settings->GetIntegerField(TEXT("map_size"));
    if(GridSize<25||GridSize>150)return false;
    if(bIrregularCity)
    {
        using namespace MRCoreValues;
        if(!Is(CityLayout,TEXT("road_graph"),EJson::Object)||!Is(CityLayout,TEXT("background"),EJson::Array))return false;
        const auto Roads=CityLayout->GetObjectField(TEXT("road_graph"));
        if(MRCoreValues::Text(Roads,TEXT("format"))!=TEXT("metarescue.street-graph.v2")||!Is(Roads,TEXT("nodes"),EJson::Array)||
           !Is(Roads,TEXT("edges"),EJson::Array)||!Is(Roads,TEXT("entrances"),EJson::Array))return false;
        const auto& Nodes=Roads->GetArrayField(TEXT("nodes"));const auto& Edges=Roads->GetArrayField(TEXT("edges"));
        if(Nodes.Num()<4||Nodes.Num()>15000||Edges.Num()<4||Edges.Num()>30000)return false;
        TSet<FString> Names;
        for(const auto& Value:Nodes)
        {
            if(Value->Type!=EJson::Object)return false;
            const auto Node=Value->AsObject();const FString Id=MRCoreValues::Text(Node,TEXT("id"));FVector P;
            if(Id.IsEmpty()||Names.Contains(Id)||!MRCoreJson::Point(Field(Node,TEXT("position")),P)||
               P.X<0||P.Y<0||P.X>GridSize*10||P.Y>GridSize*10||P.Z!=0)return false;
            Names.Add(Id);
        }
        for(const auto& Value:Edges)
        {
            if(Value->Type!=EJson::Object)return false;
            const auto Edge=Value->AsObject();const FString U=MRCoreValues::Text(Edge,TEXT("from")),V=MRCoreValues::Text(Edge,TEXT("to"));
            if(!Names.Contains(U)||!Names.Contains(V)||U==V||!Is(Edge,TEXT("width_m"),EJson::Number))return false;
            const double Width=Edge->GetNumberField(TEXT("width_m"));if(Width<4.8||Width>14)return false;
        }
        const auto& Gates=Roads->GetArrayField(TEXT("entrances"));
        if(Gates.Num()!=4)return false;
        for(const auto& Value:Gates)
        {
            if(Value->Type!=EJson::Object)return false;
            const auto Gate=Value->AsObject();
            if(!Names.Contains(MRCoreValues::Text(Gate,TEXT("node_id")))||!Is(Gate,TEXT("outward"),EJson::Array))return false;
            const auto& Direction=Gate->GetArrayField(TEXT("outward"));
            if(Direction.Num()!=2||Direction[0]->Type!=EJson::Number||Direction[1]->Type!=EJson::Number||
               FMath::Abs(Direction[0]->AsNumber())+FMath::Abs(Direction[1]->AsNumber())!=1)return false;
        }
        if(bDecoratedCity)
        {
            CityVegetationRevision=1;
            CityLayout->TryGetNumberField(TEXT("vegetation_revision"),CityVegetationRevision);
            if(CityVegetationRevision<1||CityVegetationRevision>3)return false;
            if(!Is(CityLayout,TEXT("lot_covers"),EJson::Array)||!Is(CityLayout,TEXT("features"),EJson::Array))return false;
            for(const auto& Entry:CityLayout->GetArrayField(TEXT("features")))
            {
                if(Entry->Type!=EJson::Object)return false;
                const auto Feature=Entry->AsObject();
                const FString Kind=MRCoreValues::Text(Feature,TEXT("kind")),Id=MRCoreValues::Text(Feature,TEXT("asset_id"));
                if(Kind==TEXT("vegetation")&&!MRCityVegetation(Id,CityVegetationRevision))
                {UE_LOG(LogTemp,Error,TEXT("MR_CITY missing vegetation %s"),*Id);return false;}
                if(Kind==TEXT("parked_vehicle")&&bCityProps)
                {
                    if(!MRCityProp(Id)){UE_LOG(LogTemp,Error,TEXT("MR_CITY missing prop %s"),*Id);return false;}
                }
                else if(Kind!=TEXT("vegetation")&&(Kind!=TEXT("shelter")||Id!=TEXT("utility_shelter")))return false;
            }
            for(const FString& Material:{TEXT("M_Yard"),TEXT("M_Lawn"),TEXT("M_Service"),TEXT("M_Verge")})
                if(!CityYardMaterial(Material)){UE_LOG(LogTemp,Error,TEXT("MR_CITY missing yard material %s"),*Material);return false;}
        }
    }
    if(!ValidateCompetitionLayout())return false;
    Seed=Settings->GetIntegerField(TEXT("seed"));Base=CityPoint(CityLayout->GetArrayField(TEXT("base_position")));
    Scenario=MakeShared<FJsonObject>();Scenario->SetNumberField(TEXT("width"),GridSize);Scenario->SetNumberField(TEXT("seed"),Seed);
    Scenario->SetNumberField(TEXT("scouts"),Settings->GetIntegerField(TEXT("scouts")));
    Scenario->SetNumberField(TEXT("rescuers"),Settings->GetIntegerField(TEXT("rescuers")));
    Scenario->SetNumberField(TEXT("ground_battery_Wh"),240);
    Scenario->SetArrayField(TEXT("base"),CityXY(Base)->AsArray());
    Grid.Empty();for(int32 I=0;I<GridSize;I++){TArray<int32> Row;Row.Init(0,GridSize);Grid.Add(Row);}
    TArray<TSharedPtr<FJsonValue>> People;
    for(const auto& Entry:CityLayout->GetArrayField(TEXT("people")))
    {
        auto Input=Entry->AsObject();auto Person=MakeShared<FJsonObject>();const FVector P=CityPoint(Input->GetArrayField(TEXT("position")));
        Person->SetNumberField(TEXT("id"),Input->GetIntegerField(TEXT("id")));
        Person->SetNumberField(TEXT("x"),P.X/1000);Person->SetNumberField(TEXT("y"),P.Y/1000);
        Person->SetNumberField(TEXT("priority"),Input->GetNumberField(TEXT("priority"))/3.);
        Person->SetNumberField(TEXT("available_at"),Input->GetNumberField(TEXT("available_at")));
        Person->SetArrayField(TEXT("path"),{});People.Add(CityValue(Person));
    }
    Scenario->SetArrayField(TEXT("people"),People);Scenario->SetArrayField(TEXT("scout_waypoints"),{});
    bCityLayout=true;return true;
}

void AMRWorld::BuildCity()
{
    if(!MRCityAssetsReady())
    {UE_LOG(LogTemp,Error,TEXT("MR_CITY prepare_city_assets.py must succeed before city launch"));return;}
    bBuildingCity=true;
    const double BuildStarted=FPlatformTime::Seconds();
    CitySurfaceIndex.Empty();const float Size=CityLayout->GetNumberField(TEXT("size_m"))*100;
    const FBox BaseBox=CityBox(CityLayout->GetObjectField(TEXT("base")));
    const float RoadWidth=bIrregularCity?0:CityLayout->GetNumberField(TEXT("road_width_m"))*100;
    // The union and support height stay the same. Bounded tiles avoid one
    // enormous, thin, non-uniform Nanite primitive spanning the whole city.
    for(float X=-6000;X<Size+6000;X+=4000)for(float Y=-6000;Y<Size+6000;Y+=4000)
    {
        const float W=FMath::Min(4000.f,Size+6000-X),H=FMath::Min(4000.f,Size+6000-Y);
        auto* Ground=Shape("Cube",FVector(X+W/2,Y+H/2,-22),FVector(W,H,44),"City_Soil");
        if(bDecoratedCity)Ground->SetMaterial(0,CityYardMaterial(TEXT("M_Verge")));
    }
    if(bDecoratedCity)BuildCityYards();
    BuildCompetitionAnnex();
    TArray<float> Axes;
    if(bIrregularCity)BuildIrregularStreets(BaseBox);
    else for(const auto& V:CityLayout->GetArrayField(TEXT("road_axes_m")))Axes.Add(V->AsNumber()*100);
    for(float Axis:Axes)
    {
        for(float From=-4000;From<Size+4000;From+=2000)
        {
            const float Length=FMath::Min(2000.f,Size+4000-From);
            Shape("Cube",FVector(Axis,From+Length/2,-2),FVector(RoadWidth,Length,12),"M_QuarterAsphalt");
        }
        float Start=-4000;
        for(int32 I=0;I<=Axes.Num();I++)
        {
            const float End=I<Axes.Num()?Axes[I]-RoadWidth/2:Size+4000;
            for(float From=Start;From<End;From+=2000)
            {
                const float Length=FMath::Min(2000.f,End-From);
                Shape("Cube",FVector(From+Length/2,Axis,-2),FVector(Length,RoadWidth,12),"M_QuarterAsphalt");
            }
            if(I<Axes.Num())Start=Axes[I]+RoadWidth/2;
        }
        for(float Along=0;Along<Size;Along+=400)
        {
            bool Crossing=false;for(float Cross:Axes)Crossing|=FMath::Abs(Along-Cross)<600;
            if(Crossing)continue;
            for(bool Vertical:{true,false})
            {
                const FVector P=Vertical?FVector(Axis,Along,7):FVector(Along,Axis,7);
                if(!BaseBox.IsInsideXY(P))Shape("Cube",P,Vertical?FVector(9,170,2):FVector(170,9,2),"MI_Paint",FRotator::ZeroRotator,false);
            }
        }
    }
    for(int32 X=0;X+1<Axes.Num();X++)for(int32 Y=0;Y+1<Axes.Num();Y++)
    {
        const float X0=Axes[X]+500,X1=Axes[X+1]-500,Y0=Axes[Y]+500,Y1=Axes[Y+1]-500;
        auto Pave=[&](float A,float B,float C,float D)
        {if(B>A&&D>C)Shape("Cube",FVector((A+B)/2,(C+D)/2,8),FVector(B-A,D-C,30),"M_QuarterPaving");};
        const float CutX0=FMath::Max(X0,float(BaseBox.Min.X)),CutX1=FMath::Min(X1,float(BaseBox.Max.X));
        const float CutY0=FMath::Max(Y0,float(BaseBox.Min.Y)),CutY1=FMath::Min(Y1,float(BaseBox.Max.Y));
        if(CutX1<=CutX0||CutY1<=CutY0)Pave(X0,X1,Y0,Y1);
        else
        {
            Pave(X0,CutX0,Y0,Y1);Pave(CutX1,X1,Y0,Y1);
            Pave(CutX0,CutX1,Y0,CutY0);Pave(CutX0,CutX1,CutY1,Y1);
        }
    }
    int32 Count=0;
    for(const auto& Value:CityLayout->GetArrayField(TEXT("buildings")))
    {
        auto J=Value->AsObject();FVector P=CityPoint(J->GetArrayField(TEXT("position")));P.Z+=bIrregularCity?0:23;
        // Native apartment models keep their metre scale. Facade orientation is
        // symmetric; the selected variant controls actual structural damage.
        const int32 Begin=Generated.Num();Apartment(P,J->GetIntegerField(TEXT("floors")),Count+17,J->GetIntegerField(TEXT("variant")));
        const FQuat Turn(FVector::UpVector,FMath::DegreesToRadians(J->GetNumberField(TEXT("yaw"))));
        for(int32 I=Begin;I<Generated.Num();I++)if(auto* C=Generated[I].Get())if(C->GetAttachParent()==GetRootComponent())
        {C->SetRelativeLocation(P+Turn.RotateVector(C->GetRelativeLocation()-P));C->SetRelativeRotation(Turn*C->GetRelativeRotation().Quaternion());}
        if(bCityProps)
        {
            const auto& Frontage=J->GetArrayField(TEXT("street_source"));
            const FVector DoorWalk(Frontage[0]->AsNumber()*100,Frontage[1]->AsNumber()*100,0);
            const FVector Direction=(DoorWalk-P).GetSafeNormal2D();
            const FVector Threshold=P+Direction*446;
            const double Length=FVector::Dist2D(Threshold,DoorWalk);
            if(Length>5&&Length<1600)
                Shape("Cube",(Threshold+DoorWalk)*.5+FVector(0,0,.7),FVector(Length,186,.4),
                      "M_QuarterPaving",Direction.Rotation(),false);
        }
        if(++Count%32==0)OptimizeDistrictInstances();
    }
    // Background is outside mission bounds. Four street continuations and an
    // inhabited edge replace the empty horizon, without scaling house models.
    if(bIrregularCity&&!CityLayout->HasTypedField<EJson::Number>(TEXT("background_revision")))
    {
        for(const auto& Entry:CityLayout->GetArrayField(TEXT("background")))
        {
            const auto House=Entry->AsObject();const FVector P=CityPoint(House->GetArrayField(TEXT("position")));
            const int32 Begin=Generated.Num();Apartment(P,House->GetIntegerField(TEXT("floors")),Count,House->GetIntegerField(TEXT("variant")));
            const FQuat Turn(FVector::UpVector,FMath::DegreesToRadians(House->GetNumberField(TEXT("yaw"))));
            for(int32 I=Begin;I<Generated.Num();++I)if(auto* C=Generated[I].Get())if(C->GetAttachParent()==GetRootComponent())
            {C->SetRelativeLocation(P+Turn.RotateVector(C->GetRelativeLocation()-P));C->SetRelativeRotation(Turn*C->GetRelativeRotation().Quaternion());}
            if(++Count%32==0)OptimizeDistrictInstances();
        }
    }
    else if(!bIrregularCity)for(float Along=2500;Along<Size-1000;Along+=2400)
    {
        bool Crossing=false;for(float Cross:Axes)Crossing|=FMath::Abs(Along-Cross)<1000;
        if(Crossing)continue;
        for(int32 Side=0;Side<4;Side++)
        {
            const FVector P=Side==0?FVector(Along,-2500,0):Side==1?FVector(Along,Size+2500,0):
                Side==2?FVector(-2500,Along,0):FVector(Size+2500,Along,0);
            Apartment(P,3+(Count%2),Count,Count%6);Count++;
        }
        OptimizeDistrictInstances();
    }
    BuildCityHorizon();
    for(const auto& Entry:CityLayout->GetArrayField(TEXT("features")))
    {
        auto J=Entry->AsObject();const FVector P=CityPoint(J->GetArrayField(TEXT("position")));
        if(bDecoratedCity){BuildCityFeature(J);continue;}
        if(J->HasTypedField<EJson::Number>(TEXT("model")))
        {
            auto* Mesh=MRCityFoliage(J->GetIntegerField(TEXT("model")));
            if(!Mesh){UE_LOG(LogTemp,Error,TEXT("MR_CITY missing authored foliage"));continue;}
            auto* C=NewObject<UStaticMeshComponent>(this);AddInstanceComponent(C);C->SetupAttachment(GetRootComponent());
            C->SetMobility(EComponentMobility::Movable);C->ComponentTags.Add(TEXT("CityStaticPending"));C->SetStaticMesh(Mesh);
            for(int32 I=0;I<C->GetNumMaterials();I++)C->SetMaterial(I,MRCityMaterial(C->GetMaterial(I)));
            C->SetRelativeLocation(P);C->SetRelativeRotation(FRotator(0,J->GetNumberField(TEXT("yaw")),0));
            C->SetCollisionProfileName(TEXT("BlockAll"));Generated.Add(C);continue;
        }
        // Historical city 1.0 recordings retain their declared primitive trees.
        const float Height=J->GetNumberField(TEXT("height_m"))*100;
        Shape("Cylinder",P+FVector(0,0,200),FVector(48,48,400),"City_Bark");
        Shape("Cone",P+FVector(0,0,Height*.62),FVector(440,440,Height*.7),"City_Leaves",FRotator::ZeroRotator,false);
        Shape("Cone",P+FVector(0,0,Height*.8),FVector(300,300,Height*.4),"City_Leaves",FRotator::ZeroRotator,false);
    }
    for(const auto& Entry:CityLayout->GetArrayField(TEXT("parcels")))
    {
        auto J=Entry->AsObject();const FVector P=CityPoint(J->GetArrayField(TEXT("position")))+FVector(0,0,bIrregularCity?1:24);
        const FString Use=J->GetStringField(TEXT("use"));
        if(Use==TEXT("courtyard"))DistrictAssembly("SceneryKit",P+FVector(bIrregularCity?-200:-500,0,0),FRotator::ZeroRotator,FVector::OneVector,!bIrregularCity,false,"courtyard_bench");
        else if(Use==TEXT("service"))DistrictAssembly("SceneryKit",P,FRotator::ZeroRotator,FVector::OneVector,!bIrregularCity,false,"service_bins");
    }
    Shape("Cube",FVector(BaseBox.GetCenter().X,BaseBox.GetCenter().Y,bIrregularCity?-3:1),FVector(BaseBox.GetSize().X,BaseBox.GetSize().Y,20),"M_QuarterAsphalt");
    const bool DeclaredBase=CityLayout->HasTypedField<EJson::Number>(TEXT("base_layout_revision"))&&
        CityLayout->GetIntegerField(TEXT("base_layout_revision"))>=3;
    if(!DeclaredBase)DistrictMesh("Medical",Base+FVector(0,0,13));
    DistrictLabel("MEDICAL / RESCUE BASE",Base+FVector(0,-350,350),45);
    if(bDecoratedCity||DeclaredBase)
    {
        // Separate service lane to the west of patient transfer and fleet exits.
        for(const auto& Entry:CityLayout->GetArrayField(TEXT("fixed_obstacles")))
        {
            const auto Fixture=Entry->AsObject();const FString Asset=Fixture->GetStringField(TEXT("asset"));
            const FVector P=CityPoint(Fixture->GetArrayField(TEXT("position")));
            const FRotator Turn(0,Fixture->GetNumberField(TEXT("yaw")),0);
            if(Asset==TEXT("Van"))
            {
                DistrictMesh(Asset,P,Turn);
                for(double X:{-150.,150.})
                    Shape("Cube",P+FVector(X,180,0),FVector(9,1020,1),"MI_White",FRotator::ZeroRotator,false);
                Shape("Cube",P+FVector(0,-330,0),FVector(300,9,1),"MI_White",FRotator::ZeroRotator,false);
            }
            else if(Asset==TEXT("Streetlight"))DistrictMesh(Asset,P,Turn);
            else if(DeclaredBase&&(Asset==TEXT("Medical")||Asset==TEXT("Generator")||Asset==TEXT("Sensor")||Asset==TEXT("UtilityBox")))
            {
                const FBox Declared=CityBox(Fixture->GetObjectField(TEXT("bounds")));
                auto* Assembly=DistrictAssembly(Asset,P,Turn,FVector::OneVector,true,
                    Asset!=TEXT("Medical")&&Asset!=TEXT("UtilityBox"));
                FBox Actual(ForceInit);
                TArray<USceneComponent*> Parts;
                if(Assembly)Assembly->GetChildrenComponents(true,Parts);
                for(const auto* Part:Parts)
                    if(const auto* Mesh=Cast<UStaticMeshComponent>(Part);Mesh&&Mesh->IsCollisionEnabled()&&Mesh->GetStaticMesh())
                        Actual+=Mesh->GetStaticMesh()->GetBoundingBox().TransformBy(Mesh->GetComponentTransform());
                const bool Enclosed=Actual.IsValid&&Declared.IsInsideOrOn(Actual.Min)&&Declared.IsInsideOrOn(Actual.Max);
                UE_LOG(LogTemp,Display,TEXT("MR_BASE_GEOMETRY %s enclosed=%d actual=%s declared=%s"),
                    *Fixture->GetStringField(TEXT("id")),int(Enclosed),*Actual.ToString(),*Declared.ToString());
                if(!Enclosed)UE_LOG(LogTemp,Error,TEXT("MR base collider outside its announced geometry"));
            }
        }
    }
    if(bDecoratedCity)
    {
        for(double X=1200;X<BaseBox.Max.X-200;X+=360)
            Shape("Cube",FVector(X,1000,8),FVector(130,9,1),"MI_Paint",FRotator::ZeroRotator,false);
        ApplyCityDaylight();
    }
    for(const auto& Entry:CityLayout->GetArrayField(TEXT("spawns")))
    {
        auto J=Entry->AsObject();FVector P=CityPoint(J->GetArrayField(TEXT("position")));P.Z=13;
        if(J->GetStringField(TEXT("kind"))==TEXT("ground"))
        {
            // A field-deployed rover can start on a real road. Only docked
            // spawns have the physical parking frame beneath the vehicle.
            if(!J->HasTypedField<EJson::Null>(TEXT("dock")))DistrictMesh("Dock",P,FRotator(0,90,0));
        }
        else
        {
            Shape("Cylinder",P,FVector(210,210,2),"MI_Blue",FRotator::ZeroRotator,false);
            Shape("Cube",P+FVector(0,0,2),FVector(90,10,1),"MI_White",FRotator::ZeroRotator,false);
            Shape("Cube",P+FVector(0,0,2),FVector(10,90,1),"MI_White",FRotator::ZeroRotator,false);
        }
    }
    for(const auto& Entry:CityLayout->GetArrayField(TEXT("infrastructure")))
    {
        auto J=Entry->AsObject();FVector P=CityPoint(J->GetArrayField(TEXT("position")));P.Z=13;
        const FString Kind=J->GetStringField(TEXT("kind"));
        if(Kind==TEXT("relay"))DistrictMesh("Relay",P);
        else if(Kind==TEXT("sensor_node")&&!DeclaredBase)DistrictMesh("Sensor",P);
        else if(Kind==TEXT("charging_station"))
        {
            if(!J->HasTypedField<EJson::Object>(TEXT("charger")))
            {if(!DeclaredBase)DistrictMesh("Generator",P);}
            else if(J->GetObjectField(TEXT("charger"))->GetStringField(TEXT("kind"))==TEXT("ground"))
            {
                if(!DeclaredBase)DistrictMesh("Generator",P+FVector(-480,0,0));
                Shape("Cube",P+FVector(0,0,1),FVector(490,390,2),"MI_Blue",FRotator::ZeroRotator,false);
                DistrictLabel("CHARGE",P+FVector(-430,0,160),30);
            }
        }
        else if(Kind==TEXT("compute_node")&&!DeclaredBase)DistrictMesh("UtilityBox",P);
    }
    FRandomStream RubbleRng(Seed^0x176542);
    for(const auto& Entry:CityLayout->GetArrayField(TEXT("facilities")))
    {
        auto J=Entry->AsObject();const FVector P=CityPoint(J->GetArrayField(TEXT("position")));
        StructureFootprints.Add(CityBox(J->GetObjectField(TEXT("bounds"))));
        for(int32 X:{-1,1})for(int32 Y:{-1,1})Shape("Cube",P+FVector(X*350,Y*280,400),FVector(45,45,800),"MI_Concrete");
        for(int32 I=0;I<5;I++)
        {
            const float X=-300+I*150;
            auto* Support=Shape("Cube",P+FVector(X,0,795),FVector(45,660,40),"MI_Concrete");Support->ComponentTags.Add(TEXT("CollapseSupport"));
            auto* Slab=Chunk(RubbleRng,P+FVector(X,0,847),FVector(145,620,65),true,true);
            Slab->SetRelativeRotation(FRotator::ZeroRotator);Slab->SetRelativeLocation(P+FVector(X,0,847));
        }
        for(int32 I=0;I<18;I++)GroundedChunk(RubbleRng,P+FVector(RubbleRng.FRandRange(-480,480),RubbleRng.FRandRange(-360,360),0),
                                           FVector(110,80,45),true);
        DistrictLabel("UNSTABLE STRUCTURE",P+FVector(0,-600,160),38);
    }
    const auto& Surfaces=CityLayout->GetArrayField(TEXT("surfaces"));
    for(int32 I=0;I<Surfaces.Num();I++)
    {
        const auto Surface=Surfaces[I]->AsObject();const FBox Box=CityBox(Surface->GetObjectField(TEXT("bounds")));
        const FString Kind=Surface->GetStringField(TEXT("kind"));
        const FString Material=bIrregularCity&&Kind==TEXT("paving")?TEXT("M_QuarterPaving"):
            bIrregularCity&&Kind==TEXT("grass")?TEXT("City_Leaves"):TEXT("MI_Ground");
        auto* SurfaceMesh=Shape("Cube",FVector(Box.GetCenter().X,Box.GetCenter().Y,bIrregularCity?2:25),
            FVector(Box.GetSize().X,Box.GetSize().Y,2),Material,FRotator::ZeroRotator,false);
        if(bDecoratedCity&&Kind!=TEXT("paving"))
            SurfaceMesh->SetMaterial(0,CityYardMaterial(Kind==TEXT("grass")?TEXT("M_Lawn"):TEXT("M_Service")));
        for(int32 X=FMath::FloorToInt(Box.Min.X/500);X<=FMath::FloorToInt(Box.Max.X/500);X++)
            for(int32 Y=FMath::FloorToInt(Box.Min.Y/500);Y<=FMath::FloorToInt(Box.Max.Y/500);Y++)CitySurfaceIndex.FindOrAdd({X,Y}).Add(I);
    }
    OptimizeDistrictInstances();
    bBuildingCity=false;
    int32 HorizonComponents=0,HorizonColliders=0;
    for(USceneComponent* C:Generated)if(C)
    {
        if(auto* Batch=Cast<UHierarchicalInstancedStaticMeshComponent>(C))
        {Batch->bAutoRebuildTreeOnInstanceChanges=true;Batch->BuildTreeIfOutdated(false,true);}
        if(!C->IsRegistered())C->RegisterComponent();
        if(C->ComponentHasTag(TEXT("CityVisualHorizon")))
        {
            ++HorizonComponents;
            if(auto* Primitive=Cast<UPrimitiveComponent>(C);Primitive&&Primitive->GetCollisionEnabled()!=ECollisionEnabled::NoCollision)
                ++HorizonColliders;
        }
    }
    UE_LOG(LogTemp,Display,TEXT("MR_CITY_HORIZON_READBACK components=%d colliders=%d"),HorizonComponents,HorizonColliders);
    CityBuildWallSeconds=FPlatformTime::Seconds()-BuildStarted;
    UE_LOG(LogTemp,Display,TEXT("MR_CITY_BUILD_WALL seconds=%.3f"),CityBuildWallSeconds);
    UE_LOG(LogTemp,Display,TEXT("MR_CITY_BUILT size_m=%.0f buildings=%d background_total=%d components=%d bodies=%d"),
        Size/100,CityLayout->GetArrayField(TEXT("buildings")).Num(),Count,Generated.Num(),PhysicsPieces.Num());
}

void AMRWorld::BuildCityYards()
{
    const TArray<FString> Materials={TEXT("M_Yard"),TEXT("M_Lawn"),TEXT("M_Service"),TEXT("M_Verge")};
    TMap<FIntVector,FCityCoverMesh> Batches;
    int32 Count=0;
    for(const auto& Entry:CityLayout->GetArrayField(TEXT("lot_covers")))
    {
        const auto Row=Entry->AsObject();
        const auto& Outline=Row->GetArrayField(TEXT("vertices"));
        if(Outline.Num()<3)continue;
        const auto& First=Outline[0]->AsArray();
        const FString Kind=Row->GetStringField(TEXT("kind"));
        const int32 Material=Kind==TEXT("park")?1:Kind==TEXT("service")?2:Kind==TEXT("garden")?3:0;
        const FIntVector Key(FMath::FloorToInt(First[0]->AsNumber()/200),FMath::FloorToInt(First[1]->AsNumber()/200),Material);
        auto& Batch=Batches.FindOrAdd(Key);
        const int32 Start=Batch.Vertices.Num();
        for(const auto& Value:Outline)
        {
            const auto& Point=Value->AsArray();
            const FVector Vertex(Point[0]->AsNumber()*100,Point[1]->AsNumber()*100,.40);
            Batch.Vertices.Add(Vertex);
            Batch.Normals.Add(FVector::UpVector);
            Batch.UV.Add(FVector2D(Vertex.X,Vertex.Y)/100);
        }
        for(int32 I=1;I+1<Outline.Num();I++)Batch.Triangles.Append({Start,Start+I+1,Start+I});
        Count++;
    }
    for(const auto& Pair:Batches)
    {
        auto* Mesh=NewObject<UProceduralMeshComponent>(this);
        AddInstanceComponent(Mesh);Mesh->SetupAttachment(GetRootComponent());
        Mesh->SetMobility(EComponentMobility::Static);
        Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);Mesh->SetCastShadow(false);
        const auto& Batch=Pair.Value;
        Mesh->CreateMeshSection_LinearColor(0,Batch.Vertices,Batch.Triangles,Batch.Normals,Batch.UV,{},{},false);
        Mesh->SetMaterial(0,CityYardMaterial(Materials[Pair.Key.Z]));
        Mesh->ComponentTags.Add(TEXT("CityLotCover"));Generated.Add(Mesh);
    }
    UE_LOG(LogTemp,Display,TEXT("MR_CITY_YARDS lots=%d batches=%d"),Count,Batches.Num());
}

void AMRWorld::BuildCityFeature(const TSharedPtr<FJsonObject>& Feature)
{
    const FString Id=Feature->GetStringField(TEXT("asset_id"));
    const FString Kind=Feature->GetStringField(TEXT("kind"));
    const FVector Position=CityPoint(Feature->GetArrayField(TEXT("position")));
    const FRotator Turn(0,Feature->GetNumberField(TEXT("yaw")),0);
    if(Kind!=TEXT("shelter"))
    {
        auto* Plant=NewObject<UStaticMeshComponent>(this);
        AddInstanceComponent(Plant);Plant->SetupAttachment(GetRootComponent());
        Plant->SetMobility(EComponentMobility::Static);
        Plant->SetStaticMesh(Kind==TEXT("vegetation")?MRCityVegetation(Id,CityVegetationRevision):MRCityProp(Id));
        Plant->SetRelativeLocation(Position);Plant->SetRelativeRotation(Turn);
        Plant->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        const FString Prefix=Kind==TEXT("vegetation")?TEXT("CityVegetation:"):TEXT("CityProp:");
        Plant->ComponentTags.Add(FName(*(Prefix+Id)));
        Generated.Add(Plant);
        if(CityVegetationRevision>=3&&(Id==TEXT("street_linden")||Id==TEXT("pine_sapling")))
        {
            const float Diameter=Id==TEXT("street_linden")?210:120;
            auto* Planting=Shape(TEXT("Cylinder"),Position+FVector(0,0,3.35),FVector(Diameter,Diameter,.3),
                TEXT("City_Soil"),FRotator::ZeroRotator,false);
            Planting->SetMaterial(0,CityYardMaterial(TEXT("M_Verge")));
        }
    }
    else
    {
        auto Place=[&](FVector Offset,FVector Size,const TCHAR* Material)
        {
            return Shape(TEXT("Cube"),Position+Turn.RotateVector(Offset),Size,Material,Turn,false);
        };
        Place(FVector(0,0,133),FVector(570,380,266),TEXT("MI_Plaster"))->ComponentTags.Add(TEXT("CityUtilityShelter"));
        Place(FVector(0,0,277),FVector(600,400,24),TEXT("MI_Dark"));
        Place(FVector(0,-191,108),FVector(270,2,216),TEXT("MI_Concrete"));
        for(int32 Step=1;Step<=8;Step++)
            Place(FVector(0,-193,Step*24),FVector(265,2,2),TEXT("MI_Dark"));
    }
    for(const auto& Row:Feature->GetArrayField(TEXT("obstacles")))
    {
        const auto Obstacle=Row->AsObject();const FBox Bounds=CityBox(Obstacle);
        FVector Center=Bounds.GetCenter(),Half=Bounds.GetExtent();FRotator Yaw=FRotator::ZeroRotator;
        if(Obstacle->HasTypedField<EJson::Object>(TEXT("footprint")))
        {
            const auto Footprint=Obstacle->GetObjectField(TEXT("footprint"));
            const auto& P=Footprint->GetArrayField(TEXT("center"));const auto& H=Footprint->GetArrayField(TEXT("half"));
            Center.X=P[0]->AsNumber()*100;Center.Y=P[1]->AsNumber()*100;
            Half.X=H[0]->AsNumber()*100;Half.Y=H[1]->AsNumber()*100;
            Yaw.Yaw=Footprint->GetNumberField(TEXT("yaw"));
        }
        auto* Collider=NewObject<UBoxComponent>(this);AddInstanceComponent(Collider);
        Collider->SetupAttachment(GetRootComponent());Collider->SetMobility(EComponentMobility::Static);
        Collider->SetBoxExtent(Half);Collider->SetRelativeLocation(Center);Collider->SetRelativeRotation(Yaw);
        Collider->SetCollisionProfileName(TEXT("BlockAll"));
        Collider->ComponentTags.Add(FName(*FString(TEXT("CityYardCollider:")+Feature->GetStringField(TEXT("id")))));
        Generated.Add(Collider);
    }
}

void AMRWorld::ApplyCityDaylight()
{
    for(TActorIterator<ADirectionalLight> It(GetWorld());It;++It)
    {
        auto* Light=Cast<UDirectionalLightComponent>(It->GetLightComponent());
        if(!Light)continue;
        Light->SetIntensity(18000);
        Light->SetLightColor(FLinearColor(.93f,.96f,1));
        Light->SetLightSourceAngle(7.5f);
        if(bCityProps)Light->SetIndirectLightingIntensity(1.8f);
    }
    for(TActorIterator<ASkyLight> It(GetWorld());It;++It)
    {
        It->GetLightComponent()->SetIntensity(2.8f);
        if(bCityProps)It->GetLightComponent()->SetIndirectLightingIntensity(1.6f);
    }
    for(TActorIterator<AExponentialHeightFog> It(GetWorld());It;++It)It->GetComponent()->SetFogDensity(.007f);
    for(TActorIterator<APostProcessVolume> It(GetWorld());It;++It)if(It->bUnbound)
    {
        auto& Settings=It->Settings;
        Settings.bOverride_AmbientOcclusionIntensity=true;Settings.AmbientOcclusionIntensity=.36f;
        Settings.bOverride_AutoExposureMinBrightness=true;Settings.AutoExposureMinBrightness=4.6f;
    }
}

void AMRWorld::PrepareCityAssetViews()
{
    const float Size=CityLayout->GetNumberField(TEXT("size_m"))*100;
    EventInspections.Add({5,Base,TEXT("quarter-base"),6000,150,-38});
    EventInspections.Add({10,FVector(Size/2,Size/2,0),TEXT("quarter-overview"),Size*1.65f,45,-50});
    EventInspections.Add({14,VanPark+FVector(0,0,110),TEXT("city-service-van"),1100,135,-28});
    TSet<FString> Seen;
    for(const auto& Entry:CityLayout->GetArrayField(TEXT("features")))
    {
        const auto Feature=Entry->AsObject();
        const FString Kind=Feature->GetStringField(TEXT("kind"));
        if(Kind==TEXT("shelter"))continue;
        const FString Id=Feature->GetStringField(TEXT("asset_id"));
        if(Seen.Contains(Id))continue;
        const bool bTree=Id==TEXT("street_linden");
        const FVector Focus=CityPoint(Feature->GetArrayField(TEXT("position")))+FVector(0,0,bTree?222:52);
        const float Distance=bTree?950:Kind==TEXT("parked_vehicle")?1080:620;
        FMRInspection View={18.f+4.f*Seen.Num(),Focus,TEXT("city-asset-")+Id,Distance,45,-18,1.5f};
        for(float Angle:{45.f,135.f,225.f,315.f,0.f,90.f,180.f,270.f})
        {
            const FVector Eye=Focus-FRotator(View.Pitch,Angle,0).Vector()*Distance;
            FHitResult Hit;
            if(!GetWorld()->LineTraceSingleByChannel(Hit,Eye,Focus,ECC_Visibility)||Hit.Distance>Distance-190)
            {View.Yaw=Angle;break;}
        }
        EventInspections.Add(View);
        Seen.Add(Id);
    }
}

void AMRWorld::PrepareCityBuildingViews()
{
    const float Size=CityLayout->GetNumberField(TEXT("size_m"))*100;
    if(VisualProbe==TEXT("city-competition"))
    {
        if(!CityLayout->HasTypedField<EJson::Object>(TEXT("competition")))
        {UE_LOG(LogTemp,Error,TEXT("MR_CITY competition views require the annex"));return;}
        const auto Annex=CityLayout->GetObjectField(TEXT("competition"));
        const FBox Basin=CityBox(Annex->GetObjectField(TEXT("basin")));
        const auto Unit=[&](const FString& Kind)
        {
            for(const auto& Entry:Annex->GetArrayField(TEXT("units")))
                if(Entry->AsObject()->GetStringField(TEXT("kind"))==Kind)
                    return CityPoint(Entry->AsObject()->GetArrayField(TEXT("position")));
            return Base;
        };
        EventInspections={
            {4,FVector(Basin.GetCenter().X,Basin.GetCenter().Y,0),TEXT("city-basin-overview"),7500,35,-48,2.5f},
            {10,Unit(TEXT("surface_water")),TEXT("city-surface-agent"),650,145,-24,2.5f},
            {16,Unit(TEXT("underwater")),TEXT("city-underwater-agent"),550,145,-8,2.5f},
            {22,Unit(TEXT("underground")),TEXT("city-tunnel-agent"),380,0,-5,2.5f},
            {28,Unit(TEXT("infrastructure"))-FVector(0,0,70),TEXT("city-site-sensor"),600,135,-12,2.5f},
            {34,Base+FVector(0,0,100),TEXT("city-services-base"),3500,150,-28,2.5f},
            {40,FVector(-2000,Size*.3f,0),TEXT("city-annex-context"),Size*.85f,150,-45,2.5f}
        };
        return;
    }
    const auto ViewPenalty=[&](const TSharedPtr<FJsonObject>& Subject,FVector Focus,float Distance,float Yaw,float Pitch)
    {
        const FVector Eye=Focus-FRotator(Pitch,Yaw,0).Vector()*Distance;
        double Penalty=0;
        for(const auto& Entry:CityLayout->GetArrayField(TEXT("buildings")))
        {
            const auto Other=Entry->AsObject();if(Other==Subject)continue;
            const FBox Bounds=CityBox(Other->GetObjectField(TEXT("bounds"))).ExpandBy(30);
            if(Bounds.IsInsideOrOn(Eye))Penalty+=10000;
            if(FMath::LineBoxIntersection(Bounds,Eye,Focus,Focus-Eye))Penalty+=1000;
        }
        return Penalty;
    };
    if(VisualProbe==TEXT("city-lumen"))
    {
        for(const auto& Entry:CityLayout->GetArrayField(TEXT("buildings")))
        {
            const auto House=Entry->AsObject();
            if(House->GetIntegerField(TEXT("variant"))!=0)continue;
            const float Yaw=House->GetNumberField(TEXT("yaw"));
            const FVector Window=CityPoint(House->GetArrayField(TEXT("position")))+
                FRotator(0,Yaw,0).RotateVector(FVector(-300,-450,158));
            EventInspections={
                {4,Window,TEXT("city-lit-exterior"),620,Yaw+90,-5,2.5f},
                {9,Window,TEXT("city-surface-cache-exterior"),620,Yaw+90,-5,2.5f},
                {14,Window,TEXT("city-mesh-fields-exterior"),620,Yaw+90,-5,2.5f},
                {19,Window,TEXT("city-surface-cache-interior"),320,Yaw-90,-5,2.5f},
                {24,Window,TEXT("city-mesh-fields-interior"),320,Yaw-90,-5,2.5f},
                {29,Window,TEXT("city-indirect-interior"),320,Yaw-90,-5,2.5f},
                {34,Window,TEXT("city-lit-interior"),320,Yaw-90,-5,2.5f},
            };
            break;
        }
        return;
    }
    if(VisualProbe==TEXT("city-glazing"))
    {
        struct FWindowView{FVector Position;float Facing=0;double Penalty=MAX_dbl;};
        TMap<FString,FWindowView> Windows;
        int32 Count=17;
        for(const auto& Entry:CityLayout->GetArrayField(TEXT("buildings")))
        {
            const auto House=Entry->AsObject();
            const int32 Variant=Count++,Damage=House->GetIntegerField(TEXT("variant"));
            if(Damage>=4)continue;
            const float Yaw=House->GetNumberField(TEXT("yaw"));
            const FVector P=CityPoint(House->GetArrayField(TEXT("position")));
            for(int32 Side:{2,3,0,1})for(int32 Bay:{0,2})
            {
                const FString Style=MRApartmentWindowStyle(Damage,Variant,0,Side,Bay);
                const float Facing=Yaw+90.f*Side;
                const FVector Window=P+FRotator(0,Facing,0).RotateVector(FVector((Bay-1)*300,-450,155));
                // Room furniture is on the south side. Prefer a clear north
                // bay and reject exterior viewpoints behind a neighbouring wall.
                const double Penalty=(Side==2?0:Side==0?20:5)+
                    ViewPenalty(House,Window,600,Facing+90,-5)+ViewPenalty(House,Window,650,Facing+50,-8);
                auto& Candidate=Windows.FindOrAdd(Style);
                if(Penalty<Candidate.Penalty)Candidate={Window,Facing,Penalty};
            }
            if(Count>=177)break;
        }
        int32 Index=0;
        for(const FString& Style:{TEXT("clean"),TEXT("dirty"),TEXT("cracked"),TEXT("broken"),TEXT("empty")})
        {
            const auto* View=Windows.Find(Style);if(!View)continue;
            const float At=4.f+15.f*Index++;const FString Prefix=TEXT("city-glazing-")+Style;
            EventInspections.Add({At,View->Position,Prefix+TEXT("-exterior"),600,View->Facing+90,-5,2.5f});
            EventInspections.Add({At+5,View->Position,Prefix+TEXT("-interior"),295,View->Facing-90,-5,2.5f});
            EventInspections.Add({At+10,View->Position,Prefix+TEXT("-oblique"),650,View->Facing+50,-8,2.5f});
            UE_LOG(LogTemp,Display,TEXT("MR_CITY_WINDOW_VIEW style=%s penalty=%.1f"),*Style,View->Penalty);
        }
        return;
    }
    EventInspections.Add({4,FVector(Size/2,Size/2,0),TEXT("quarter-overview"),Size*1.65f,45,-50});
    for(int32 Variant=0;Variant<6;Variant++)
    {
        FMRInspection Best;double BestPenalty=MAX_dbl;TSharedPtr<FJsonObject> Selected;int32 Candidates=0;
        for(const auto& Entry:CityLayout->GetArrayField(TEXT("buildings")))
        {
            const auto House=Entry->AsObject();if(House->GetIntegerField(TEXT("variant"))!=Variant)continue;
            const FVector P=CityPoint(House->GetArrayField(TEXT("position")));
            const int32 Floors=House->GetIntegerField(TEXT("floors"));
            const float Height=Variant==5?300:Variant==4?590:(Variant==3?FMath::Max(2,Floors-1)*300+100:Floors*300);
            const float Distance=FMath::Max(1850.f,Height*2.2f),Yaw=House->GetNumberField(TEXT("yaw"));
            const FVector Focus=P+FVector(0,0,Height*.42f);
            for(float Pitch:{-24.f,-35.f,-48.f})for(float Offset:{73.f,120.f,165.f,210.f,255.f,300.f,345.f})
            {
                const double Penalty=ViewPenalty(House,Focus,Distance,Yaw+Offset,Pitch)+FMath::Abs(Pitch+24)*.1;
                if(Penalty<BestPenalty)
                {BestPenalty=Penalty;Best={8.f+4.f*Variant,Focus,FString::Printf(TEXT("city-building-%d"),Variant),Distance,Yaw+Offset,Pitch,1.5f};Selected=House;}
            }
            if(++Candidates>=12)break;
        }
        if(!Selected)continue;
        EventInspections.Add(Best);
        UE_LOG(LogTemp,Display,TEXT("MR_CITY_BUILDING_VIEW variant=%d penalty=%.1f yaw=%.1f pitch=%.1f"),Variant,BestPenalty,Best.Yaw,Best.Pitch);
        if(Variant==0)
        {
            const float Yaw=Selected->GetNumberField(TEXT("yaw"));
            const FVector P=CityPoint(Selected->GetArrayField(TEXT("position")));
            const FVector Window=P+FRotator(0,Yaw,0).RotateVector(FVector(-300,-450,158));
            EventInspections.Add({55.f,Window,TEXT("city-window-exterior"),620,Yaw+90,-5,2.5f});
            EventInspections.Add({61.f,Window,TEXT("city-interior"),320,Yaw-90,-5,2.5f});
            EventInspections.Add({67.f,Window,TEXT("city-window-oblique"),640,Yaw+47,-7,2.5f});
        }
    }
    const auto Graph=CityLayout->GetObjectField(TEXT("road_graph"));TMap<FString,FVector> Nodes;
    for(const auto& Entry:Graph->GetArrayField(TEXT("nodes")))
    {
        const auto Node=Entry->AsObject();
        Nodes.Add(Node->GetStringField(TEXT("id")),CityPoint(Node->GetArrayField(TEXT("position"))));
    }
    int32 Side=0;
    for(const auto& Entry:Graph->GetArrayField(TEXT("entrances")))
    {
        const auto Gate=Entry->AsObject();const auto& Direction=Gate->GetArrayField(TEXT("outward"));
        const FVector Outward(Direction[0]->AsNumber(),Direction[1]->AsNumber(),0);
        const FVector GatePos=Nodes.FindChecked(Gate->GetStringField(TEXT("node_id")));
        const float Yaw=static_cast<float>((-Outward).Rotation().Yaw)+18.f;
        EventInspections.Add({34.f+5.f*Side,GatePos+Outward*1950,FString::Printf(TEXT("city-boundary-%d"),Side),
            4800,Yaw,-29,1.5f});
        Side++;
    }
    EventInspections.Sort([](const FMRInspection& A,const FMRInspection& B){return A.Time<B.Time;});
}

void AMRWorld::BuildIrregularStreets(const FBox& BaseBox)
{
    const auto Graph=CityLayout->GetObjectField(TEXT("road_graph"));
    TMap<FString,FVector> Positions;TMap<FString,double> JunctionWidths;
    for(const auto& Row:Graph->GetArrayField(TEXT("nodes")))
    {
        const auto Node=Row->AsObject();
        Positions.Add(Node->GetStringField(TEXT("id")),CityPoint(Node->GetArrayField(TEXT("position"))));
    }
    const auto Pave=[&](const FVector& Start,const FVector& End,double Width,bool Avenue,bool Footway)
    {
        const FVector Delta=End-Start;
        const double Length=Delta.Size2D();if(Length<2)return;
        const FVector Along=Delta/Length,Normal(-Along.Y,Along.X,0);
        const FRotator Turn(0,Along.Rotation().Yaw,0);
        const FVector Middle=(Start+End)*.5;
        // All strips share the flat physical terrain. Render-layer seams do
        // not create overlapping support colliders at angled intersections.
        Shape("Cube",Middle+FVector(0,0,1.2),FVector(Length,Width,1),"M_QuarterAsphalt",Turn,false);
        if(Footway&&Length>500)for(double Side:{-1.,1.})
        {
            const FVector Shoulder=Middle+Normal*Side*(Width/2+75);
            if(!BaseBox.IsInsideXY(Shoulder))Shape("Cube",Shoulder+FVector(0,0,.8),FVector(Length-250,140,1),"M_QuarterPaving",Turn,false);
        }
        if(Avenue)for(double At=460;At<Length-350;At+=440)
        {
            const FVector Dash=Start+Along*At;
            if(!BaseBox.IsInsideXY(Dash))Shape("Cube",Dash+FVector(0,0,2),FVector(150,9,1),"MI_Paint",Turn,false);
        }
    };
    const bool bShowProps=bCityProps&&FApp::CanEverRender()&&
        CityLayout->HasTypedField<EJson::Number>(TEXT("background_revision"));
    TArray<FBox> StreetPropExclusions;
    TArray<FVector> DamagedLots;
    struct FStreet { FVector Start,End; double Width; };
    TArray<FStreet> Streets;
    TMap<FString,TArray<FVector>> Approaches;
    if(bShowProps)
    {
        StreetPropExclusions.Add(BaseBox);
        for(const TCHAR* Key:{TEXT("buildings"),TEXT("facilities"),TEXT("fixed_obstacles")})
            for(const auto& Entry:CityLayout->GetArrayField(Key))
            {
                const auto Item=Entry->AsObject();const auto Bounds=CityBox(Item->GetObjectField(TEXT("bounds")));
                StreetPropExclusions.Add(Bounds);
                if(FStringView(Key)==TEXT("buildings")&&Item->GetIntegerField(TEXT("variant"))>=2)
                    DamagedLots.Add(CityPoint(Item->GetArrayField(TEXT("position"))));
            }
        for(const auto& Entry:CityLayout->GetArrayField(TEXT("features")))
            for(const auto& Obstacle:Entry->AsObject()->GetArrayField(TEXT("obstacles")))
                StreetPropExclusions.Add(CityBox(Obstacle->AsObject()));
        for(const auto& Entry:CityLayout->GetArrayField(TEXT("infrastructure")))
        {
            const FVector P=CityPoint(Entry->AsObject()->GetArrayField(TEXT("position")));
            StreetPropExclusions.Emplace(P-FVector(90),P+FVector(90));
        }
    }
    const auto Fits=[&](const FBox& Envelope)
    {
        return !StreetPropExclusions.ContainsByPredicate([&](const FBox& Existing){return Existing.IntersectXY(Envelope);});
    };
    const auto Decorate=[](USceneComponent* Root,FName Tag)
    {
        Root->ComponentTags.Add(Tag);
        for(USceneComponent* Child:Root->GetAttachChildren())if(auto* Mesh=Cast<UStaticMeshComponent>(Child))
        {
            Mesh->ComponentTags.Add(Tag);
            Mesh->ComponentTags.Add(TEXT("NoMissionCollision"));
        }
    };
    int32 RoadModules=0,PoweredSignals=0,DarkSignals=0;
    for(const auto& Row:Graph->GetArrayField(TEXT("edges")))
    {
        const auto Edge=Row->AsObject();const FString A=Edge->GetStringField(TEXT("from")),B=Edge->GetStringField(TEXT("to"));
        const double Width=Edge->GetNumberField(TEXT("width_m"))*100;
        const FString Kind=Edge->GetStringField(TEXT("street_class"));
        const FVector Start=Positions.FindChecked(A),End=Positions.FindChecked(B);
        const FVector Direction=(End-Start).GetSafeNormal2D(),Normal(-Direction.Y,Direction.X,0);
        const FVector Middle=(Start+End)*.5;
        const bool Avenue=Kind==TEXT("avenue");
        bool bReplaced=false;
        if(bShowProps)
        {
            Streets.Add({Start,End,Width});
            Approaches.FindOrAdd(A).Add(Direction);
            Approaches.FindOrAdd(B).Add(-Direction);
            if(RoadModules<3&&Kind==TEXT("street")&&Width<=850&&FVector::DistSquared2D(Start,End)>=FMath::Square(2700.))
            {
                // Source road section is 9.998 m long with 7 m between its curbs.
                // Keep the road support and graph unchanged and replace only the render layer.
                const double HalfLength=499.9,HalfWidth=540*Width/700;
                const FVector Extent=Direction.GetAbs()*HalfLength+Normal.GetAbs()*HalfWidth+FVector(20,20,20);
                const FBox Envelope(Middle-Extent,Middle+Extent);
                if(Fits(Envelope))if(auto* Module=DistrictAssembly(TEXT("ModularRoadSectionV1"),Middle+FVector(0,0,1.2),
                    Direction.Rotation(),FVector(1,Width/700,1),false))
                {
                    Decorate(Module,TEXT("CityRoadModule"));StreetPropExclusions.Add(Envelope);
                    Pave(Start,Middle-Direction*HalfLength,Width,false,true);
                    Pave(Middle+Direction*HalfLength,End,Width,false,true);
                    ++RoadModules;bReplaced=true;
                }
            }
        }
        if(!bReplaced)Pave(Start,End,Width,Avenue,Kind!=TEXT("access"));
        for(const FString& Id:{A,B})JunctionWidths.FindOrAdd(Id)=FMath::Max(JunctionWidths.FindRef(Id),Width);
    }
    if(bShowProps)
    {
        auto* RedOff=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/RescueAssets/LibraryV3/TrafficSignalV1/Materials/M_TrafficSignalV1_RedOff.M_TrafficSignalV1_RedOff"));
        const double Size=CityLayout->GetNumberField(TEXT("size_m"))*100;
        const double Spacing=FMath::Max(6400.,Size/4.);
        TSet<FIntPoint> SignalBlocks;
        for(const auto& Row:Graph->GetArrayField(TEXT("nodes")))
        {
            const FString Id=Row->AsObject()->GetStringField(TEXT("id"));
            const auto* Neighbors=Approaches.Find(Id);
            if(!Neighbors||Neighbors->Num()<3)continue;
            const FVector Center=Positions.FindChecked(Id);
            const FIntPoint Block(FMath::FloorToInt(Center.X/Spacing),FMath::FloorToInt(Center.Y/Spacing));
            if(SignalBlocks.Contains(Block))continue;
            const double Offset=JunctionWidths.FindChecked(Id)/2+230;
            bool bPlaced=false;
            for(const FVector& Direction:*Neighbors)
            {
                const FVector Right(-Direction.Y,Direction.X,0);
                for(const double Side:{1.,-1.})
                {
                    const FVector P=Center+Direction*780+Right*(Side*Offset);
                    if(P.X<100||P.Y<100||P.X>Size-100||P.Y>Size-100)continue;
                    const FBox Envelope(P-FVector(65,65,0),P+FVector(65,65,355));
                    if(!Fits(Envelope)||Streets.ContainsByPredicate([&](const FStreet& Street)
                        {return FVector::DistSquared2D(P,FMath::ClosestPointOnSegment(P,Street.Start,Street.End))<FMath::Square(Street.Width/2+180);}))continue;
                    // Blender -Y becomes Unreal +Y in the selected forward-axis export.
                    auto* Signal=DistrictAssembly(TEXT("TrafficSignalV1"),P,FRotator(0,Direction.Rotation().Yaw-90,0),FVector::OneVector,false);
                    if(!Signal)break;
                    const bool bDark=RedOff&&DamagedLots.ContainsByPredicate([&](const auto& Lot)
                        {return FVector::DistSquared2D(P,Lot)<FMath::Square(1800.);});
                    Decorate(Signal,bDark?TEXT("CityTrafficSignal:off"):TEXT("CityTrafficSignal:powered"));
                    if(bDark)for(USceneComponent* Child:Signal->GetAttachChildren())if(auto* Mesh=Cast<UStaticMeshComponent>(Child))
                        for(int32 Slot=0;Slot<Mesh->GetNumMaterials();++Slot)
                            if(const auto* Material=Mesh->GetMaterial(Slot);Material&&Material->GetName()==TEXT("M_TrafficSignalV1_Red"))
                                Mesh->SetMaterial(Slot,RedOff);
                    if(bDark)++DarkSignals;else ++PoweredSignals;
                    StreetPropExclusions.Add(Envelope);SignalBlocks.Add(Block);bPlaced=true;break;
                }
                if(bPlaced)break;
            }
        }
        UE_LOG(LogTemp,Display,TEXT("MR_CITY_STREET_PROPS road_modules=%d powered=%d off=%d collision=none"),RoadModules,PoweredSignals,DarkSignals);
    }
    for(const auto& Junction:JunctionWidths)if(!BaseBox.IsInsideXY(Positions.FindChecked(Junction.Key)))
        Shape("Cylinder",Positions.FindChecked(Junction.Key)+FVector(0,0,1.65),FVector(Junction.Value,Junction.Value,1),"M_QuarterAsphalt",FRotator::ZeroRotator,false);
    for(const auto& Row:Graph->GetArrayField(TEXT("entrances")))
    {
        const auto Gate=Row->AsObject();const auto& Direction=Gate->GetArrayField(TEXT("outward"));
        const FVector Start=Positions.FindChecked(Gate->GetStringField(TEXT("node_id")));
        Pave(Start,Start+FVector(Direction[0]->AsNumber(),Direction[1]->AsNumber(),0)*6500,1000,true,true);
    }
}

float AMRWorld::CityGroundCost(const FVector& P) const
{
    float Cost=1;const auto* Entries=CitySurfaceIndex.Find(FIntPoint(int32(FMath::FloorToInt(P.X/500)),int32(FMath::FloorToInt(P.Y/500))));
    if(Entries)for(int32 Index:*Entries)
    {
        auto J=CityLayout->GetArrayField(TEXT("surfaces"))[Index]->AsObject();
        if(CityBox(J->GetObjectField(TEXT("bounds"))).IsInsideXY(P))Cost*=J->GetNumberField(TEXT("cost"));
    }
    return Cost;
}
