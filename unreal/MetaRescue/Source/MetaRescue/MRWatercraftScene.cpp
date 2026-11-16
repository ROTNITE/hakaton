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
