#include "MRWorld.h"
#include "MRAgent.h"
#include "MRCameraPawn.h"
#include "MRCityAssets.h"
#include "MRCoreRuntime.h"
#include "MRCoreReset.h"
#include "MRMissionSession.h"
#include "EngineUtils.h"
#include "ProceduralMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/HierarchicalInstancedStaticMeshComponent.h"
#include "Components/BoxComponent.h"
#include "Components/MeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Materials/MaterialInterface.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "HAL/FileManager.h"
#include "UnrealClient.h"
#include "NiagaraComponent.h"
#include "NiagaraFunctionLibrary.h"
#include "NiagaraSystem.h"
#include "HAL/PlatformMemory.h"
#include "HAL/PlatformTime.h"
#include "HAL/IConsoleManager.h"
#include "Misc/App.h"

AMRWorld::AMRWorld()
{
    PrimaryActorTick.bCanEverTick=true;
    SetRootComponent(CreateDefaultSubobject<USceneComponent>(TEXT("DistrictRoot")));
    GetRootComponent()->SetMobility(EComponentMobility::Static);
}

bool AMRWorld::ReadScenario()
{
    if(const auto* Session=UMRMissionSession::Get(GetWorld()))
    {
        if(Session->CoreReset&&!Session->CoreReset->LayoutFile.IsEmpty())
            return ReadCityLayout(Session->CoreReset->LayoutFile);
        if(Session->Enabled&&!Session->LayoutFile.IsEmpty())return ReadCityLayout(Session->LayoutFile);
    }
    FString CityFile;
    if(bRescueQuarter&&FParse::Value(FCommandLine::Get(),TEXT("MRLayoutFile="),CityFile))return ReadCityLayout(CityFile);
    FString Text;
    const FString File=FPaths::ProjectContentDir()/(bRescueQuarter?TEXT("Scenario/quarter.json"):TEXT("Scenario/scenario.json"));
    if(!FFileHelper::LoadFileToString(Text,*File)||!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Scenario)||!Scenario)
    { UE_LOG(LogTemp,Error,TEXT("MR: missing or invalid scenario: %s"),*File);return false; }
    GridSize=Scenario->GetIntegerField(TEXT("width"));Seed=Scenario->GetIntegerField(TEXT("seed"));
    const auto& Rows=Scenario->GetArrayField(TEXT("grid"));
    if(GridSize<1||GridSize>65||Rows.Num()!=GridSize)return false;
    Grid.Empty();
    for(const auto& Row:Rows)
    {
        TArray<int32> Cells;for(const auto& V:Row->AsArray())Cells.Add(int32(V->AsNumber()));
        if(Cells.Num()!=GridSize)return false;Grid.Add(Cells);
    }
    const auto& B=Scenario->GetArrayField(TEXT("base"));
    Base=FVector(B[0]->AsNumber()*1000,B[1]->AsNumber()*1000,0);
    return true;
}

UStaticMeshComponent* AMRWorld::Shape(const FString& Mesh,const FVector& P,const FVector& S,
    const FString& Mat,const FRotator& R,bool Collision)
{
    auto* C=NewObject<UStaticMeshComponent>(this);AddInstanceComponent(C);C->SetupAttachment(GetRootComponent());
    auto* Source=LoadObject<UStaticMesh>(nullptr,*(TEXT("/Engine/BasicShapes/")+Mesh+TEXT(".")+Mesh));
    auto* Baked=bCityLayout&&Mesh==TEXT("Cube")?MRCityBakedBox(S):nullptr;
    if(!Baked&&bCityLayout){const auto Parts=MRCityMeshParts(Source);if(!Parts.IsEmpty())Source=Parts[0].Mesh;}
    C->SetStaticMesh(Baked?Baked:Source);
    const FString MaterialFolder=Mat.StartsWith(TEXT("City_"))?TEXT("/Game/MaterialsCity/"):TEXT("/Game/Materials/");
    auto* Material=MRSceneMaterial(LoadObject<UMaterialInterface>(nullptr,*(MaterialFolder+Mat+TEXT(".")+Mat)));
    C->SetMaterial(0,bCityLayout?MRCityMaterial(Material):Material);
    C->SetMobility(bBuildingCity?EComponentMobility::Movable:EComponentMobility::Static);
    if(bBuildingCity)C->ComponentTags.Add(TEXT("CityStaticPending"));
    C->SetCollisionEnabled(Collision?ECollisionEnabled::QueryAndPhysics:ECollisionEnabled::NoCollision);
    C->SetRelativeLocation(P);C->SetRelativeRotation(R);C->SetRelativeScale3D(Baked?FVector::OneVector:S/100.f);
    if(!bBuildingCity)C->RegisterComponent();
    Generated.Add(C);return C;
}

