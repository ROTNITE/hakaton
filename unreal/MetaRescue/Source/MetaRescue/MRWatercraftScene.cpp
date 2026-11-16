#include "MRWorld.h"
#include "MRAgent.h"
#include "MRCoreValues.h"
#include "MRCoreJson.h"
#include "MRWatercraftHydro.h"
#include "Components/StaticMeshComponent.h"
#include "PhysicalMaterials/PhysicalMaterial.h"
#include "Engine/World.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"

using namespace MRCoreValues;

TSharedPtr<FJsonObject> AMRWorld::ShoreStation() const
{
    if(!bDisasterCity||!CityLayout||!Is(CityLayout,TEXT("watercraft"),EJson::Object))return nullptr;
    const auto Data=CityLayout->GetObjectField(TEXT("watercraft"));
    return Is(Data,TEXT("shore_station"),EJson::Object)?Data->GetObjectField(TEXT("shore_station")):nullptr;
}

TOptional<double> AMRWorld::ElevatedSupportHeightCm(const FVector& P) const
{
    const auto Station=ShoreStation();if(!Station)return {};
    for(const auto& Value:Station->GetArrayField(TEXT("platforms")))
    {
        FVector Low,High;MRCoreJson::Point(Field(Value->AsObject(),TEXT("min")),Low);MRCoreJson::Point(Field(Value->AsObject(),TEXT("max")),High);
        Low*=100;High*=100;
        if(P.X>=Low.X&&P.X<=High.X&&P.Y>=Low.Y&&P.Y<=High.Y&&P.Z>=High.Z-30)return High.Z;
    }
    return {};
}

double AMRWorld::ShoreHoistHeightCm() const
{const auto Station=ShoreStation();return Station?Station->GetNumberField(TEXT("hoist_height_m"))*100:0.;}

