#include "MRWorld.h"
#include "MRCityAssets.h"
#include "Components/PrimitiveComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "Misc/App.h"
#include "ProceduralMeshComponent.h"

void AMRWorld::BuildCityHorizon()
{
    if(!bDecoratedCity||!FApp::CanEverRender())return;
    const double Size=CityLayout->GetNumberField(TEXT("size_m"))*100;
    constexpr double Far=2000000,Near=6000;
    auto* Ground=NewObject<UProceduralMeshComponent>(this);
    AddInstanceComponent(Ground);Ground->SetupAttachment(GetRootComponent());
    Ground->SetMobility(EComponentMobility::Static);Ground->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    Ground->SetCastShadow(false);Ground->SetAffectDistanceFieldLighting(false);
    Ground->ComponentTags={TEXT("CityVisualHorizon"),TEXT("NoMissionCollision")};
    TArray<FVector> Vertices,Normals;TArray<FVector2D> UV;TArray<int32> Triangles;
    FBox Basin(ForceInit);
    if(CityLayout->HasTypedField<EJson::Object>(TEXT("competition")))
    {
        const auto Bounds=CityLayout->GetObjectField(TEXT("competition"))->GetObjectField(TEXT("basin"));
        const auto& Low=Bounds->GetArrayField(TEXT("min"));const auto& High=Bounds->GetArrayField(TEXT("max"));
        Basin=FBox(FVector(Low[0]->AsNumber()*100-40,Low[1]->AsNumber()*100-40,-1000),
                   FVector(High[0]->AsNumber()*100+40,High[1]->AsNumber()*100+40,100));
    }
    const auto Quad=[&](double X0,double Y0,double X1,double Y1)
    {
        if(X1<=X0||Y1<=Y0)return;
        const int32 Start=Vertices.Num();
        for(const FVector P:{FVector(X0,Y0,-6),FVector(X1,Y0,-6),FVector(X1,Y1,-6),FVector(X0,Y1,-6)})
        {Vertices.Add(P);Normals.Add(FVector::UpVector);UV.Add(FVector2D(P.X,P.Y)/100);}
        Triangles.Append({Start,Start+2,Start+1,Start,Start+3,Start+2});
    };
    const auto Terrain=[&](double X0,double Y0,double X1,double Y1)
    {
        if(!Basin.IsValid||Basin.Max.X<=X0||Basin.Min.X>=X1||Basin.Max.Y<=Y0||Basin.Min.Y>=Y1)
        {Quad(X0,Y0,X1,Y1);return;}
        // Keep the real open basin visible; a decorative plane must not fill it.
        const double A=FMath::Max(X0,Basin.Min.X),B=FMath::Min(X1,Basin.Max.X);
        const double C=FMath::Max(Y0,Basin.Min.Y),D=FMath::Min(Y1,Basin.Max.Y);
        Quad(X0,Y0,A,Y1);Quad(B,Y0,X1,Y1);Quad(A,Y0,B,C);Quad(A,D,B,Y1);
    };
    Terrain(-Far,-Far,-Near,Size+Far);Terrain(Size+Near,-Far,Size+Far,Size+Far);
    Terrain(-Near,-Far,Size+Near,-Near);Terrain(-Near,Size+Near,Size+Near,Size+Far);
    Ground->CreateMeshSection_LinearColor(0,Vertices,Triangles,Normals,UV,{},{},false);
    Ground->SetMaterial(0,LoadObject<UMaterialInterface>(nullptr,
        TEXT("/Game/RescueAssets/CityV2/SurfacesR4/M_Verge.M_Verge")));
    Generated.Add(Ground);

    const auto Point=[](const TArray<TSharedPtr<FJsonValue>>& A)
    {return FVector(A[0]->AsNumber(),A[1]->AsNumber(),A[2]->AsNumber())*100;};
    const auto Decorative=[](UPrimitiveComponent* Component)
    {
        Component->ComponentTags.Add(TEXT("CityVisualHorizon"));
        Component->ComponentTags.Add(TEXT("NoMissionCollision"));
        Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        Component->SetAffectDistanceFieldLighting(false);
    };
    const bool bOutskirts=CityLayout->HasTypedField<EJson::Number>(TEXT("background_revision"));
    const auto Graph=CityLayout->GetObjectField(TEXT("road_graph"));TMap<FString,FVector> Nodes;
    for(const auto& Entry:Graph->GetArrayField(TEXT("nodes")))
        Nodes.Add(Entry->AsObject()->GetStringField(TEXT("id")),Point(Entry->AsObject()->GetArrayField(TEXT("position"))));
    int32 Houses=0,GreenLots=0,ServiceLots=0;
    for(const auto& Entry:Graph->GetArrayField(TEXT("entrances")))
    {
        const auto Gate=Entry->AsObject();const auto& Direction=Gate->GetArrayField(TEXT("outward"));
        const FVector Outward(Direction[0]->AsNumber(),Direction[1]->AsNumber(),0),Side(-Outward.Y,Outward.X,0);
        const FVector Start=Nodes.FindChecked(Gate->GetStringField(TEXT("node_id")));
        if(bOutskirts)
        {
            // Continue the near road at the same visible height, in bounded render pieces.
            constexpr double NearRoadEnd=6500.,SegmentLength=4000.;
            const double End=FMath::Max(38000.,Size*.65);
            for(double From=NearRoadEnd;From<End;From+=SegmentLength)
            {
                const double Length=FMath::Min(SegmentLength,End-From);
                auto* Road=Shape(TEXT("Cube"),Start+Outward*(From+Length*.5)+FVector(0,0,1.2),
                    FVector(Length,1000,1),TEXT("M_QuarterAsphalt"),Outward.Rotation(),false);
                Road->SetCastShadow(false);Decorative(Road);
            }
            continue;
        }
        auto* Road=Shape(TEXT("Cube"),Start+Outward*103250+FVector(0,0,-2.5),FVector(193500,1000,1),
                         TEXT("M_QuarterAsphalt"),Outward.Rotation(),false);
        Road->SetCastShadow(false);Decorative(Road);
        for(int32 Block=0;Block<3;Block++)for(int32 Lot=-2;Lot<=2;Lot++)for(int32 Flank:{-1,1})
        {
            // These use the same 9 m houses, floors, textures and windows. The
            // distant street fronts are decorative and outside mission bounds.
            const FVector P=Start+Outward*(17000+Block*13000)+Side*(Flank*(1500+FMath::Abs(Lot)*1800));
            if(Lot*Flank<0)continue;
            const int32 Begin=Generated.Num(),Footprints=StructureFootprints.Num();
            Apartment(P,3+(Houses%2),40000+Houses,0);
            StructureFootprints.SetNum(Footprints);
            for(int32 Index=Begin;Index<Generated.Num();Index++)if(auto* Component=Generated[Index].Get())
            {
                Component->ComponentTags.Add(TEXT("CityVisualHorizon"));
                Component->ComponentTags.Add(TEXT("NoMissionCollision"));
                if(auto* Primitive=Cast<UPrimitiveComponent>(Component))Primitive->SetCollisionEnabled(ECollisionEnabled::NoCollision);
            }
            Houses++;
            if(Houses%6==0)OptimizeDistrictInstances();
        }
    }
    if(bOutskirts)
    {
        auto* Service=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/RescueAssets/CityV2/SurfacesR4/M_Service.M_Service"));
        auto* Linden=MRCityVegetation(TEXT("street_linden"),CityVegetationRevision);
        auto* Pine=MRCityVegetation(TEXT("pine_sapling"),CityVegetationRevision);
        for(const auto& Entry:CityLayout->GetArrayField(TEXT("background")))
        {
            const auto Lot=Entry->AsObject();
            const FVector P=Point(Lot->GetArrayField(TEXT("position")));
            const FRotator Turn(0,Lot->GetNumberField(TEXT("yaw")),0);
            const FString Kind=Lot->GetStringField(TEXT("kind"));
            // Keep the open basin and the adjacent access apron free of scenery.
            if(Basin.IsValid&&Basin.ExpandBy(950).IsInsideXY(P))continue;
            const int32 Variant=Lot->GetIntegerField(TEXT("variant"));
            const auto Piece=[&](const FVector& Offset,const FVector& Size,const TCHAR* Material)
            {
                auto* Component=Shape(TEXT("Cube"),P+Turn.RotateVector(Offset),Size,Material,Turn,false);
                Decorative(Component);
                return Component;
            };
            if(Kind==TEXT("housing"))
            {
                const double H=300*Lot->GetIntegerField(TEXT("floors"));
                const double W=Variant%2?740:890, D=Variant<2?720:870;
                Piece(FVector(0,0,H*.5),FVector(W,D,H),Variant<2?TEXT("MI_Plaster"):TEXT("MI_Concrete"));
                Piece(FVector(0,0,H+14),FVector(W+32,D+32,28),Variant%2?TEXT("MI_Dark"):TEXT("M_QuarterAsphalt"));
                Piece(FVector(-W*.23,D*.21,H+47),FVector(130,154,45),TEXT("MI_Dark"));
                Houses++;
            }
            else if(Kind==TEXT("green"))
            {
                for(const FVector Offset:{FVector(-205,-190,0),FVector(255,235,0),FVector(-178,240,0)})
                {
                    auto* Mesh=Offset.Y<0?Linden:Pine;
                    if(!Mesh)continue;
                    auto* Tree=NewObject<UStaticMeshComponent>(this);
                    AddInstanceComponent(Tree);Tree->SetupAttachment(GetRootComponent());
                    Tree->SetMobility(EComponentMobility::Static);Tree->SetStaticMesh(Mesh);
                    Tree->SetRelativeLocation(P+Turn.RotateVector(Offset));Tree->SetRelativeRotation(Turn);
                    Decorative(Tree);Generated.Add(Tree);
                }
                GreenLots++;
            }
            else if(Kind==TEXT("service"))
            {
                auto* Cover=Piece(FVector(0,0,.4),FVector(1140,1180,.6),TEXT("City_Soil"));
                Cover->SetMaterial(0,Service);
                Cover->SetCastShadow(false);
                Piece(FVector(0,255,135),FVector(840,380,270),TEXT("MI_Concrete"));
                Piece(FVector(0,255,278),FVector(865,406,18),TEXT("MI_Dark"));
                ServiceLots++;
            }
        }
    }
    UE_LOG(LogTemp,Display,TEXT("MR_CITY_HORIZON extent_m=20000 houses=%d green=%d service=%d triangles=%d collision=none basin_open=%d"),
        Houses,GreenLots,ServiceLots,Triangles.Num()/3,Basin.IsValid?1:0);
}