UProceduralMeshComponent* AMRWorld::Chunk(FRandomStream& Rng,const FVector& P,const FVector& S,bool Physics,bool Collapse)
{
    auto* C=NewObject<UProceduralMeshComponent>(this);AddInstanceComponent(C);C->SetupAttachment(GetRootComponent());
    C->SetMobility(Physics||bBuildingCity?EComponentMobility::Movable:EComponentMobility::Static);
    if(bBuildingCity&&!Physics)C->ComponentTags.Add(TEXT("CityStaticPending"));
    C->bUseComplexAsSimpleCollision=false;C->bUseAsyncCooking=false;
    C->SetRelativeLocation(P);C->SetRelativeRotation(FRotator(Rng.FRandRange(-24,24),Rng.FRandRange(-180,180),Rng.FRandRange(-22,22)));
    C->SetCollisionProfileName(TEXT("PhysicsActor"));C->RegisterComponent();
    TArray<FVector> Corners;
    for(int32 I=0;I<8;I++)Corners.Add(FVector((I&1?1:-1)*S.X*.5,(I&2?1:-1)*S.Y*.5,(I&4?1:-1)*S.Z*.5)
        +FVector(Rng.FRandRange(-.1,.1)*S.X,Rng.FRandRange(-.1,.1)*S.Y,Rng.FRandRange(-.15,.15)*S.Z));
    const int32 Faces[6][4]={{0,4,6,2},{1,3,7,5},{0,1,5,4},{2,6,7,3},{0,2,3,1},{4,5,7,6}};
    TArray<FVector> V,N;TArray<int32> Tri;TArray<FVector2D> UV;
    for(const auto& Face:Faces)
    {
        const int32 Offset=V.Num();const FVector Normal=FVector::CrossProduct(Corners[Face[1]]-Corners[Face[0]],Corners[Face[2]]-Corners[Face[0]]).GetSafeNormal();
        for(int32 J=0;J<4;J++){V.Add(Corners[Face[J]]);N.Add(Normal);UV.Add(FVector2D(J==1||J==2?1:0,J>=2?1:0));}
        // Unreal uses clockwise front faces; normals remain outward.
        Tri.Append({Offset,Offset+2,Offset+1,Offset,Offset+3,Offset+2});
    }
    C->CreateMeshSection_LinearColor(0,V,Tri,N,UV,TArray<FLinearColor>(),TArray<FProcMeshTangent>(),false);
    C->AddCollisionConvexMesh(Corners);
    C->SetMaterial(0,LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/Materials/MI_Concrete.MI_Concrete")));
    C->SetLinearDamping(.3f);C->SetAngularDamping(.9f);
    C->SetMassOverrideInKg(NAME_None,FMath::Clamp(float(S.X*S.Y*S.Z*.0008),20.f,1400.f));
    Generated.Add(C);
    if(Physics)
    {
        PhysicsPieces.Add(C);if(Collapse)CollapsePieces.Add(C);
        if(bRuntimeReady)
        {
            InitialPiecePositions.Add(C->GetComponentLocation());C->SetSimulatePhysics(!Collapse);
            C->SetNotifyRigidBodyCollision(true);C->OnComponentHit.AddDynamic(this,&AMRWorld::OnRubbleHit);
        }
    }
    return C;
}

void AMRWorld::Building(FRandomStream& Rng,int32 X,int32 Y)
{
    const FVector Center(X*1000,Y*1000,0);const int32 Floors=Rng.RandRange(2,4);
    Shape("Cube",Center+FVector(0,0,30),FVector(850,850,60),"MI_Concrete");
    for(int32 SX:{-1,1})for(int32 SY:{-1,1})
        Shape("Cube",Center+FVector(SX*345,SY*345,Floors*155),FVector(42,42,Floors*310),"MI_Concrete");
    for(int32 F=1;F<=Floors;F++)
    {
        const float Z=F*310;
        Shape("Cube",Center+FVector(-110,0,Z),FVector(570,780,28),"MI_Concrete");
        if(Rng.FRand()>.35)Shape("Cube",Center+FVector(295,170,Z-35),FVector(220,380,23),"MI_Concrete",FRotator(0,0,Rng.FRandRange(-9,9)));
        for(int32 Side:{-1,1})
        {
            Shape("Cube",Center+FVector(0,Side*365,Z-245),FVector(740,22,105),"MI_Plaster");
            if(Rng.FRand()>.3)
            {
                Shape("Cube",Center+FVector(0,Side*367,Z-120),FVector(480,9,128),"MI_Glass",FRotator::ZeroRotator,false);
                for(int32 K:{-1,0,1})Shape("Cube",Center+FVector(K*242,Side*370,Z-125),FVector(12,18,145),"MI_Metal",FRotator::ZeroRotator,false);
            }
            if(Rng.FRand()>.4)Shape("Cube",Center+FVector(Side*365,-80,Z-155),FVector(28,510,260),"MI_Plaster");
        }
        // Exposed ends of floor reinforcement remain distinct from solid walls.
        for(int32 I=0;I<3;I++)Shape("Cube",Center+FVector(415,-190+I*105,Z-8),FVector(160,5,5),"MI_Rust",FRotator(0,Rng.FRandRange(-8,8),Rng.FRandRange(-6,6)),false);
    }
    for(int32 I=0;I<5;I++)Chunk(Rng,Center+FVector(Rng.FRandRange(-420,420),Rng.FRandRange(-420,420),60),FVector(Rng.FRandRange(120,260),Rng.FRandRange(100,200),Rng.FRandRange(50,100)),false);
}

void AMRWorld::Checkpoint()
{
    // Keep the shelter outside the route grid: props must not obstruct the exit.
    const FVector C=Base+FVector(-1500,1000,0);
    Shape("Cube",C+FVector(0,0,12),FVector(1750,1350,24),"MI_Concrete");
    Shape("Cube",C+FVector(0,270,180),FVector(1100,530,360),"MI_Teal");
    Shape("Cube",C+FVector(0,250,371),FVector(1150,600,30),"MI_Metal");
    for(int32 I=-4;I<=4;I++)Shape("Cube",C+FVector(I*110,1,180),FVector(8,5,342),"MI_Metal",FRotator::ZeroRotator,false);
    Shape("Cube",C+FVector(200,-3,180),FVector(310,15,250),"MI_Glass",FRotator::ZeroRotator,false);
    Shape("Cube",C+FVector(-250,-11,210),FVector(40,15,165),"MI_WhiteGlow",FRotator::ZeroRotator,false);
    Shape("Cube",C+FVector(-250,-12,210),FVector(165,15,40),"MI_WhiteGlow",FRotator::ZeroRotator,false);
    Shape("Cube",C+FVector(0,-330,310),FVector(1050,650,18),"MI_Teal",FRotator(-4,0,0));
    for(int32 I:{-1,1})Shape("Cylinder",C+FVector(I*480,-600,155),FVector(12,12,310),"MI_Metal");
    // A small service vehicle, with clear rescue colours and cab proportions.
    const FVector A=Base+FVector(-1000,-150,0);
    Shape("Cube",A+FVector(0,0,120),FVector(520,215,150),"MI_White");
    Shape("Cube",A+FVector(170,0,195),FVector(160,210,125),"MI_White");
    Shape("Cube",A+FVector(245,0,220),FVector(9,180,65),"MI_Glass",FRotator(0,0,0),false);
    for(int32 Y:{-1,1})
    {
        Shape("Cube",A+FVector(-50,Y*110,155),FVector(380,5,22),"MI_Red",FRotator::ZeroRotator,false);
        for(int32 X:{-175,170})Shape("Cylinder",A+FVector(X,Y*110,53),FVector(94,94,23),"MI_Rubber",FRotator(0,0,90));
    }
    Shape("Cube",A+FVector(150,0,265),FVector(40,145,20),"MI_CyanGlow",FRotator::ZeroRotator,false);
    // Cones, crates and a marked collection area make the checkpoint readable.
    for(int32 I=0;I<10;I++)
    {
        FVector P=Base+FVector(-850,-400+I*180,0);
        Shape("Cube",P+FVector(0,0,4),FVector(65,65,8),"MI_Dark");
        Shape("Cone",P+FVector(0,0,42),FVector(48,48,76),"MI_Orange");
    }
    for(int32 I=0;I<4;I++)Shape("Cube",C+FVector(-600+I*120,0,55),FVector(100,85,110),"MI_Equipment");
    Shape("Cube",Base+FVector(0,0,1),FVector(820,650,2),"MI_Zone",FRotator::ZeroRotator,false);
    for(int32 I=0;I<4;I++)Shape("Cube",Base+FVector(-300+I*200,0,3),FVector(110,4,2),"MI_White",FRotator::ZeroRotator,false);
}

void AMRWorld::BuildScene()
{
    for(USceneComponent* C:Generated){if(C){RemoveInstanceComponent(C);C->DestroyComponent();}}
    Generated.Empty();PhysicsPieces.Empty();CollapsePieces.Empty();
    StructureFootprints.Empty();
    DistrictMechanisms.Empty();ServiceVan=nullptr;
    if(!ReadScenario())return;
    if(bCityLayout){BuildCity();return;}
    if(bRescueQuarter){BuildDistrict();return;}
    FRandomStream Rng(Seed);const float Mid=(GridSize-1)*500.f;
    Shape("Cube",FVector(Mid,Mid,-60),FVector(GridSize*1000+3200,GridSize*1000+3200,100),"MI_Asphalt");
    for(int32 Y=0;Y<GridSize;Y++)for(int32 X=0;X<GridSize;X++)
    {
        const int32 V=Grid[Y][X];const FVector P(X*1000,Y*1000,-10);
        const bool Road=X<=2||Y<=2||X==GridSize/2||Y==GridSize/2||X%5==0||Y%5==0;
        if(V==3)
        {
            Shape("Plane",P+FVector(0,0,13),FVector(1000,1000,100),"MI_Water",FRotator::ZeroRotator,false);
            auto* Bank=NewObject<UBoxComponent>(this);AddInstanceComponent(Bank);Bank->SetupAttachment(GetRootComponent());
            Bank->SetBoxExtent(FVector(470,470,160));Bank->SetRelativeLocation(P+FVector(0,0,150));
            Bank->SetCollisionProfileName(TEXT("BlockAll"));Bank->RegisterComponent();Generated.Add(Bank);
            continue;
        }
        if(V==2)Shape("Cylinder",P+FVector(0,0,11),FVector(700,850,2),"MI_Mud",FRotator(0,Rng.FRandRange(0,180),0),false);
        if(V==1)
        {
            if(V==1&&Rng.FRand()>.4)Building(Rng,X,Y);
            else
            {
                for(int32 I=0;I<9;I++)Chunk(Rng,P+FVector(Rng.FRandRange(-330,330),Rng.FRandRange(-330,330),70+I*16),FVector(Rng.FRandRange(180,550),Rng.FRandRange(120,430),Rng.FRandRange(70,160)),false);
                for(int32 I=0;I<4;I++)Shape("Cube",P+FVector(Rng.FRandRange(-300,300),Rng.FRandRange(-300,300),130),FVector(350,5,5),"MI_Rust",FRotator(0,Rng.FRandRange(0,180),Rng.FRandRange(-30,30)),false);
            }
        }
        else if(Road&&X>2&&Y>2)
        {
            if(X%5==0)Shape("Cube",P+FVector(0,0,11),FVector(10,300,1),"MI_Paint",FRotator::ZeroRotator,false);
            else if(Y%5==0)Shape("Cube",P+FVector(0,0,11),FVector(300,10,1),"MI_Paint",FRotator::ZeroRotator,false);
        }
    }
    Checkpoint();
    // Deliberately unstable detached concrete. Chaos, not an animated transform.
    const FVector CollapseOrigin=Base+FVector(2300,1800,0);
    for(int32 I=0;I<18;I++)
        Chunk(Rng,CollapseOrigin+FVector(Rng.FRandRange(-500,500),Rng.FRandRange(-430,430),60+I*42),
              FVector(Rng.FRandRange(150,390),Rng.FRandRange(130,290),Rng.FRandRange(50,110)),true);
    for(int32 I=0;I<5;I++)
        Chunk(Rng,CollapseOrigin+FVector(-400+I*190,80,1050+I*85),FVector(400,520,65),true,true);
    for(int32 I=0;I<5;I++)
    {
        FVector P=Base+FVector(900+I*1300,-450,0);
        Shape("Cylinder",P+FVector(0,0,300),FVector(17,17,600),"MI_Metal");
        Shape("Cube",P+FVector(80,0,605),FVector(170,36,15),"MI_Metal");
        Shape("Cube",P+FVector(110,0,593),FVector(110,27,5),"MI_WhiteGlow",FRotator::ZeroRotator,false);
    }
    UE_LOG(LogTemp,Display,TEXT("MR scene built: %d components, %d Chaos pieces, grid %d"),Generated.Num(),PhysicsPieces.Num(),GridSize);
}

void AMRWorld::SpawnTargets()
{
    Targets.Empty();
    for(const auto& Item:Scenario->GetArrayField(TEXT("people")))
    {
        auto J=Item->AsObject();FMRTarget T;T.Id=J->GetIntegerField(TEXT("id"));
        T.Position=FVector(J->GetNumberField(TEXT("x"))*1000,J->GetNumberField(TEXT("y"))*1000,bRescueQuarter?6:24);
        if(J->HasTypedField<EJson::Number>(TEXT("z_m")))T.Position.Z=100*J->GetNumberField(TEXT("z_m"));
        for(const auto& P:J->GetArrayField(TEXT("path")))
        {const auto& XY=P->AsArray();T.Path.Add(FVector(XY[0]->AsNumber()*1000,XY[1]->AsNumber()*1000,48));}
        AActor* Visual=GetWorld()->SpawnActor<AActor>(T.Position,FRotator::ZeroRotator);
        USceneComponent* Root=NewObject<USceneComponent>(Visual);Visual->SetRootComponent(Root);Visual->AddInstanceComponent(Root);Root->RegisterComponent();Visual->SetActorLocation(T.Position);
        if(bRescueQuarter)
        {
            TArray<FMRAssemblyPart> Parts;
            constexpr double StretcherPadHeightCm=20.4354;
            auto* Stretcher=MRBuildAssembly(Visual,Root,TEXT("StretcherV2"),FVector::ZeroVector,
                FRotator::ZeroRotator,FVector::OneVector,false,true,Parts);
            if(!Stretcher)
                MRBuildAssembly(Visual,Root,TEXT("Stretcher"),FVector::ZeroVector,FRotator::ZeroRotator,FVector::OneVector,false,true,Parts);
            MRBuildAssembly(Visual,Root,TEXT("Casualty"),FVector(0,0,Stretcher?StretcherPadHeightCm:31.),
                FRotator::ZeroRotator,FVector::OneVector,false,true,Parts);
            if(J->HasTypedField<EJson::Number>(TEXT("available_at")))T.AvailableAt=J->GetNumberField(TEXT("available_at"));
            if(J->HasTypedField<EJson::Number>(TEXT("priority")))T.Priority=J->GetNumberField(TEXT("priority"));
            Visual->SetActorHiddenInGame(T.AvailableAt>0);
            T.Visual=Visual;Targets.Add(T);continue;
        }
        auto BodyPart=[Visual,Root](FVector P,FVector S,const FString& Mesh)
        {
            auto* C=NewObject<UStaticMeshComponent>(Visual);Visual->AddInstanceComponent(C);C->SetupAttachment(Root);
            C->SetStaticMesh(LoadObject<UStaticMesh>(nullptr,*(TEXT("/Engine/BasicShapes/")+Mesh+TEXT(".")+Mesh)));
            C->SetMaterial(0,LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/Materials/MI_Red.MI_Red")));
            C->SetRelativeLocation(P);C->SetRelativeScale3D(S/100);C->SetCollisionEnabled(ECollisionEnabled::NoCollision);C->RegisterComponent();
        };
        BodyPart(FVector(0,0,0),FVector(75,43,32),"Sphere");
        BodyPart(FVector(62,0,2),FVector(30,30,30),"Sphere");
        for(int32 Side:{-1,1}){BodyPart(FVector(-60,Side*14,-4),FVector(90,20,24),"Sphere");BodyPart(FVector(0,Side*36,-5),FVector(74,16,18),"Sphere");}
        T.Visual=Visual;Targets.Add(T);
    }
}

void AMRWorld::SpawnAgents()
{
    const bool External=bCoreControlled||FParse::Param(FCommandLine::Get(),TEXT("MRExternalControl"));
    const int32 Drones=Scenario->GetIntegerField(TEXT("scouts")),Robots=Scenario->GetIntegerField(TEXT("rescuers"));
    const auto& Routes=Scenario->GetArrayField(TEXT("scout_waypoints"));
    for(int32 I=0;I<Drones+Robots;I++)
    {
        const bool Aerial=I<Drones;const int32 Id=Aerial?I:I-Drones;
        FVector P=Base+FVector((Id%2?1:-1)*250,(Id/2?1:-1)*230,Aerial?(bRescueQuarter?24:1900):60);
        if(Aerial&&bRescueQuarter)P=Base+FVector(-900,-900+Id*450,31);
        if(!Aerial&&bRescueQuarter)P=FVector(-1100+Id*330,200,95);
        TSharedPtr<FJsonObject> CitySpawn;FRotator Orientation=!Aerial&&bRescueQuarter?FRotator(0,-90,0):FRotator::ZeroRotator;
        if(bCityLayout)
        {
            int32 Seen=0;for(const auto& Entry:CityLayout->GetArrayField(TEXT("spawns")))
            {
                auto J=Entry->AsObject();if((J->GetStringField(TEXT("kind"))==TEXT("aerial"))!=Aerial)continue;
                if(Seen++==Id){CitySpawn=J;break;}
            }
            if(!CitySpawn){UE_LOG(LogTemp,Error,TEXT("MR_CITY missing physical spawn"));continue;}
            const auto& XYZ=CitySpawn->GetArrayField(TEXT("position"));P=FVector(XYZ[0]->AsNumber(),XYZ[1]->AsNumber(),XYZ[2]->AsNumber())*100;
            Orientation=FRotator(0,CitySpawn->GetNumberField(TEXT("yaw")),0);
        }
        auto* A=GetWorld()->SpawnActor<AMRAgent>(P,Orientation);
        TArray<FVector> Waypoints;
        if(Aerial&&!External&&Routes.IsValidIndex(Id))for(const auto& W:Routes[Id]->AsArray())
        {const auto& XY=W->AsArray();Waypoints.Add(FVector(XY[0]->AsNumber()*1000,XY[1]->AsNumber()*1000,bRescueQuarter?2200+Id*450:1900+Id*150));}
        if(Aerial&&bRescueQuarter&&!External){Waypoints.Add(FVector(P.X,P.Y,2200+Id*450));AppendEvent(TEXT("agent_takeoff_started"),Id);}
        A->Initialize(this,Id,Aerial,Waypoints);if(CitySpawn)A->PublicId=CitySpawn->GetStringField(TEXT("id"));
        if(Aerial&&External)A->State=TEXT("landed");Agents.Add(A);
    }
    if(bCityLayout)SpawnCompetitionUnits();
}

void AMRWorld::BeginPlay()
{
    Super::BeginPlay();
    auto* Session=UMRMissionSession::Get(GetWorld());
    if(Session&&Session->Enabled)
    {
        bRescueQuarter=true;bDemoDispatcherEnabled=false;
        if(Session->LayoutFile.IsEmpty()){SetActorTickEnabled(false);Session->BindWorld(this);return;}
    }
    int32 CorePort=0;bCoreControlled=FParse::Value(FCommandLine::Get(),TEXT("MRCorePort="),CorePort);
    if(Session&&Session->Enabled){bCoreControlled=true;CorePort=Session->Port;}
    if(bCoreControlled)bDemoDispatcherEnabled=false;
    MissionStartWall=FPlatformTime::Seconds();
    if(!ReadScenario())return;
    if(bCityLayout||Generated.IsEmpty())BuildScene();
    if(bCoreControlled&&!ReadCoreEventTape())
    {
        FPlatformMisc::RequestExitWithStatus(false,1);
        return;
    }
    if(bRescueQuarter)
    {
        DistrictMechanisms.Empty();TArray<UStaticMeshComponent*> Meshes;GetComponents(Meshes);
        for(auto* Mesh:Meshes)if(Mesh->Mobility==EComponentMobility::Movable&&!Mesh->ComponentHasTag(TEXT("FloodSurface")))
        {
            FMRAssemblyPart P;P.Mesh=Mesh;P.Rest=Mesh->GetRelativeTransform();
            if(Mesh->ComponentTags.Num()>1){P.Role=Mesh->ComponentTags[0].ToString();P.Name=Mesh->ComponentTags[1].ToString();}
            if(P.Name==TEXT("portable_generator"))P.Role=TEXT("generator_engine");
            P.Side=P.Name.EndsWith(TEXT("_-1"))?1:-1;P.Radius=36;
            if(P.Role==TEXT("beacon"))
            {
                Mesh->SetMaterial(0,LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/Effects/M_VanBeacon.M_VanBeacon")));
                Mesh->CreateAndSetMaterialInstanceDynamic(0);
            }
            DistrictMechanisms.Add(P);
        }
        TArray<USceneComponent*> Components;GetComponents(Components);
        for(auto* C:Components)if(C->ComponentHasTag(TEXT("MRAsset:Van"))){ServiceVan=C;VanPark=C->GetRelativeLocation();}
        if(ServiceVan)ServiceVan->SetRelativeLocation(VanPark+FVector(0,650,0));
    }
    IFileManager::Get().MakeDirectory(*(FPaths::ProjectSavedDir()/TEXT("Telemetry")),true);
    FFileHelper::SaveStringToFile(TEXT(""),*(FPaths::ProjectSavedDir()/TEXT("Telemetry/events.jsonl")));
    if(bRescueQuarter)FFileHelper::SaveStringToFile(TEXT(""),*(FPaths::ProjectSavedDir()/TEXT("Telemetry/frames.jsonl")));
    if(bRescueQuarter)FFileHelper::SaveStringToFile(TEXT(""),*(FPaths::ProjectSavedDir()/TEXT("Telemetry/public-frames.jsonl")));
    for(UProceduralMeshComponent* P:PhysicsPieces)
    {
        InitialPiecePositions.Add(P->GetComponentLocation());P->SetNotifyRigidBodyCollision(true);
        P->OnComponentHit.AddDynamic(this,&AMRWorld::OnRubbleHit);
        P->SetSimulatePhysics(!CollapsePieces.Contains(P));
    }
    bRuntimeReady=true;
    SpawnTargets();SpawnAgents();AppendEvent(TEXT("episode_started"));
    if(bRescueQuarter&&!bCoreControlled){InitializeEnvironment();InitializeTrafficProbe();}
    bCaptureFrames=FParse::Param(FCommandLine::Get(),TEXT("MRCaptureFrames"));
    FParse::Value(FCommandLine::Get(),TEXT("MRVisualProbe="),VisualProbe);
    FParse::Value(FCommandLine::Get(),TEXT("MRProbeWarmup="),ProbeWarmup);
    ProbeWarmup=FMath::IsFinite(ProbeWarmup)?FMath::Clamp(ProbeWarmup,0.f,120.f):0.f;
    if(bDecoratedCity&&VisualProbe==TEXT("city-assets"))PrepareCityAssetViews();
    if(bIrregularCity&&(VisualProbe==TEXT("city-buildings")||VisualProbe==TEXT("city-lumen")||
        VisualProbe==TEXT("city-glazing")||VisualProbe==TEXT("city-competition")))PrepareCityBuildingViews();
    bSmoke=FParse::Param(FCommandLine::Get(),TEXT("MRSmoke"));
    bPhotoTour=FParse::Param(FCommandLine::Get(),TEXT("MRPhotoTour"));
    bMechanicsProbe=FParse::Param(FCommandLine::Get(),TEXT("MRMechanicsProbe"));
    FParse::Value(FCommandLine::Get(),TEXT("MRQuitAfter="),QuitAfter);
    if(bCoreControlled)
    {
        CoreRuntime=MakeShared<FMRCoreRuntime>(this);
        if(!CoreRuntime->Start(CorePort))
        {UE_LOG(LogTemp,Error,TEXT("MR_CORE server failed to start"));CoreRuntime.Reset();FPlatformMisc::RequestExitWithStatus(false,1);}
        else if(Session&&Session->Enabled)Session->BindWorld(this);
    }
}

void AMRWorld::EndPlay(const EEndPlayReason::Type Reason)
{
    if(CoreRuntime){CoreRuntime->Stop();CoreRuntime.Reset();}
    Super::EndPlay(Reason);
}

void AMRWorld::ReleaseCollapse()
{
    if(bCollapseReleased)return;bCollapseReleased=true;
    if(bRescueQuarter)
    {
        TArray<UStaticMeshComponent*> Meshes;GetComponents(Meshes);FRandomStream Breaks(Seed+817);
        for(auto* M:Meshes)if(M->ComponentHasTag(TEXT("CollapseSupport")))
        {
            const FVector P=M->GetComponentLocation();M->SetCollisionEnabled(ECollisionEnabled::NoCollision);M->SetVisibility(false);
            for(int32 Side:{-1,1})Chunk(Breaks,P+FVector(0,Side*165,-15),FVector(45,300,40),true);
        }
    }
    for(UProceduralMeshComponent* P:CollapsePieces){P->SetSimulatePhysics(true);P->WakeAllRigidBodies();P->AddImpulse(FVector(2000,3500,0));}
    AppendEvent(TEXT("demo_collapse_released"));
}

void AMRWorld::OnRubbleHit(UPrimitiveComponent*,AActor*,UPrimitiveComponent*,FVector Impulse,const FHitResult&)
{if(Impulse.Size()>1)ContactCount++;}

int32 AMRWorld::FoundCount()const{int32 N=0;for(const auto& T:Targets)N+=T.bDiscovered;return N;}
int32 AMRWorld::SavedCount()const{int32 N=0;for(const auto& T:Targets)N+=T.bRescued;return N;}

void AMRWorld::SenseAndDispatch(float Dt)
{
    SensorClock+=Dt;if(SensorClock<.3f)return;SensorClock=0;
    for(auto& T:Targets)
    {
        if(T.bDiscovered)continue;
        const float Time=GetWorld()->GetTimeSeconds();
        if(Time<T.AvailableAt)continue;
        if(T.AvailableAt>0&&!T.bAvailabilityReported)
        {T.bAvailabilityReported=true;if(T.Visual)T.Visual->SetActorHiddenInGame(false);AppendEvent(TEXT("person_became_observable"),T.Id);}
        if(bRescueQuarter&&T.ObservedAt>=0)
        {
            for(AMRAgent* A:Agents)if(A->bAerial&&A->AgentId==T.Observer)T.ReportOrigin=A->GetActorLocation();
            if(HasRadio(T.ReportOrigin)&&Time-T.ObservedAt>.8)
            {T.bDiscovered=true;T.DiscoveredAt=Time;AppendEvent(TEXT("person_report_received"),T.Id);}
            continue;
        }
        for(AMRAgent* A:Agents)
        {
            if(!A->bAerial||A->Energy<=0||FVector::Dist2D(A->GetActorLocation(),T.Position)>SensorRange(A->GetActorLocation()))continue;
            FCollisionQueryParams Params;Params.AddIgnoredActor(A);
            FHitResult Hit;
            if(bRescueQuarter)
            {
                float Quality=1;
                for(float Along:{0.f,.25f,.5f,.75f,1.f})Quality=FMath::Min(Quality,VisibilityQuality(FMath::Lerp(A->GetActorLocation(),T.Position,Along)));
                FRandomStream SensorRng(HashCombineFast(GetTypeHash(T.Id),HashCombineFast(GetTypeHash(Seed),GetTypeHash(int32(Time/15)))));
                if(SensorRng.FRand()>.99f*Quality)continue;
            }
            if(!GetWorld()->LineTraceSingleByChannel(Hit,A->GetActorLocation(),T.Position+FVector(0,0,60),ECC_Visibility,Params))
            {
                if(bRescueQuarter){T.ObservedAt=Time;T.Observer=A->AgentId;T.ReportOrigin=A->GetActorLocation();}
                else {T.bDiscovered=true;T.DiscoveredAt=Time;}
                AppendEvent(TEXT("person_detected"),T.Id);break;
            }
        }
        if(bRescueQuarter&&T.ObservedAt<0)
        {
            TArray<FVector> Nodes;
            if(bCityLayout)for(const auto& Value:CityLayout->GetArrayField(TEXT("infrastructure")))
            {
                auto Node=Value->AsObject();if(Node->GetStringField(TEXT("kind"))!=TEXT("sensor_node"))continue;
                const auto& P=Node->GetArrayField(TEXT("position"));Nodes.Add(FVector(P[0]->AsNumber()*100,P[1]->AsNumber()*100,P[2]->AsNumber()*100));
            }
            else Nodes={FVector(-650,3600,240),FVector(10800,6100,240),FVector(11750,12200,240),FVector(11600,2550,240)};
            for(const FVector& Node:Nodes)
            {
                if(FVector::Dist2D(Node,T.Position)>2500)continue;
                FRandomStream SensorRng(HashCombineFast(GetTypeHash(T.Id),HashCombineFast(GetTypeHash(Seed+13),GetTypeHash(int32(Time/15)))));
                if(SensorRng.FRand()>.99f*FMath::Min(VisibilityQuality(Node),VisibilityQuality(T.Position)))continue;
                FHitResult Hit;
                if(!GetWorld()->LineTraceSingleByChannel(Hit,Node,T.Position+FVector(0,0,60),ECC_Visibility))
                {T.ObservedAt=Time;T.ReportOrigin=Node;T.Observer=-2;AppendEvent(TEXT("stationary_sensor_observed"),T.Id);break;}
            }
        }
    }
    // A deliberately small demo dispatcher. Runtime NSGA/controller integration is separate.
    if(bRescueQuarter&&!bDemoDispatcherEnabled)return;
    for(AMRAgent* A:Agents)
    {
        if(A->bAerial||!A->IsIdle()||A->Energy<10)continue;
        int32 Choice=-1;double Best=TNumericLimits<double>::Max();
        for(int32 I=0;I<Targets.Num();I++)
        {
            auto& T=Targets[I];if(!T.bDiscovered||T.bAssigned||T.bRescued||T.Path.IsEmpty())continue;
            double Length=0;for(int32 J=1;J<T.Path.Num();J++)Length+=FVector::Dist2D(T.Path[J-1],T.Path[J]);
            if(Length/1000*2>A->Energy-22)continue;
            if(Length<Best){Best=Length;Choice=I;}
        }
        if(Choice>=0)A->StartRescue(Choice);
    }
}

void AMRWorld::AppendEvent(const FString& Type,int32 Id)
{
    TSharedRef<FJsonObject> J=MakeShared<FJsonObject>();J->SetStringField(TEXT("type"),Type);
    J->SetNumberField(TEXT("time_s"),GetWorld()->GetTimeSeconds());
    J->SetNumberField(Type.StartsWith(TEXT("agent_"))?TEXT("agent_id"):TEXT("target_id"),Id);
    FString Text;FJsonSerializer::Serialize(J,TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Text));
    FFileHelper::SaveStringToFile(Text+TEXT("\n"),*(FPaths::ProjectSavedDir()/TEXT("Telemetry/events.jsonl")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,&IFileManager::Get(),FILEWRITE_Append);
    UE_LOG(LogTemp,Display,TEXT("MR event: %s"),*Text);
}

void AMRWorld::WriteTelemetry()
{
    TSharedRef<FJsonObject> J=MakeShared<FJsonObject>();J->SetStringField(TEXT("kind"),bRescueQuarter?TEXT("rescue_quarter_environment_demo"):TEXT("3d_physics_sandbox_debug"));
    J->SetNumberField(TEXT("time_s"),GetWorld()->GetTimeSeconds());J->SetNumberField(TEXT("seed"),Seed);
    J->SetNumberField(TEXT("discovered"),FoundCount());J->SetNumberField(TEXT("delivered"),SavedCount());
    J->SetNumberField(TEXT("contacts"),ContactCount);J->SetBoolField(TEXT("collapse_released"),bCollapseReleased);
    if(bCityLayout)
    {
        auto Summary=MakeShared<FJsonObject>();Summary->SetStringField(TEXT("format"),CityLayout->GetStringField(TEXT("format")));
        Summary->SetNumberField(TEXT("size_m"),CityLayout->GetNumberField(TEXT("size_m")));
        Summary->SetNumberField(TEXT("buildings"),CityLayout->GetArrayField(TEXT("buildings")).Num());
        Summary->SetNumberField(TEXT("initial_people"),CityLayout->GetArrayField(TEXT("people")).Num());
        Summary->SetNumberField(TEXT("features"),CityLayout->GetArrayField(TEXT("features")).Num());
        Summary->SetNumberField(TEXT("construction_wall_s"),CityBuildWallSeconds);
        int32 MeshComponents=0,Instances=0,NaniteInstances=0;TArray<UStaticMeshComponent*> Meshes;GetComponents(Meshes);
        for(auto* Mesh:Meshes)if(Mesh->GetStaticMesh())
        {
            MeshComponents++;const auto* Batch=Cast<UInstancedStaticMeshComponent>(Mesh);const int32 N=Batch?Batch->GetInstanceCount():1;
            Instances+=N;if(Mesh->GetStaticMesh()->HasValidNaniteData())NaniteInstances+=N;
        }
        Summary->SetNumberField(TEXT("mesh_components"),MeshComponents);Summary->SetNumberField(TEXT("mesh_instances"),Instances);
        Summary->SetNumberField(TEXT("nanite_instances"),NaniteInstances);
        if(bDecoratedCity)
        {
            auto PlantInstances=MakeShared<FJsonObject>(),PropInstances=MakeShared<FJsonObject>();
            int32 CoverBatches=0,YardColliders=0;
            const FString PlantPrefix=TEXT("CityVegetation:"),PropPrefix=TEXT("CityProp:");
            for(auto* Mesh:Meshes)for(FName Tag:Mesh->ComponentTags)
            {
                const FString Name=Tag.ToString();
                const bool IsPlant=Name.StartsWith(PlantPrefix);
                if(!IsPlant&&!Name.StartsWith(PropPrefix))continue;
                const auto* Batch=Cast<UInstancedStaticMeshComponent>(Mesh);
                const FString Id=Name.Mid(IsPlant?PlantPrefix.Len():PropPrefix.Len());
                auto& Counts=IsPlant?PlantInstances:PropInstances;
                double Count=0;Counts->TryGetNumberField(Id,Count);
                Counts->SetNumberField(Id,Count+(Batch?Batch->GetInstanceCount():1));
            }
            for(USceneComponent* Component:Generated)if(Component&&Component->IsRegistered())
            {
                if(Component->ComponentHasTag(TEXT("CityLotCover")))CoverBatches++;
                if(const auto* Box=Cast<UBoxComponent>(Component))
                    if(Box->IsCollisionEnabled()&&Box->GetCollisionResponseToChannel(ECC_Visibility)==ECR_Block)YardColliders++;
            }
            Summary->SetNumberField(TEXT("cover_batches"),CoverBatches);
            Summary->SetNumberField(TEXT("yard_colliders"),YardColliders);
            Summary->SetObjectField(TEXT("vegetation_instances"),PlantInstances);
            Summary->SetObjectField(TEXT("prop_instances"),PropInstances);
            if(ServiceVan)
            {
                Summary->SetNumberField(TEXT("van_travel_m"),VanWheelTravel/100.);
                Summary->SetNumberField(TEXT("van_distance_to_parking_m"),FVector::Dist(ServiceVan->GetComponentLocation(),VanPark)/100.);
            }
        }
        J->SetObjectField(TEXT("city_layout"),Summary);
    }
    if(bRescueQuarter)
    {
        J->SetNumberField(TEXT("pending_reports"),PendingReports());J->SetBoolField(TEXT("relay_online"),bRelayOnline);
        J->SetBoolField(TEXT("flood_active"),bFloodActive);J->SetBoolField(TEXT("dust_active"),bDustActive);
        J->SetNumberField(TEXT("flood_depth_cm"),WaterDepth(FVector(14500,12800,0)));
        J->SetNumberField(TEXT("average_game_fps"),ProfileFrames/FMath::Max(.001,ProfileSeconds));
        J->SetStringField(TEXT("time_step_mode"),FApp::UseFixedTimeStep()?TEXT("fixed_functional"):TEXT("real_time"));
        J->SetNumberField(TEXT("requested_fixed_fps"),FApp::UseFixedTimeStep()?1./FApp::GetFixedDeltaTime():0);
        J->SetNumberField(TEXT("model_delta_s_min"),ModelDeltaMin==MAX_flt?0:ModelDeltaMin);
        J->SetNumberField(TEXT("model_delta_s_max"),ModelDeltaMax);
        J->SetNumberField(TEXT("wall_elapsed_s"),FPlatformTime::Seconds()-MissionStartWall);
        J->SetNumberField(TEXT("render_wall_fps"),WarmStartWall>0?ProfileFrames/FMath::Max(.001,FPlatformTime::Seconds()-WarmStartWall):0);
        J->SetNumberField(TEXT("worst_frame_ms"),WorstFrameSeconds*1000);
        J->SetBoolField(TEXT("fire_effect_active"),FireEffect&&FireEffect->IsActive());
        J->SetBoolField(TEXT("leak_effect_active"),LeakEffect&&LeakEffect->IsActive());
        J->SetBoolField(TEXT("dust_effect_active"),DustEffect&&DustEffect->IsActive());
        J->SetStringField(TEXT("environment_mode"),Environment.Mode);J->SetNumberField(TEXT("event_seed"),Environment.Seed);
        J->SetNumberField(TEXT("world_revision"),Environment.Revision);J->SetNumberField(TEXT("events_applied"),Environment.Applied.Num());
        J->SetNumberField(TEXT("process_memory_mb"),FPlatformMemory::GetStats().UsedPhysical/1048576.);
        int32 Seen=0,P50=-1,P95=0;
        for(int32 I=0;I<1000;I++)
        {
            Seen+=ProfileMsHistogram[I];
            if(P50<0&&Seen>=ProfileFrames*.50)P50=I;
            if(Seen>=ProfileFrames*.95){P95=I;break;}
        }
        J->SetNumberField(TEXT("p50_frame_ms"),P50);J->SetNumberField(TEXT("p95_frame_ms"),P95);
        auto Counts=MakeShared<FJsonObject>();
        for(int32 K=0;K<8;K++)
        {int32 Count=0;for(const auto& E:Environment.Applied)if(int32(E.Kind)==K&&Environment.IsActive(E))Count++;Counts->SetNumberField(MRDisturbanceName(EMRDisturbance(K)),Count);}
        J->SetObjectField(TEXT("active_environment_events"),Counts);
        TArray<TSharedPtr<FJsonValue>> Samples;
        for(const auto& Site:EventSites)
        {
            auto Row=MakeShared<FJsonObject>();Row->SetStringField(TEXT("site_id"),Site.Id);
            Row->SetNumberField(TEXT("cost"),MovementCost(Site.Position));Row->SetNumberField(TEXT("depth_cm"),WaterDepth(Site.Position));
            Row->SetNumberField(TEXT("visibility"),VisibilityQuality(Site.Position));Row->SetBoolField(TEXT("blocked"),IsUnsafeGround(Site.Position));
            Samples.Add(MakeShared<FJsonValueObject>(Row));
        }
        J->SetArrayField(TEXT("surface_samples"),Samples);
        TArray<TSharedPtr<FJsonValue>> Effects;
        for(const auto& E:Environment.Applied)
        {
            auto Row=MakeShared<FJsonObject>();Row->SetStringField(TEXT("event_id"),E.Id);
            Row->SetStringField(TEXT("event_type"),MRDisturbanceName(E.Kind));
            Row->SetNumberField(TEXT("age_s"),Environment.Time-E.Time);Row->SetBoolField(TEXT("active"),Environment.IsActive(E));
            float Cost=1,Depth=0,Visibility=1;int32 Blocked=0,Visuals=0;
            TArray<TSharedPtr<FJsonValue>> CellSamples,VisualSamples;
            for(auto Cell:E.Cells)
            {
                const FVector P=FMRDistrictEnvironment::Center(Cell);
                Cost=FMath::Max(Cost,MovementCost(P));Depth=FMath::Max(Depth,WaterDepth(P));
                Visibility=FMath::Min(Visibility,VisibilityQuality(P));Blocked+=IsUnsafeGround(P);
                auto Sample=MakeShared<FJsonObject>();Sample->SetNumberField(TEXT("x"),Cell.X);Sample->SetNumberField(TEXT("y"),Cell.Y);
                Sample->SetNumberField(TEXT("cost"),MovementCost(P));Sample->SetNumberField(TEXT("depth_cm"),WaterDepth(P));
                Sample->SetNumberField(TEXT("visibility"),VisibilityQuality(P));Sample->SetBoolField(TEXT("blocked"),IsUnsafeGround(P));
                CellSamples.Add(MakeShared<FJsonValueObject>(Sample));
            }
            for(USceneComponent* C:HazardVisuals)if(C&&C->ComponentHasTag(FName(*E.Id)))
            {
                Visuals+=C->IsVisible();auto Sample=MakeShared<FJsonObject>();
                Sample->SetStringField(TEXT("kind"),C->ComponentTags.IsValidIndex(1)?C->ComponentTags[1].ToString():TEXT("unknown"));
                Sample->SetBoolField(TEXT("visible"),C->IsVisible());Sample->SetBoolField(TEXT("active"),C->IsActive());
                VisualSamples.Add(MakeShared<FJsonValueObject>(Sample));
            }
            if(const int32* Target=EventTargetIndices.Find(E.Id))
            {
                Row->SetNumberField(TEXT("target_id"),Targets[*Target].Id);Row->SetBoolField(TEXT("target_discovered"),Targets[*Target].bDiscovered);
                Row->SetNumberField(TEXT("target_observed_at"),Targets[*Target].ObservedAt);
                Row->SetBoolField(TEXT("target_visual_hidden"),!Targets[*Target].Visual||Targets[*Target].Visual->IsHidden());
                const bool Exists=IsValid(Targets[*Target].Visual);TArray<UMeshComponent*> Meshes;
                if(Exists)Targets[*Target].Visual->GetComponents(Meshes);
                Row->SetBoolField(TEXT("target_visual_exists"),Exists);Row->SetNumberField(TEXT("target_mesh_components"),Meshes.Num());
            }
            Row->SetArrayField(TEXT("cells"),CellSamples);Row->SetArrayField(TEXT("visual_components"),VisualSamples);
            Row->SetNumberField(TEXT("max_cost"),Cost);Row->SetNumberField(TEXT("max_depth_cm"),Depth);
            Row->SetNumberField(TEXT("min_visibility"),Visibility);Row->SetNumberField(TEXT("blocked_cells"),Blocked);
            Row->SetNumberField(TEXT("visible_components"),Visuals);Effects.Add(MakeShared<FJsonValueObject>(Row));
        }
        J->SetArrayField(TEXT("event_effect_samples"),Effects);
        auto Flood=MakeShared<FJsonObject>();int32 InsideBuildings=0;float Low=1000,High=-1000;
        for(const auto& Pair:FloodGroundHeights)
        {
            const FVector P((Pair.Key.X+.5)*50,(Pair.Key.Y+.5)*50,0);
            for(const auto& Box:StructureFootprints)if(Box.IsInsideXY(P)){InsideBuildings++;break;}
            Low=FMath::Min(Low,Pair.Value);High=FMath::Max(High,Pair.Value);
        }
        Flood->SetNumberField(TEXT("sample_count"),FloodGroundHeights.Num());Flood->SetNumberField(TEXT("inside_building_samples"),InsideBuildings);
        Flood->SetNumberField(TEXT("min_ground_cm"),Low);Flood->SetNumberField(TEXT("max_ground_cm"),High);
        J->SetObjectField(TEXT("flood_geometry_audit"),Flood);
    }
    TArray<TSharedPtr<FJsonValue>> Bodies;
    for(int32 I=0;I<PhysicsPieces.Num();I++)
    {
        UProceduralMeshComponent* P=PhysicsPieces[I];auto Row=MakeShared<FJsonObject>();
        Row->SetNumberField(TEXT("initial_z_cm"),InitialPiecePositions[I].Z);
        Row->SetBoolField(TEXT("collapse_piece"),CollapsePieces.Contains(P));
        Row->SetNumberField(TEXT("z_cm"),P->GetComponentLocation().Z);Row->SetBoolField(TEXT("simulating"),P->IsSimulatingPhysics());
        Row->SetNumberField(TEXT("speed_cm_s"),P->GetPhysicsLinearVelocity().Size());Bodies.Add(MakeShared<FJsonValueObject>(Row));
    }
    J->SetArrayField(TEXT("physics_bodies"),Bodies);TArray<TSharedPtr<FJsonValue>> Rows;
    for(AMRAgent* A:Agents)
    {
        // Pair the post-physics pose with movement and energy measured through
        // that exact pose, rather than the previous pre-physics drive tick.
        A->AccountExecutedMovement();
        auto Row=MakeShared<FJsonObject>();const FVector P=A->GetActorLocation();
        Row->SetNumberField(TEXT("id"),A->AgentId);Row->SetBoolField(TEXT("aerial"),A->bAerial);
        Row->SetStringField(TEXT("state"),A->State);Row->SetNumberField(TEXT("energy"),A->Energy);
        Row->SetNumberField(TEXT("x_cm"),P.X);Row->SetNumberField(TEXT("y_cm"),P.Y);Row->SetNumberField(TEXT("z_cm"),P.Z);
        Row->SetNumberField(TEXT("distance_cm"),A->DistanceTravelled);Row->SetBoolField(TEXT("simulating"),A->Body->IsSimulatingPhysics());Rows.Add(MakeShared<FJsonValueObject>(Row));
        if(bRescueQuarter)
        {
            Row->SetNumberField(TEXT("support_contacts"),A->GroundContacts);Row->SetNumberField(TEXT("mass_kg"),A->Body->GetMass());
            Row->SetBoolField(TEXT("route_blocked"),A->bRouteBlocked);
            Row->SetNumberField(TEXT("speed_cm_s"),A->Body->GetPhysicsLinearVelocity().Size());
            Row->SetNumberField(TEXT("yaw_deg"),A->GetActorRotation().Yaw);
            Row->SetNumberField(TEXT("rotor_rpm"),A->RotorRPM);Row->SetNumberField(TEXT("ramp_deployment"),A->RampDeployment);
            Row->SetBoolField(TEXT("radio_link"),HasRadio(P));Row->SetNumberField(TEXT("surface_speed_factor"),GroundSpeedFactor(P));
            Row->SetNumberField(TEXT("water_depth_cm"),WaterDepth(P));
            Row->SetStringField(TEXT("key"),A->AgentKey());Row->SetStringField(TEXT("kind"),A->Kind());
            Row->SetStringField(TEXT("command_id"),A->CommandId);
            Row->SetStringField(TEXT("stop_reason"),A->StopReason);Row->SetNumberField(TEXT("vehicle_contacts"),A->AgentContacts);
            Row->SetStringField(TEXT("stop_obstacle"),A->StopObstacle);
            Row->SetNumberField(TEXT("waypoint_x_cm"),A->ActiveWaypoint().X);
            Row->SetNumberField(TEXT("waypoint_y_cm"),A->ActiveWaypoint().Y);
            Row->SetBoolField(TEXT("carrying"),A->bCarrying);
        }
    }
    J->SetArrayField(TEXT("agents"),Rows);
    if(bMechanicsProbe)
    {
        TArray<TSharedPtr<FJsonValue>> ProbeRows;
        for(AMRAgent* A:MechanicsProbes)
        {
            auto Row=MakeShared<FJsonObject>();const FVector P=A->GetActorLocation();
            Row->SetNumberField(TEXT("id"),A->AgentId);Row->SetNumberField(TEXT("x_cm"),P.X);Row->SetNumberField(TEXT("y_cm"),P.Y);
            Row->SetNumberField(TEXT("z_cm"),P.Z);Row->SetNumberField(TEXT("speed_cm_s"),A->Body->GetPhysicsLinearVelocity().Size2D());
            Row->SetNumberField(TEXT("surface_factor"),GroundSpeedFactor(P));Row->SetNumberField(TEXT("distance_cm"),A->DistanceTravelled);
            Row->SetBoolField(TEXT("blocked"),A->bRouteBlocked);ProbeRows.Add(MakeShared<FJsonValueObject>(Row));
        }
        J->SetArrayField(TEXT("mechanics_probes"),ProbeRows);
    }
    FString Text;FJsonSerializer::Serialize(J,TJsonWriterFactory<>::Create(&Text));
    FFileHelper::SaveStringToFile(Text,*(FPaths::ProjectSavedDir()/TEXT("Telemetry/latest.json")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
    if(bRescueQuarter)
    {
        const FString Public=PublicObservationJson();
        FFileHelper::SaveStringToFile(Public,*(FPaths::ProjectSavedDir()/TEXT("Telemetry/public-observation.json")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
        FFileHelper::SaveStringToFile(Public+TEXT("\n"),*(FPaths::ProjectSavedDir()/TEXT("Telemetry/public-frames.jsonl")),
            FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,&IFileManager::Get(),FILEWRITE_Append);
    }
    if(bRescueQuarter)
    {
        FString Frame;FJsonSerializer::Serialize(J,TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Frame));
        FFileHelper::SaveStringToFile(Frame+TEXT("\n"),*(FPaths::ProjectSavedDir()/TEXT("Telemetry/frames.jsonl")),
            FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,&IFileManager::Get(),FILEWRITE_Append);
    }
}

void AMRWorld::Tick(float Dt)
{
    Super::Tick(Dt);if(!Scenario)return;
    if(bCoreControlled){if(CoreRuntime)CoreRuntime->BeforePhysics(Dt);return;}
    const float Time=GetWorld()->GetTimeSeconds();if(bRescueQuarter){TickDistrict(Dt);TickTrafficProbe();}SenseAndDispatch(Dt);
    if(bCaptureFrames&&Time>=28&&Time<=148)
    {
        CaptureClock+=Dt;
        if(CaptureClock>=.2f)
        {
            CaptureClock=0;
            const FString Folder=FPaths::ProjectSavedDir()/TEXT("Screenshots/Capture");IFileManager::Get().MakeDirectory(*Folder,true);
            FScreenshotRequest::RequestScreenshot(Folder/FString::Printf(TEXT("frame-%05d.png"),CaptureFrame++),true,false);
        }
    }
    if(bRescueQuarter&&Time>3)
    {
        if(WarmStartWall==0)WarmStartWall=FPlatformTime::Seconds();
        ModelDeltaMin=FMath::Min(ModelDeltaMin,Dt);ModelDeltaMax=FMath::Max(ModelDeltaMax,Dt);
        ProfileSeconds+=Dt;ProfileFrames++;WorstFrameSeconds=FMath::Max(WorstFrameSeconds,Dt);
        ProfileMsHistogram[FMath::Clamp(FMath::RoundToInt(Dt*1000),0,999)]++;
    }
    if(bRescueQuarter&&!EventInspections.IsEmpty()&&Time>=EventInspections[0].Time)
    {
        const auto& View=EventInspections[0];
        if(!bPhotoPending)
        {
            if(VisualProbe==TEXT("city-lumen"))
            {
                const bool MeshFields=View.Name.Contains(TEXT("mesh-fields"));
                const int32 LumenView=View.Name.Contains(TEXT("surface-cache"))?5:
                    View.Name.Contains(TEXT("indirect"))?13:0;
                if(auto* Viewport=GetWorld()->GetGameViewport())
                {
                    auto* Flags=Viewport->GetEngineShowFlags();
                    Flags->SetVisualizeMeshDistanceFields(MeshFields);
                    Flags->SetVisualizeLumen(LumenView!=0);
                }
                if(auto* Mode=IConsoleManager::Get().FindConsoleVariable(TEXT("r.Lumen.Visualize")))
                    Mode->Set(LumenView,ECVF_SetByCode);
                UE_LOG(LogTemp,Display,TEXT("MR_CITY_LIGHT_VIEW %s lumen=%d mesh_fields=%d"),*View.Name,LumenView,MeshFields);
            }
            for(TActorIterator<AMRCameraPawn> It(GetWorld());It;++It)It->SetInspectionView(View.Focus,View.Distance,View.Yaw,View.Pitch);
            bPhotoPending=true;PhotoRequestedAt=Time;
        }
        else if(Time>PhotoRequestedAt+View.SettleSeconds)
        {
            FScreenshotRequest::RequestScreenshot(FPaths::ProjectSavedDir()/TEXT("Screenshots")/(View.Name+TEXT(".png")),true,false);
            EventInspections.RemoveAt(0);bPhotoPending=false;
        }
    }
    if(bRescueQuarter&&VisualProbe==TEXT("windows"))
    {
        const float Times[]={3,8,13,18};
        const FString Names[]={TEXT("windows-exterior"),TEXT("windows-interior"),TEXT("windows-oblique"),TEXT("fault-inspection")};
        if(PhotoStage<4&&!bPhotoPending&&Time>Times[PhotoStage]+ProbeWarmup)
        {
            for(TActorIterator<AMRCameraPawn> It(GetWorld());It;++It)
            {
                if(PhotoStage==0)It->SetInspectionView(FVector(1850,1730,180),1200,90,-8);
                else if(PhotoStage==1)It->SetInspectionView(FVector(1900,1900,140),350,-90,-5);
                else if(PhotoStage==2)It->SetInspectionView(FVector(1850,1730,180),1100,50,-8);
                else It->SetInspectionView(FVector(7800,14500,-50),2400,-90,-48);
            }
            bPhotoPending=true;PhotoRequestedAt=Time;
        }
        else if(PhotoStage<4&&bPhotoPending&&Time>PhotoRequestedAt+2.5f)
        {
            FScreenshotRequest::RequestScreenshot(FPaths::ProjectSavedDir()/TEXT("Screenshots")/(Names[PhotoStage]+TEXT(".png")),true,false);
            PhotoStage++;bPhotoPending=false;
        }
    }
    else if(bRescueQuarter&&bPhotoTour&&VisualProbe.IsEmpty())
    {
        const float Times[]={5,12,38,88,96,104,122,140};
        const FString Names[]={TEXT("quarter-base"),TEXT("quarter-overview"),TEXT("quarter-collapse"),TEXT("quarter-water"),TEXT("quarter-tunnel"),TEXT("quarter-fire"),TEXT("quarter-street"),TEXT("quarter-vehicle")};
        if(PhotoStage<8&&!bPhotoPending&&Time>Times[PhotoStage])
        {
            for(TActorIterator<AMRCameraPawn> It(GetWorld());It;++It)It->SetPreset(PhotoStage);
            bPhotoPending=true;PhotoRequestedAt=Time;
        }
        else if(PhotoStage<8&&bPhotoPending&&Time>PhotoRequestedAt+.5f)
        {
            FScreenshotRequest::RequestScreenshot(FPaths::ProjectSavedDir()/TEXT("Screenshots")/(Names[PhotoStage]+TEXT(".png")),true,false);
            PhotoStage++;bPhotoPending=false;
        }
    }
    if(!bRescueQuarter&&Time>18&&!bCollapseReleased)ReleaseCollapse();
    TelemetryClock+=Dt;if(TelemetryClock>=2){WriteTelemetry();TelemetryClock=0;}
    if(bSmoke&&Time>2&&!bStartScreenshotTaken)
    {IFileManager::Get().MakeDirectory(*(FPaths::ProjectSavedDir()/TEXT("Screenshots")),true);
     FScreenshotRequest::RequestScreenshot(FPaths::ProjectSavedDir()/TEXT("Screenshots/scene-start.png"),true,false);bStartScreenshotTaken=true;}
    if(bSmoke&&Time>26&&!bScreenshotTaken)
    {IFileManager::Get().MakeDirectory(*(FPaths::ProjectSavedDir()/TEXT("Screenshots")),true);
     FScreenshotRequest::RequestScreenshot(FPaths::ProjectSavedDir()/TEXT("Screenshots/physics-smoke.png"),true,false);bScreenshotTaken=true;}
    if(QuitAfter>0&&Time>QuitAfter){WriteTelemetry();FGenericPlatformMisc::RequestExit(false);}
}