bool AMRWorld::ValidateWatercraftLayout()
{
    WatercraftPhysicsProfile.Reset();
    if(!CityLayout->HasField(TEXT("watercraft")))return true;
    if(!bDisasterCity||!Is(CityLayout,TEXT("watercraft"),EJson::Object)||!CityLayout->HasField(TEXT("hydrology")))return false;
    const auto Data=CityLayout->GetObjectField(TEXT("watercraft"));
    if(Text(Data,TEXT("format"))!=TEXT("metarescue.rescue-watercraft.v1")||
       Text(Data,TEXT("hydrostatics_profile"))!=TEXT("watercraft-hydrostatics-r1.json")||
       !Is(Data,TEXT("spawns"),EJson::Array)||!Is(Data,TEXT("slipways"),EJson::Array))return false;
    const auto& Spawns=Data->GetArrayField(TEXT("spawns"));const auto& Slips=Data->GetArrayField(TEXT("slipways"));
    if(Spawns.IsEmpty()||Spawns.Num()>4||Slips.Num()!=Spawns.Num())return false;
    if(Data->HasField(TEXT("load_fixture")))
    {
        if(!Is(Data,TEXT("load_fixture"),EJson::Object))return false;
        const auto Fixture=Data->GetObjectField(TEXT("load_fixture"));
        if(Text(Fixture,TEXT("format"))!=TEXT("metarescue.stretcher-cradle.v1"))return false;
        for(const auto& Pair:TMap<FString,double>{{TEXT("anchor_x_m"),.6},{TEXT("deck_raise_m"),.12},{TEXT("mass_kg"),8.}})
            if(!Is(Fixture,Pair.Key,EJson::Number)||Fixture->GetNumberField(Pair.Key)!=Pair.Value)return false;
    }
    if(Data->HasField(TEXT("shore_station")))
    {
        if(!Is(Data,TEXT("shore_station"),EJson::Object))return false;
        const auto Station=Data->GetObjectField(TEXT("shore_station"));
        if(Text(Station,TEXT("id"))!=TEXT("rescue-pier-west")||
           !Is(Station,TEXT("deck_z_m"),EJson::Number)||Station->GetNumberField(TEXT("deck_z_m"))!=3.47||
           !Is(Station,TEXT("hoist_height_m"),EJson::Number)||Station->GetNumberField(TEXT("hoist_height_m"))!=6.47||
           !Is(Station,TEXT("width_m"),EJson::Number)||Station->GetNumberField(TEXT("width_m"))!=6||
           !Is(Station,TEXT("platforms"),EJson::Array)||Station->GetArrayField(TEXT("platforms")).Num()!=2||
           !Is(Station,TEXT("boat_position_xy"),EJson::Array)||!Is(Station,TEXT("boat_yaw_degrees"),EJson::Number)||
           !Is(Station,TEXT("patient_capacity"),EJson::Number)||
           !Is(Station,TEXT("ground_route"),EJson::Array)||Station->GetArrayField(TEXT("ground_route")).Num()!=3)return false;
        const FVector ExpectedLow[]={FVector(-79,7,3.15),FVector(-79,7,3.15)};
        const FVector ExpectedHigh[]={FVector(0,13,3.47),FVector(-73,27,3.47)};
        for(int32 I=0;I<2;++I)
        {
            const auto Row=Station->GetArrayField(TEXT("platforms"))[I];FVector Low,High;
            if(Row->Type!=EJson::Object||!MRCoreJson::Point(Field(Row->AsObject(),TEXT("min")),Low)||
               !MRCoreJson::Point(Field(Row->AsObject(),TEXT("max")),High)||Low!=ExpectedLow[I]||High!=ExpectedHigh[I])return false;
        }
        FVector Patient=FVector::ZeroVector,Ground=FVector::ZeroVector;const auto& BoatXY=Station->GetArrayField(TEXT("boat_position_xy"));
        if(!MRCoreJson::Point(Field(Station,TEXT("patient_position")),Patient)||Patient!=FVector(-76,26,3.47)||
           !MRCoreJson::Point(Field(Station,TEXT("ground_pickup")),Ground)||Ground!=FVector(-76,22.5,3.47)||
           BoatXY.Num()!=2||BoatXY[0]->Type!=EJson::Number||BoatXY[1]->Type!=EJson::Number||
           BoatXY[0]->AsNumber()!= -76||BoatXY[1]->AsNumber()!=30.5||
           Station->GetNumberField(TEXT("boat_yaw_degrees"))!= -90||Station->GetNumberField(TEXT("patient_capacity"))!=1)return false;
        const FVector Route[]={FVector(10,10,3.47),FVector(-76,10,3.47),Ground};
        for(int32 I=0;I<3;++I){FVector P;if(!MRCoreJson::Point(Station->GetArrayField(TEXT("ground_route"))[I],P)||P!=Route[I])return false;}
    }
    TSet<FString> Ids;TArray<FVector> Positions;
    for(int32 I=0;I<Spawns.Num();++I)
    {
        if(Spawns[I]->Type!=EJson::Object||Slips[I]->Type!=EJson::Object)return false;
        const auto Spawn=Spawns[I]->AsObject(),Slip=Slips[I]->AsObject();FVector P;
        const FString Id=Text(Spawn,TEXT("id")),SlipId=Text(Slip,TEXT("id"));double Pitch,Yaw;
        if(Id.IsEmpty()||Ids.Contains(Id)||SlipId.IsEmpty()||Text(Spawn,TEXT("slipway_id"))!=SlipId||
           !MRCoreJson::Point(Field(Spawn,TEXT("position")),P)||P.X< -98||P.X> -64||P.Y<63||P.Y>72||P.Z<0||P.Z>4||
           !Spawn->TryGetNumberField(TEXT("pitch"),Pitch)||!Spawn->TryGetNumberField(TEXT("yaw"),Yaw)||
           !FMath::IsFinite(Pitch)||!FMath::IsFinite(Yaw)||FMath::Abs(Pitch)>10||Yaw!= -90)return false;
        for(FVector Prior:Positions)if(FVector::Dist2D(P,Prior)<6)return false;
        for(const FString& Key:{TEXT("x_m"),TEXT("upper_y_m"),TEXT("lower_y_m"),TEXT("upper_z_m"),TEXT("lower_z_m"),TEXT("width_m")})
            if(!Is(Slip,Key,EJson::Number)||!FMath::IsFinite(Slip->GetNumberField(Key)))return false;
        if(Slip->GetNumberField(TEXT("x_m"))!=P.X||Slip->GetNumberField(TEXT("upper_y_m"))!=73||
           Slip->GetNumberField(TEXT("lower_y_m"))!=55||Slip->GetNumberField(TEXT("upper_z_m"))!=1.5||
           Slip->GetNumberField(TEXT("lower_z_m"))!= -.4||Slip->GetNumberField(TEXT("width_m"))!=3)return false;
        Ids.Add(Id);Positions.Add(P);
    }
    FString Raw;Object Profile;
    const FString File=FPaths::ProjectContentDir()/TEXT("Scenario/watercraft-hydrostatics-r1.json");
    if(!FFileHelper::LoadFileToString(Raw,*File)||!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Raw),Profile))
    {UE_LOG(LogTemp,Error,TEXT("MR_WATERCRAFT prepare_water_hydrostatics.py must produce the runtime profile"));return false;}
    WatercraftPhysicsProfile=MakeShared<FMRWatercraftHydro>();
    if(!WatercraftPhysicsProfile->Read(Profile)||WatercraftPhysicsProfile->ModelSourceHash!=
        TEXT("d2c205b47f5b39c7e79292310c1ef4236f278cd2055b3b12308a4ca1073a1e47"))
    {WatercraftPhysicsProfile.Reset();return false;}
    return true;
}

