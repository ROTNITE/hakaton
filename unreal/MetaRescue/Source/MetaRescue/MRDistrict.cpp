#include "MRWorld.h"
#include "MRBuildingWindows.h"
#include "Components/StaticMeshComponent.h"
#include "Components/BoxComponent.h"
#include "Components/TextRenderComponent.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "ProceduralMeshComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/SpotLightComponent.h"
#include "Engine/World.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "StaticMeshResources.h"

USceneComponent* AMRWorld::DistrictAssembly(const FString& Name,const FVector& P,const FRotator& R,
    const FVector& S,bool Collision,bool Movable,const FString& Module)
{
    TArray<FMRAssemblyPart> Parts;
    auto* Root=MRBuildAssembly(this,GetRootComponent(),Name,P,R,S,Collision,Movable,Parts,Module,bCityLayout,bBuildingCity);
    if(Root)Generated.Add(Root);
    for(auto& Part:Parts){Generated.Add(Part.Mesh);if(Movable)DistrictMechanisms.Add(Part);}
    return Root;
}

USceneComponent* AMRWorld::GroundedAssembly(const FString& Name,const FVector& P,const FRotator& R,
    const FVector& S,const FString& Module,bool Collision)
{
    if(Name==TEXT("Beam"))
    {
        auto* C=DistrictMesh(Name,P,R,S,Collision);
        if(C)C->AddWorldOffset(FVector(0,0,P.Z-(C->Bounds.Origin.Z-C->Bounds.BoxExtent.Z)));
        return C;
    }
    auto* Root=DistrictAssembly(Name,P,R,S,Collision,false,Module);
    if(!Root)return nullptr;
    TArray<USceneComponent*> Descendants;Root->GetChildrenComponents(true,Descendants);
    double Bottom=TNumericLimits<double>::Max();TArray<FVector> SurfacePoints;
    for(auto* C:Descendants)if(auto* M=Cast<UStaticMeshComponent>(C))
    {
        const UStaticMesh* Mesh=M->GetStaticMesh();
        if(!Mesh)continue;
        const auto* Data=Mesh->GetRenderData();
        const auto* Positions=Data&&Data->LODResources.Num()?
            &Data->LODResources[0].VertexBuffers.PositionVertexBuffer:nullptr;
        const bool bCpuPositions=Positions&&Positions->GetAllowCPUAccess()&&Positions->GetVertexData();
#if !WITH_EDITOR
        static TSet<const UStaticMesh*> Reported;
        if(!Reported.Contains(Mesh))
        {
            Reported.Add(Mesh);
            if(bCpuPositions)
            {
                UE_LOG(LogTemp,Display,TEXT("MR_GROUND_CPU %s vertices=%u"),*Mesh->GetPathName(),Positions->GetNumVertices());
            }
            else
            {
                UE_LOG(LogTemp,Warning,TEXT("MR_GROUND_BOUNDS %s"),*Mesh->GetPathName());
            }
        }
#endif
        if(bCpuPositions)
        {
            for(uint32 I=0;I<Positions->GetNumVertices();I++)
            {
                const FVector Point=M->GetComponentTransform().TransformPosition(FVector(Positions->VertexPosition(I)));
                Bottom=FMath::Min(Bottom,Point.Z);
                if(Name==TEXT("Slab"))SurfacePoints.Add(Point);
            }
        }
        else
        {
            const auto Bounds=M->CalcBounds(M->GetComponentTransform());
            Bottom=FMath::Min(Bottom,Bounds.Origin.Z-Bounds.BoxExtent.Z);
        }
    }
    if(Bottom<TNumericLimits<double>::Max())Root->AddWorldOffset(FVector(0,0,P.Z-Bottom));
    if(Name==TEXT("Slab")&&!SurfacePoints.IsEmpty())
    {
        // Grounding the lowest vertex alone leaves a tilted panel balancing on
        // one edge. Derive actual low surface points in four quadrants, then
        // build tapered masonry directly under those contacts.
        int32 Contacts=0;
        for(int32 SX:{-1,1})for(int32 SY:{-1,1})
        {
            FVector Contact;bool Found=false;
            for(FVector Point:SurfacePoints)
                if((Point.X-P.X)*SX>15&&(Point.Y-P.Y)*SY>15&&(!Found||Point.Z<Contact.Z))
                {Contact=Point;Found=true;}
            if(!Found)continue;
            Contact.Z+=P.Z-Bottom;Contacts++;
            const float Gap=Contact.Z-P.Z;
            if(Gap<3)continue;
            auto* Support=NewObject<UProceduralMeshComponent>(this);AddInstanceComponent(Support);Support->SetupAttachment(GetRootComponent());
            Support->SetRelativeLocation(FVector(Contact.X,Contact.Y,P.Z));Support->bUseComplexAsSimpleCollision=false;
            Support->SetCollisionProfileName(TEXT("BlockAll"));
            if(!bBuildingCity)Support->RegisterComponent();
            const TArray<FVector> Corners={FVector(-28,-24,0),FVector(25,-27,0),FVector(30,24,0),FVector(-25,28,0),
                FVector(-8,-8,Gap),FVector(8,-8,Gap),FVector(8,8,Gap),FVector(-8,8,Gap)};
            const int32 Faces[6][4]={{0,3,2,1},{4,5,6,7},{0,1,5,4},{1,2,6,5},{2,3,7,6},{3,0,4,7}};
            TArray<FVector> V,N;TArray<FVector2D> UV;TArray<int32> Tri;
            for(const auto& Face:Faces)
            {
                const int32 I=V.Num();const FVector Normal=FVector::CrossProduct(Corners[Face[1]]-Corners[Face[0]],Corners[Face[2]]-Corners[Face[0]]).GetSafeNormal();
                for(int32 J=0;J<4;J++){V.Add(Corners[Face[J]]);N.Add(Normal);UV.Add(FVector2D(J==1||J==2?1:0,J>1?1:0));}
                Tri.Append({I,I+2,I+1,I,I+3,I+2});
            }
            Support->CreateMeshSection_LinearColor(0,V,Tri,N,UV,{}, {},false);Support->AddCollisionConvexMesh(Corners);
            Support->SetMaterial(0,MRSceneMaterial(LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/Materials/MI_Concrete.MI_Concrete"))));
            Support->ComponentTags={TEXT("SlabMasonrySupport"),FName(*FString::Printf(TEXT("ContactGapCm:%.2f"),Gap))};Generated.Add(Support);
        }
        Root->ComponentTags.Add(FName(*FString::Printf(TEXT("SlabSupportContacts:%d"),Contacts)));
    }
    Root->ComponentTags.Add(TEXT("GroundedAssembly"));return Root;
}
void AMRWorld::GroundedChunk(FRandomStream& Rng,const FVector& P,const FVector& S,bool Physics)
{
    auto* C=Chunk(Rng,P,S,Physics);
    const auto* Section=C->GetProcMeshSection(0);
    double Bottom=TNumericLimits<double>::Max();
    if(Section)for(const auto& V:Section->ProcVertexBuffer)
        Bottom=FMath::Min(Bottom,C->GetComponentTransform().TransformPosition(V.Position).Z);
    C->AddWorldOffset(FVector(0,0,P.Z-Bottom));C->ComponentTags.Add(TEXT("GroundedDebris"));
}
void AMRWorld::Apartment(const FVector& P,int32 Floors,int32 Variant,int32 Damage)
{
    StructureFootprints.Add(FBox(P-FVector(475,475,24),P+FVector(475,475,Floors*300+70)));
    if(Damage==5)Floors=1;
    if(Damage==3)Floors=FMath::Max(2,Floors-1);
    if(Damage>=4)
    {
        auto* Ruin=GroundedAssembly(TEXT("BuildingVariants"),P,FRotator(0,(Variant%4)*90,0),FVector(.9,.9,1),
            Damage==4?TEXT("ruin_full"):TEXT("ruin_low"));
        if(Ruin)
        {
            TArray<USceneComponent*> Parts;Ruin->GetChildrenComponents(true,Parts);
            for(auto* Part:Parts)if(auto* Mesh=Cast<UStaticMeshComponent>(Part))
                Mesh->ComponentTags.Add(FName(*FString::Printf(TEXT("BuildingVariant:%d"),Damage)));
        }
        FRandomStream Local(Variant*831);
        GroundedAssembly(TEXT("Rubble"),P+FVector(0,-465,0),FRotator(0,Variant*41,0),FVector(.58,.6,.65));
        for(int32 I=0;I<24;I++)GroundedAssembly(TEXT("SceneryKit"),P+FVector(Local.FRandRange(-440,440),Local.FRandRange(-580,-430),0),
            FRotator(Local.FRandRange(-10,10),Local.FRandRange(-180,180),Local.FRandRange(-12,12)),FVector::OneVector,
            FString::Printf(TEXT("fragment_%d"),I%4));
        return;
    }
    auto Interior=[](UStaticMeshComponent* Surface)
    {Surface->ComponentTags.Add(TEXT("InteriorLightingSurface"));return Surface;};
    auto* Foundation=Interior(Shape("Cube",P+FVector(0,0,8),FVector(900,900,16),"MI_Concrete"));
    Foundation->ComponentTags.Add(FName(*FString::Printf(TEXT("BuildingVariant:%d"),Damage)));
    for(int32 Level=0;Level<Floors;Level++)
    {
        const float Z=Level*300;
        const bool BrokenTop=Damage>=2&&Level==Floors-1;
        if(Level>0)
        {
            if(BrokenTop&&Damage==2)
            {
                Interior(Shape("Cube",P+FVector(-150,0,Z+8),FVector(600,900,16),"MI_Concrete"));
                Interior(Shape("Cube",P+FVector(300,150,Z+8),FVector(300,600,16),"MI_Concrete"));
                for(int32 I=0;I<6;I++)
                    Shape("Cylinder",P+FVector(165,-400+I*45,Z+7),FVector(2,2,90),"MI_Rust",FRotator(90,0,0),false);
            }
            else Interior(Shape("Cube",P+FVector(0,0,Z+8),FVector(900,900,16),"MI_Concrete"));
        }
        Interior(Shape("Cube",P+FVector(0,70,Z+147),FVector(15,720,278),"M_QuarterInterior"));
        if(!BrokenTop)Interior(Shape("Cube",P+FVector(60,160,Z+147),FVector(740,12,278),"M_QuarterInterior"));
        for(int32 Side=0;Side<4;Side++)for(int32 Bay=0;Bay<3;Bay++)
        {
            const bool Missing=BrokenTop&&((Damage==2&&(Side==0&&Bay==2||Side==1&&Bay==0))||
                (Damage==3&&Side==1)||(Damage==4&&Side<2)||(Damage==5&&(Side+Bay)%3==0));
            if(Missing)continue;
            const FRotator Turn(0,Side*90,0);
            const FVector At=P+Turn.RotateVector(FVector((Bay-1)*300,-450,Z+16));
            if(Damage==1&&Level==1&&Side==0&&Bay==2)
            {
                // Local facade failure leaves masonry and the jambs; the rest
                // of the load-bearing building remains intact.
                DistrictAssembly("SceneryKit",At,Turn,FVector(1.45,1,1),true,false,"fragment_4");
                Shape("Cube",At+FVector(-125,0,145),FVector(35,24,290),"MI_Concrete");
                Shape("Cube",At+FVector(125,0,145),FVector(35,24,290),"MI_Concrete");
                continue;
            }
            const bool Door=Level==0&&Bay==1&&Side==0;
            const int32 Window=1+(Bay+Side+Variant)%3;
            const FString Wall=Door?TEXT("wall_door_centered_small_01"):
                FString::Printf(TEXT("wall_window_centered_large_0%d"),Window);
            DistrictAssembly("UrbanKit",At,Turn,FVector::OneVector,true,false,Wall);
            if(Door)DistrictAssembly("UrbanKit",At,Turn,FVector::OneVector,true,false,"door_centered_small_01");
            else
            {
                const TCHAR* Style=MRApartmentWindowStyle(Damage,Variant,Level,Side,Bay);
                const float OffsetZ=Window==1?0:Window==2?30:40;
                DistrictAssembly("GlazingKit",At+Turn.RotateVector(FVector(0,-4,OffsetZ)),Turn,FVector::OneVector,
                    false,false,FString::Printf(TEXT("window_0%d_%s"),Window,Style));
                // Sill and a dark reveal keep a readable thickness from either side.
                Shape("Cube",At+Turn.RotateVector(FVector(0,1,45)),FVector(180,35,8),"MI_Concrete",Turn);
            }
            if(!BrokenTop)DistrictAssembly("UrbanKit",P+Turn.RotateVector(FVector((Bay-1)*300,-457,Z+288)),Turn,
                FVector::OneVector,false,false,"cornice_standard_standard_01");
            if(Level==0)DistrictAssembly("UrbanKit",At,Turn,FVector::OneVector,true,false,"base_standard_01");
        }
        for(int32 Room:{-1,1})
            DistrictAssembly("SceneryKit",P+FVector(Room*210,-150,Z+16),FRotator(0,Variant%2*180,0),
                FVector::OneVector,false,false,FString::Printf(TEXT("room_%d"),(Variant+Level+Room+3)%3));
        // Low skirting and lintels give the rooms readable edge thickness,
        // rather than three bare planes immediately behind the window.
        Shape("Cube",P+FVector(0,-420,Z+24),FVector(850,8,14),"MI_Plaster",FRotator::ZeroRotator,false);
        if(Damage<2||Level<Floors-1)
            Interior(Shape("Cube",P+FVector(0,0,Z+297),FVector(900,900,14),"M_QuarterInterior"));
    }
    if(Damage<2)
    {
        Shape("Cube",P+FVector(0,0,Floors*300+12),FVector(945,945,24),"MI_Dark");
        for(int32 Side:{-1,1})
        {
            Shape("Cube",P+FVector(Side*460,0,Floors*300+34),FVector(18,925,44),"MI_Concrete");
            Shape("Cube",P+FVector(0,Side*460,Floors*300+34),FVector(925,18,44),"MI_Concrete");
        }
        DistrictAssembly("SceneryKit",P+FVector((Variant%2?1:-1)*210,130,Floors*300+24),
            FRotator(0,(Variant%4)*90,0),FVector::OneVector,true,false,"roof_vent");
    }
    if(Damage==3)
    {
        // Remnants of the lost storey distinguish this from a roof simply
        // removed from a complete cube. Broken stubs expose reinforcement.
        const float Z=Floors*300;
        for(int32 I=0;I<5;I++)
        {
            DistrictAssembly("SceneryKit",P+FVector(-350+I*175,430,Z),FRotator(0,180,0),
                FVector(.85,1,.55+(I%3)*.2),true,false,"fragment_4");
            Shape("Cylinder",P+FVector(-350+I*175,420,Z+110),FVector(3,3,140),"MI_Rust",FRotator(5,0,0),false);
        }
        GroundedAssembly("Slab",P+FVector(140,-120,16),FRotator(5,Variant*27,4),FVector(.55));
    }
    if(Damage>0)
    {
        FRandomStream Local(Variant*871+Damage*17+int32(P.X+P.Y));
        const int32 Count=Damage==1?5:18;
        for(int32 I=0;I<Count;I++)
        {
            const FVector At=P+FVector(Local.FRandRange(-420,420),Local.FRandRange(-580,-440),0);
            GroundedAssembly("SceneryKit",At,FRotator(Local.FRandRange(-18,18),Local.FRandRange(-180,180),Local.FRandRange(-15,15)),
                FVector(Local.FRandRange(.8,1.5)),FString::Printf(TEXT("fragment_%d"),I%4));
        }
        if(Damage>=2)
            GroundedAssembly("Rubble",P+FVector(270,-430,0),FRotator(0,Variant*51,0),FVector(.5,.48,.45));
    }
}

UStaticMeshComponent* AMRWorld::DistrictMesh(const FString& Name, const FVector& P,
    const FRotator& R, const FVector& Scale, bool Collision)
{
    static const TSet<FString> Library={"Building","WindowWall","Stretcher","Medical","Dock","Relay","Sensor","Barrier","Slab","Doorway","Rubble","Streetlight","UtilityBox","Manhole","Generator","Van","Case","MannequinStatic"};
    if(Library.Contains(Name))
    {
        const bool Moving=Name=="Sensor"||Name=="Generator"||Name=="Case"||Name=="Van";
        auto* Root=DistrictAssembly(Name,P,R,Scale,Collision,Moving);
        if(Name=="Van"){ServiceVan=Root;VanPark=P;}
        if(Root)for(USceneComponent* Child:Root->GetAttachChildren())if(auto* Mesh=Cast<UStaticMeshComponent>(Child))return Mesh;
        return nullptr;
    }
    if(Name=="Lamp")return DistrictMesh("Streetlight",P,R,Scale,Collision);
    if(Name=="Crate")return DistrictMesh("Case",P,R,Scale,Collision);
    if(Name=="Fence")
    {
        auto* Root=DistrictAssembly("FenceKit",P,R,Scale,Collision,false,"modular_chainlink_fence_double");
        DistrictAssembly("FenceKit",P+R.RotateVector(FVector(-100,0,0)),R,Scale,Collision,false,"modular_chainlink_fence_post");
        if(Root)for(USceneComponent* Child:Root->GetAttachChildren())if(auto* Mesh=Cast<UStaticMeshComponent>(Child))return Mesh;
        return nullptr;
    }
    const bool User=Name=="Building"||Name=="WindowWall"||Name=="Rover"||Name=="Drone"||Name=="Stretcher";
    const FString Path=FString::Printf(TEXT("/Game/RescueAssets/%s/%s/SM_%s.SM_%s"),
        User?TEXT("User"):TEXT("Authored"),*Name,*Name,*Name);
    auto* Mesh=LoadObject<UStaticMesh>(nullptr,*Path);
    if(!Mesh){UE_LOG(LogTemp,Error,TEXT("MR missing prepared district asset: %s"),*Path);return nullptr;}
    auto* C=NewObject<UStaticMeshComponent>(this);
    AddInstanceComponent(C);C->SetupAttachment(GetRootComponent());C->SetStaticMesh(Mesh);
    C->SetMobility(EComponentMobility::Static);C->SetRelativeLocation(P);C->SetRelativeRotation(R);C->SetRelativeScale3D(Scale);
    C->SetCollisionEnabled(Collision?ECollisionEnabled::QueryAndPhysics:ECollisionEnabled::NoCollision);
    C->SetCollisionProfileName(Collision?TEXT("BlockAll"):TEXT("NoCollision"));
    C->RegisterComponent();Generated.Add(C);return C;
}

void AMRWorld::DistrictLabel(const FString& Text,const FVector& P,float Size)
{
    auto* C=NewObject<UTextRenderComponent>(this);AddInstanceComponent(C);C->SetupAttachment(GetRootComponent());
    C->SetMobility(EComponentMobility::Static);C->SetRelativeLocation(P);C->SetRelativeRotation(FRotator(0,-135,0));
    C->SetText(FText::FromString(Text));C->SetWorldSize(Size);C->SetHorizontalAlignment(EHTA_Center);
    if(Text.StartsWith(TEXT("ELECTRICAL")))C->SetRelativeRotation(FRotator(0,45,0));
    C->SetTextRenderColor(FColor(220,232,215));C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    C->SetHiddenInGame(true);
    C->RegisterComponent();Generated.Add(C);
}

void AMRWorld::BuildDistrict()
{
    FRandomStream Rng(Seed);
    const auto* LegacyBarrier=LoadObject<UStaticMesh>(nullptr,
        TEXT("/Game/RescueAssets/Library/Barrier/SM_concrete_road_barrier_02_LOD0.SM_concrete_road_barrier_02_LOD0"));
    const auto* JerseyBarrier=LoadObject<UStaticMesh>(nullptr,
        TEXT("/Game/RescueAssets/LibraryV3/JerseyBarrierV2/SM_JerseyBarrierV2.SM_JerseyBarrierV2"));
    const auto ClosureBarrier=[&](const FVector& P,const FRotator& R=FRotator::ZeroRotator)
    {
        if(LegacyBarrier&&JerseyBarrier)
        {
            const FBox Legacy=LegacyBarrier->GetBoundingBox(),Jersey=JerseyBarrier->GetBoundingBox();
            const FVector Scale=Legacy.GetSize()/Jersey.GetSize();
            // Existing Barrier module translation from library-v3.json, converted to Unreal cm.
            const FVector LegacyOffset(.652769,-3.297798,-.279442);
            const FVector Shift=LegacyOffset+Legacy.GetCenter()-Jersey.GetCenter()*Scale;
            if(DistrictAssembly(TEXT("JerseyBarrierV2"),P+R.RotateVector(Shift),R,Scale,true))return;
        }
        DistrictMesh(TEXT("Barrier"),P,R);
    };
    // Continuous physical ground, with a large quiet surround instead of a floating board edge.
    const auto GroundSupport=[&](const FVector& Center,const FVector& Size,const FString& Material)
    {
        // Keep queryable support at the authored dimensions, independent of the
        // render mesh and its scale.
        Shape(TEXT("Cube"),Center,Size,Material,FRotator::ZeroRotator,false);
        auto* Surface=NewObject<UBoxComponent>(this);
        AddInstanceComponent(Surface);Surface->SetupAttachment(GetRootComponent());
        Surface->SetMobility(EComponentMobility::Static);
        Surface->SetRelativeLocation(Center);Surface->SetBoxExtent(Size*.5,false);
        Surface->SetCollisionProfileName(TEXT("BlockAll"));
        Surface->ComponentTags.Add(TEXT("QuarterGroundSupport"));
        Surface->RegisterComponent();Generated.Add(Surface);
    };
    GroundSupport(FVector(7500,7500,-350),FVector(150000,150000,120),TEXT("MI_Ground"));
    // Eight ground regions leave a genuine opening down to the soil below.
    const float GroundX[]={-7000,6800,8800,22000},GroundY[]={-7000,14075,14925,22000};
    for(int32 X=0;X<3;X++)for(int32 Y=0;Y<3;Y++)
        if(X!=1||Y!=1)GroundSupport(FVector((GroundX[X]+GroundX[X+1])*.5,(GroundY[Y]+GroundY[Y+1])*.5,-15),
            FVector(GroundX[X+1]-GroundX[X],GroundY[Y+1]-GroundY[Y],28),"MI_Concrete");
    const TArray<float> Streets={1000,5500,10000,14500};
    for(float Center:Streets)
    {
        GroundSupport(FVector(Center,7500,-2),FVector(850,29000,12),"M_QuarterAsphalt");
        float SegmentStart=-7000;
        for(int32 Segment=0;Segment<=Streets.Num();Segment++)
        {
            const float SegmentEnd=Segment<Streets.Num()?Streets[Segment]-425:22000;
            if(SegmentEnd>SegmentStart)
            {
                if(Center==14500&&SegmentStart<8800&&SegmentEnd>6800)
                {
                    if(SegmentStart<6800)GroundSupport(FVector((SegmentStart+6800)*.5,Center,-2),FVector(6800-SegmentStart,850,12),"M_QuarterAsphalt");
                    if(SegmentEnd>8800)GroundSupport(FVector((8800+SegmentEnd)*.5,Center,-2),FVector(SegmentEnd-8800,850,12),"M_QuarterAsphalt");
                }
                else GroundSupport(FVector((SegmentStart+SegmentEnd)*.5,Center,-2),FVector(SegmentEnd-SegmentStart,850,12),"M_QuarterAsphalt");
            }
            if(Segment<Streets.Num())SegmentStart=Streets[Segment]+425;
        }
        for(int32 I=0;I<48;I++)
        {
            const float Along=-1600+I*400;
            bool Intersection=false;for(float Cross:Streets)Intersection|=FMath::Abs(Along-Cross)<650;
            if(!Intersection)
            {
                Shape("Cube",FVector(Center,Along,6),FVector(9,170,2),"MI_Paint",FRotator::ZeroRotator,false);
                if(!(Center==14500&&Along>6700&&Along<8900))Shape("Cube",FVector(Along,Center,7),FVector(170,9,2),"MI_Paint",FRotator::ZeroRotator,false);
            }
        }
    }
    // Exposed subgrade, broken asphalt lips and a damaged utility crossing.
    GroundSupport(FVector(7800,14500,-282),FVector(2000,850,16),"MI_Ground");
    Shape("Cylinder",FVector(7800,14500,-140),FVector(65,65,2200),"MI_Rust",FRotator(90,0,0));
    // Static triangle collision follows the fractured rim. No single convex
    // proxy spans this concave opening, and the interior remains an actual fall.
    auto FaultBand=[&](bool AlongX,int32 Side)
    {
        TArray<FVector> Top,NTop,Soil,NSoil;TArray<FVector2D> UVTop,UVSoil;TArray<int32> TTop,TSoil;
        auto Quad=[](TArray<FVector>& V,TArray<FVector>& N,TArray<FVector2D>& UV,TArray<int32>& T,
            FVector A,FVector B,FVector C,FVector D,bool Up)
        {
            if(Up&&FVector::CrossProduct(B-A,C-A).Z<0)Swap(B,D);
            const FVector Normal=FVector::CrossProduct(B-A,C-A).GetSafeNormal();const int32 Start=V.Num();
            for(FVector P:{A,B,C,D}){V.Add(P);N.Add(Normal);UV.Add(FVector2D(P.X/150,P.Y/150));}
            T.Append({Start,Start+2,Start+1,Start,Start+3,Start+2});
        };
        const int32 Count=AlongX?18:9;
        const float Start=AlongX?6800:14075,End=AlongX?8800:14925;
        const float Rim=AlongX?(Side<0?14075:14925):(Side<0?6800:8800);
        TArray<FVector> Outer,Inner;
        for(int32 I=0;I<=Count;I++)
        {
            const float Along=FMath::Lerp(Start,End,float(I)/Count);
            const float Fracture=Rng.FRandRange(20,105);
            Outer.Add(AlongX?FVector(Along,Rim+Side*20,4):FVector(Rim+Side*20,Along,4));
            Inner.Add(AlongX?FVector(Along,Rim-Side*Fracture,Rng.FRandRange(-4,8)):
                FVector(Rim-Side*Fracture,Along,Rng.FRandRange(-4,8)));
        }
        for(int32 I=0;I<Count;I++)
        {
            Quad(Top,NTop,UVTop,TTop,Outer[I],Outer[I+1],Inner[I+1],Inner[I],true);
            Quad(Top,NTop,UVTop,TTop,Inner[I],Inner[I+1],Inner[I+1]-FVector(0,0,22),Inner[I]-FVector(0,0,22),false);
            const FVector A=Inner[I]-FVector(0,0,22),B=Inner[I+1]-FVector(0,0,22);
            const FVector BottomA=AlongX?FVector(A.X,A.Y-Side*65,-274):FVector(A.X-Side*65,A.Y,-274);
            const FVector BottomB=AlongX?FVector(B.X,B.Y-Side*65,-274):FVector(B.X-Side*65,B.Y,-274);
            Quad(Soil,NSoil,UVSoil,TSoil,A,B,BottomB,BottomA,false);
        }
        auto* Band=NewObject<UProceduralMeshComponent>(this);AddInstanceComponent(Band);Band->SetupAttachment(GetRootComponent());
        Band->bUseComplexAsSimpleCollision=true;Band->bUseAsyncCooking=false;Band->SetCollisionProfileName(TEXT("BlockAll"));Band->RegisterComponent();
        Band->CreateMeshSection_LinearColor(0,Top,TTop,NTop,UVTop,{}, {},true);
        Band->CreateMeshSection_LinearColor(1,Soil,TSoil,NSoil,UVSoil,{}, {},true);
        Band->SetMaterial(0,MRSceneMaterial(LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/Materials/M_QuarterAsphalt.M_QuarterAsphalt"))));
        Band->SetMaterial(1,MRSceneMaterial(LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/Materials/MI_Ground.MI_Ground"))));
        Band->ComponentTags={TEXT("FracturedFaultRim"),TEXT("ExactStaticCollision")};Generated.Add(Band);
    };
    for(int32 Side:{-1,1}){FaultBand(true,Side);FaultBand(false,Side);}
    for(int32 I=0;I<21;I++)
        GroundedChunk(Rng,FVector(Rng.FRandRange(6950,8650),Rng.FRandRange(14240,14750),-274),
            FVector(Rng.FRandRange(45,150),Rng.FRandRange(40,110),Rng.FRandRange(20,50)));
    for(int32 Side:{-1,1})for(int32 I=0;I<3;I++)
        ClosureBarrier(FVector(Side<0?6500:9100,14200+I*270,4),FRotator(0,90,0));
    // Urban blocks are filled, while wide real streets remain clear for evacuation.
    for(int32 BX=0;BX<3;BX++)for(int32 BY=0;BY<3;BY++)
    {
        const FVector Middle((Streets[BX]+Streets[BX+1])*.5,(Streets[BY]+Streets[BY+1])*.5,0);
        Shape("Cube",Middle+FVector(0,0,8),FVector(3480,3480,30),"M_QuarterPaving");
        for(int32 Side:{-1,1})
        {
            Shape("Cube",Middle+FVector(Side*1740,0,10),FVector(18,3480,34),"MI_Plaster");
            Shape("Cube",Middle+FVector(0,Side*1740,10),FVector(3480,18,34),"MI_Plaster");
        }
        for(int32 PX:{-1,0,1})for(int32 PY:{-1,1})
        {
            // Facilities occupy explicit parcels, rather than empty whole blocks.
            if(BX==2&&BY==2&&PY==1&&PX>=0)continue; // retention basin
            if(BX==2&&BY==0&&PY==-1)continue; // tunnel and its embankment
            if(BX==1&&BY==0&&PX==1)continue; // accessible training courtyard
            if(BX==2&&BY==1&&PX==-1&&PY==1)continue;
            if(BX==1&&BY==1&&PX==0&&PY==-1)continue; // unstable structural bay // substation
            FVector Site=Middle+FVector(PX*1100,PY*1070,24);
            const int32 Variant=BX*19+BY*7+PX+PY+4;
            const int32 Damage=(Variant+BX+BY)%6;
            Apartment(Site,3+(Variant%3==0),Variant,Damage);
        }
        // The gap between the two rows is a courtyard access route, with small
        // communal and service parcels. Road lanes and door approaches stay free.
        Shape("Cube",Middle+FVector(0,0,24),FVector(2940,220,1),"MI_Concrete",FRotator::ZeroRotator,false);
        DistrictAssembly("SceneryKit",Middle+FVector(-610,230,24),FRotator(0,180,0),FVector::OneVector,
            true,false,"courtyard_bench");
        DistrictAssembly("SceneryKit",Middle+FVector(1320,190,24),FRotator(0,90,0),FVector::OneVector,
            true,false,"service_bins");
        // Crosswalks terminate on pavements; no tall collision strips across the carriageway.
        for(int32 Stripe=0;Stripe<7;Stripe++)
        {
            Shape("Cube",FVector(Streets[BX]+600,Streets[BY]-290+Stripe*95,8),FVector(250,40,2),"MI_White",FRotator::ZeroRotator,false);
            Shape("Cube",FVector(Streets[BX]-290+Stripe*95,Streets[BY]+600,9),FVector(40,250,2),"MI_White",FRotator::ZeroRotator,false);
        }
    }
    // Ground-floor training courtyard assembled from the supplied reusable wall.
    for(int32 I=0;I<4;I++)
    {
        DistrictMesh("WindowWall",FVector(7600+I*300,2200,24));
        if(I!=1)DistrictMesh("WindowWall",FVector(7600+I*300,3900,24),FRotator(0,180,0));
    }
    DistrictMesh("Doorway",FVector(7900,3900,24));
    for(int32 I=0;I<3;I++)GroundedAssembly("Slab",FVector(7900+I*330,2900,24),FRotator(4,I*67,5),FVector(.7));
    GroundedAssembly("Beam",FVector(8400,3100,24),FRotator(0,25,0));
    if(LoadObject<UStaticMesh>(nullptr,
        TEXT("/Game/RescueAssets/LibraryV3/DeformedIBeamV2/SM_DeformedIBeamV2.SM_DeformedIBeamV2")))
        GroundedAssembly(TEXT("DeformedIBeamV2"),FVector(8160,3450,24),FRotator(0,18,0),FVector::OneVector,FString(),false);

    // Medical staging area: real open container, dock lanes, supplied stretchers and equipment.
    Shape("Cube",FVector(-1100,1700,1),FVector(3400,3900,20),"M_QuarterAsphalt");
    Shape("Cube",FVector(-300,-900,-2),FVector(5200,1800,12),"M_QuarterAsphalt");
    for(int32 Lane=0;Lane<4;Lane++)for(int32 Dash=0;Dash<8;Dash++)
    {
        const float StartX=-1100+Lane*330;
        const float X=FMath::Lerp(StartX,800.f,Dash/7.f);
        Shape("Cube",FVector(X,-600-Lane*320,6),FVector(70,6,2),"MI_Paint",FRotator::ZeroRotator,false);
    }
    DistrictMesh("Medical",FVector(-1600,2400,13));
    DistrictMesh("Van",FVector(-650,2100,14),FRotator(0,90,0));
    DistrictMesh("Generator",FVector(-2350,1900,13));
    DistrictMesh("UtilityBox",FVector(-2350,2150,13));
    DistrictMesh("MannequinStatic",FVector(-1870,2010,13),FRotator(0,-90,0),FVector::OneVector,false);
    for(int32 I=0;I<10;I++)DistrictAssembly("CableKit",FVector(-2338,1940+I*20,35),FRotator(90,0,0),
        FVector::OneVector,false,false,"cable_double");
    DistrictLabel("MEDICAL / EVACUATION",FVector(-1320,2040,365),37);
    for(int32 I=0;I<4;I++)
    {
        const FVector Dock=FVector(-1100+I*330,200,12);
        DistrictMesh("Dock",Dock,FRotator(0,90,0));
        for(int32 Side:{-1,1})Shape("Cube",Dock+FVector(Side*145,0,2),FVector(6,360,2),"MI_Paint",FRotator::ZeroRotator,false);
    }
    for(int32 I=0;I<5;I++)DistrictMesh("Crate",FVector(-1800+I*105,1800,13),FRotator(0,Rng.FRandRange(-5,5),0));
    DistrictMesh("Stretcher",FVector(-1000,2800,14),FRotator(0,90,0),FVector::OneVector,false);
    DistrictMesh("Relay",FVector(-2200,1250,13));
    for(int32 I=0;I<3;I++)
    {
        const FVector Pad=Base+FVector(-900,-900+I*450,13);
        Shape("Cylinder",Pad,FVector(210,210,2),"MI_Blue",FRotator::ZeroRotator,false);
        Shape("Cube",Pad+FVector(0,0,2),FVector(90,10,1),"MI_White",FRotator::ZeroRotator,false);
        Shape("Cube",Pad+FVector(0,0,2),FVector(10,90,1),"MI_White",FRotator::ZeroRotator,false);
    }
    DistrictMesh("Sensor",FVector(-650,3600,13),FRotator(0,-30,0));
    for(int32 I=0;I<6;I++)
    {
        const FVector P(-2600,0+I*570,0);
        DistrictMesh("Fence",P,FRotator(0,90,0));
        if(I<5)DistrictMesh("Barrier",P+FVector(160,-180,0),FRotator(0,90,0));
    }
    Shape("Cube",Base+FVector(0,0,8),FVector(650,650,3),"MI_Zone",FRotator::ZeroRotator,false);
    DistrictLabel("RESCUE BASE",Base+FVector(-200,0,80),45);

    // Street-level detail makes scale and access legible without filling every route with clutter.
    for(int32 A=0;A<4;A++)for(int32 I=0;I<5;I++)
    {
        const FVector P(Streets[A]+550,-1200+I*3600,24);
        DistrictMesh("Lamp",P,FRotator(0,180,0));
        auto* Lamp=NewObject<USpotLightComponent>(this);AddInstanceComponent(Lamp);Lamp->SetupAttachment(GetRootComponent());
        Lamp->SetMobility(EComponentMobility::Movable);Lamp->SetRelativeLocation(P+FVector(0,90,490));
        Lamp->SetRelativeRotation(FRotator(-90,0,0));Lamp->SetIntensity(2200);Lamp->SetAttenuationRadius(1150);
        Lamp->SetInnerConeAngle(35);Lamp->SetOuterConeAngle(65);Lamp->SetLightColor(FLinearColor(.88,.94,1));
        Lamp->SetCastShadows(false);Lamp->RegisterComponent();Generated.Add(Lamp);
        if(I%2==0)DistrictMesh("Barrier",P+FVector(90,450,0),FRotator(0,90,0));
    }
    DistrictMesh("Relay",FVector(6000,9700,25));
    for(const FVector P:{FVector(-2200,1250,300),FVector(6000,9700,310)})
    {
        auto* Lamp=NewObject<UPointLightComponent>(this);AddInstanceComponent(Lamp);Lamp->SetupAttachment(GetRootComponent());
        Lamp->SetMobility(EComponentMobility::Movable);Lamp->SetRelativeLocation(P);Lamp->SetIntensity(1800);
        Lamp->SetAttenuationRadius(220);Lamp->SetCastShadows(false);Lamp->ComponentTags.Add(TEXT("RelayStatus"));
        Lamp->RegisterComponent();Generated.Add(Lamp);
    }
    DistrictMesh("Sensor",FVector(10800,6100,24),FRotator(0,110,0));
    for(int32 I=0;I<5;I++)DistrictMesh("Fence",FVector(12100,11200+I*300,24),FRotator(0,90,0));

    // A shallow above-ground retention basin: the rim is physical, depth is explicit.
    const FVector Basin(12850,13000,24);
    Shape("Cube",Basin+FVector(0,0,5),FVector(1900,2200,10),"MI_Dark");
    Shape("Plane",Basin+FVector(0,0,70),FVector(1820,2120,100),"M_QuarterWater",FRotator::ZeroRotator,false);
    for(int32 S:{-1,1})
    {
        Shape("Cube",Basin+FVector(S*950,0,45),FVector(60,2260,90),"MI_Concrete");
        Shape("Cube",Basin+FVector(0,S*1100,45),FVector(1960,60,90),"MI_Concrete");
    }
    Shape("Cube",Basin+FVector(-900,-100,90),FVector(420,1600,35),"MI_Metal");
    DistrictLabel("FLOOD / WATER ZONE",Basin+FVector(0,-1130,150),40);
    DistrictMesh("Sensor",Basin+FVector(-1100,-800,0),FRotator(0,45,0));
    auto* Spill=Shape("Plane",FVector(14500,12800,4),FVector(850,1500,100),"M_QuarterWater",FRotator::ZeroRotator,false);
    Spill->SetMobility(EComponentMobility::Movable);Spill->SetVisibility(false);Spill->ComponentTags.Add(TEXT("FloodSurface"));
    
    DistrictLabel("SOFT GROUND / LOW TRACTION",FVector(6000,8300,90),30);
    DistrictLabel("LEAK / DEPTH SENSOR",FVector(14000,11950,100),32);
    // A leaking outlet connects the retention basin to the road spill.
    DistrictAssembly("PipeKit",Basin+FVector(930,-200,50),FRotator(0,90,-90),FVector::OneVector,
        false,false,"modular_industrial_pipes_01_pipe02");
    DistrictMesh("UtilityBox",FVector(10900,7950,24),FRotator(0,90,0));
    // Primary ignition sites have a plausible source in a service parcel.
    DistrictMesh("UtilityBox",FVector(6650,10650,24),FRotator(0,180,0));
    DistrictMesh("Generator",FVector(2150,6150,24),FRotator(0,180,0));
    DistrictAssembly("SceneryKit",FVector(11800,9350,24),FRotator::ZeroRotator,FVector::OneVector,
        true,false,"service_bins");
    DistrictMesh("UtilityBox",FVector(8900,2500,24));
    DistrictAssembly("SceneryKit",FVector(3300,12790,24),FRotator(0,180,0),FVector::OneVector,
        true,false,"service_bins");
    for(int32 I=0;I<3;I++)ClosureBarrier(FVector(10450+I*310,7450,24));
    DistrictLabel("ELECTRICAL FIRE / NO ENTRY",FVector(10900,7450,160),32);

    // Enclosed utility passage under a raised embankment; the clear interior is usable geometry.
    const FVector Tunnel(12400,3050,24);
    DistrictMesh("UtilityTunnel",Tunnel);
    DistrictMesh("Sensor",Tunnel+FVector(-800,-500,0));
    for(int32 I=0;I<6;I++)
    {
        DistrictAssembly("PipeKit",Tunnel+FVector(-490+I*195,260,210),FRotator(90,0,0),
            FVector::OneVector,false,false,"modular_industrial_pipes_01_pipe02");
        DistrictAssembly("CableKit",Tunnel+FVector(-490+I*60,-270,190),FRotator(90,0,0),
            FVector::OneVector,false,false,"cable_straight_long");
    }
    DistrictMesh("Manhole",Tunnel+FVector(-900,400,1));
    // One hydrant variant is assembled around its original datum; the second
    // source variant stays in the editable library rather than overlapping it.
    DistrictAssembly("Hydrant",FVector(10800,6500,24),FRotator::ZeroRotator,FVector::OneVector,true,false,"fire_hydrant");
    DistrictAssembly("Hydrant",FVector(10800,6487,55),FRotator::ZeroRotator,FVector::OneVector,true,false,"fire_hydrant_cap_01");
    DistrictAssembly("Hydrant",FVector(10810,6496,76),FRotator::ZeroRotator,FVector::OneVector,true,false,"fire_hydrant_cap_02");
    DistrictAssembly("Hydrant",FVector(10789,6496,75),FRotator::ZeroRotator,FVector::OneVector,true,false,"fire_hydrant_cap_03");
    DistrictAssembly("Hydrant",FVector(10800,6491,44),FRotator::ZeroRotator,FVector::OneVector,false,false,"fire_hydrant_chain");
    DistrictLabel("UTILITY TUNNEL",Tunnel+FVector(-720,-330,330),38);

    // A genuinely supported unstable bay. Slabs lie across concrete beams and
    // columns until a collapse event releases them; nothing hangs over a street.
    const FVector Collapse(7800,6500,24);
    for(int32 X:{-1,1})for(int32 Y:{-1,1})
        Shape("Cube",Collapse+FVector(X*350,Y*280,400),FVector(45,45,800),"MI_Concrete");
    for(int32 I=0;I<5;I++)
    {
        const float X=-300+I*150;
        auto* Support=Shape("Cube",Collapse+FVector(X,0,795),FVector(45,660,40),"MI_Concrete");
        Support->ComponentTags.Add(TEXT("CollapseSupport"));
        auto* Slab=Chunk(Rng,Collapse+FVector(X,0,853),FVector(145,620,65),true,true);
        Slab->SetRelativeRotation(FRotator::ZeroRotator);
        Slab->SetRelativeLocation(Collapse+FVector(X,0,847));
    }
    for(int32 I=0;I<18;I++)GroundedChunk(Rng,Collapse+FVector(Rng.FRandRange(-480,480),
        Rng.FRandRange(-360,360),0),FVector(Rng.FRandRange(60,160),Rng.FRandRange(50,140),Rng.FRandRange(25,60)),true);
    for(int32 I=0;I<4;I++)ClosureBarrier(Collapse+FVector(-600+I*410,-600,0));
    // Continuous inhabited background with varied intact and damaged roofs.
    for(int32 I=0;I<11;I++)for(int32 Side=0;Side<4;Side++)
    {
        const float Along=-2500+I*2150;
        const FVector At=Side==0?FVector(Along,18200,0):Side==1?FVector(18200,Along,0):
            Side==2?FVector(Along,-4300,0):FVector(-4300,Along,0);
        if(Side==3&&Along<4500)continue;
        Apartment(At,3+(I+Side)%3,I+Side*31,(I+Side)%6);
    }
    OptimizeDistrictInstances();
    UE_LOG(LogTemp,Display,TEXT("MR_RESCUE_QUARTER_BUILT: %d components, %d dynamic pieces"),Generated.Num(),PhysicsPieces.Num());
}