void AMRWorld::BuildWatercraftSlips()
{
    if(!WatercraftPhysicsProfile)return;
    auto* Contact=NewObject<UPhysicalMaterial>(this);Contact->Friction=.04f;Contact->StaticFriction=.06f;
    Contact->bOverrideFrictionCombineMode=true;Contact->FrictionCombineMode=EFrictionCombineMode::Min;
    const double Pitch=-FMath::RadiansToDegrees(FMath::Atan2(190.,1800.)),Cos=FMath::Cos(FMath::DegreesToRadians(Pitch));
    for(const auto& Value:CityLayout->GetObjectField(TEXT("watercraft"))->GetArrayField(TEXT("slipways")))
    {
        const auto Row=Value->AsObject();const double X=Row->GetNumberField(TEXT("x_m"))*100;
        const FRotator Turn(Pitch,-90,0);
        // Steel launching runners on a supported slip. The boat is restrained
        // horizontally by its mooring; after release gravity performs the dry launch.
        for(double Side:{-1.,1.})
        {
            auto* Runner=Shape(TEXT("Cube"),FVector(X+Side*60,6400,55-8*Cos),FVector(1800/Cos,38,16),TEXT("MI_Metal"),Turn);
            Runner->SetPhysMaterialOverride(Contact);Runner->ComponentTags.Add(TEXT("WatercraftSlip"));
        }
        for(double Y=5600;Y<=7200;Y+=200)
        {
            const double Z=150-(7300-Y)*190/1800;
            Shape(TEXT("Cube"),FVector(X,Y,Z-14),FVector(275,14,14),TEXT("MI_Metal"));
            for(double Side:{-1.,1.})
            {
                const FVector P(X+Side*110,Y,0);const double Ground=InitialGroundHeightCm(P);
                if(Z-20>Ground)Shape(TEXT("Cylinder"),FVector(P.X,P.Y,(Ground+Z-20)*.5),FVector(16,16,Z-20-Ground),TEXT("MI_Concrete"));
            }
        }
        for(double Side:{-1.,1.})
            Shape(TEXT("Cylinder"),FVector(X+Side*140,7100,165),FVector(15,15,330),TEXT("MI_Metal"));
    }
    const auto Station=ShoreStation();if(!Station)return;
    for(const auto& Value:Station->GetArrayField(TEXT("platforms")))
    {
        FVector Low,High;MRCoreJson::Point(Field(Value->AsObject(),TEXT("min")),Low);MRCoreJson::Point(Field(Value->AsObject(),TEXT("max")),High);
        Low*=100;High*=100;auto* Deck=Shape(TEXT("Cube"),(Low+High)*.5,High-Low,TEXT("MI_Concrete"));
        Deck->ComponentTags.Add(TEXT("RescuePier"));
    }
    auto Pile=[&](double X,double Y)
    {
        const double Ground=InitialGroundHeightCm(FVector(X,Y,0));
        if(Ground<315)Shape(TEXT("Cylinder"),FVector(X,Y,(Ground+315)*.5),FVector(36,36,315-Ground),TEXT("MI_Concrete"));
    };
    for(double X=-7600;X< -300;X+=600)
    {
        for(double Y:{750.,1250.})Pile(X,Y);
        Shape(TEXT("Cube"),FVector(X,1000,310),FVector(35,590,30),TEXT("MI_Metal"));
    }
    for(double Y=1600;Y<=2600;Y+=500)for(double X:{-7850.,-7350.})Pile(X,Y);
    auto Rail=[&](FVector A,FVector B)
    {
        const FVector D=B-A;const double L=D.Size2D();
        for(double Z:{402.,457.})Shape(TEXT("Cube"),(A+B)*.5+FVector(0,0,Z),FVector(L,6,6),TEXT("MI_Metal"),D.Rotation());
        const int32 Count=FMath::CeilToInt(L/240);
        for(int32 I=0;I<=Count;++I)Shape(TEXT("Cube"),FMath::Lerp(A,B,double(I)/Count)+FVector(0,0,402),FVector(8,8,110),TEXT("MI_Metal"));
    };
    Rail(FVector(-7900,720,0),FVector(0,720,0));Rail(FVector(-7300,1280,0),FVector(0,1280,0));
    Rail(FVector(-7880,1280,0),FVector(-7880,2700,0));Rail(FVector(-7320,1280,0),FVector(-7320,2700,0));
    for(double X:{-7850.,-7350.})Shape(TEXT("Cylinder"),FVector(X,2670,382),FVector(20,20,70),TEXT("MI_Metal"));
    // A shore-supported gantry can lift to the dry deck even at low water.
    // Its columns stand on the piles; the over-water beam is cantilevered.
    for(double X:{-7840.,-7360.})
    {
        Shape(TEXT("Cube"),FVector(X,2550,497),FVector(18,18,300),TEXT("MI_Metal"));
        const FVector A(X,2550,417),B(X,2850,632),D=B-A;
        Shape(TEXT("Cube"),(A+B)*.5,FVector(D.Size(),14,14),TEXT("MI_Metal"),D.Rotation());
    }
    Shape(TEXT("Cube"),FVector(-7600,2550,647),FVector(520,22,26),TEXT("MI_Metal"));
    Shape(TEXT("Cube"),FVector(-7600,2825,647),FVector(18,650,22),TEXT("MI_Metal"));
    DistrictLabel(TEXT("WATER RESCUE / TRANSFER"),FVector(-7580,2550,620),30);
}

void AMRWorld::SpawnWatercraft()
{
    if(!WatercraftPhysicsProfile)return;
    for(const auto& Value:CityLayout->GetObjectField(TEXT("watercraft"))->GetArrayField(TEXT("spawns")))
    {
        const auto Row=Value->AsObject();FVector Position;MRCoreJson::Point(Field(Row,TEXT("position")),Position);
        FActorSpawnParameters Parameters;Parameters.SpawnCollisionHandlingOverride=ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
        auto* Boat=GetWorld()->SpawnActor<AMRAgent>(Position*100,FRotator(Row->GetNumberField(TEXT("pitch")),Row->GetNumberField(TEXT("yaw")),0),Parameters);
        if(!Boat||!Boat->InitializeWatercraft(this,Agents.Num(),Text(Row,TEXT("id")),WatercraftPhysicsProfile))
        {UE_LOG(LogTemp,Error,TEXT("MR_WATERCRAFT could not construct the physical catamaran"));FPlatformMisc::RequestExitWithStatus(false,1);return;}
        Agents.Add(Boat);
    }
}
