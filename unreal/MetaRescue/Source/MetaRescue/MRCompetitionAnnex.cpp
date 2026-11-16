#include "MRWorld.h"
#include "MRAgent.h"
#include "MRCoreJson.h"
#include "MRCoreValues.h"
#include "Components/StaticMeshComponent.h"
#include "Components/PointLightComponent.h"
#include "Engine/World.h"
#include "Misc/App.h"

using namespace MRCoreValues;

namespace
{
FBox Box(const Object& Source)
{
    FVector Min,Max;
    if(!MRCoreJson::Point(Field(Source,TEXT("min")),Min)||!MRCoreJson::Point(Field(Source,TEXT("max")),Max)||
       Min.X>=Max.X||Min.Y>=Max.Y||Min.Z>=Max.Z)return FBox(ForceInit);
    return FBox(Min*100,Max*100);
}

bool Medium(const FString& Kind)
{return Kind==TEXT("surface_water")||Kind==TEXT("underwater")||Kind==TEXT("underground");}
}

bool AMRWorld::ValidateCompetitionLayout() const
{
    if(!CityLayout->HasField(TEXT("competition")))return true;
    if(!Is(CityLayout,TEXT("competition"),EJson::Object))return false;
    const auto Annex=CityLayout->GetObjectField(TEXT("competition"));
    if(Text(Annex,TEXT("format"))!=TEXT("metarescue.competition-annex.v1")||
        !Is(Annex,TEXT("units"),EJson::Array)||!Is(Annex,TEXT("zones"),EJson::Array))return false;
    for(const FString& Key:{TEXT("basin"),TEXT("tunnel")})
        if(!Is(Annex,Key,EJson::Object)||!Box(Annex->GetObjectField(Key)).IsValid)return false;
    const auto Bounds=Box(CityLayout->GetObjectField(TEXT("bounds")));
    TSet<FString> Ids;
    for(const auto& Spawn:CityLayout->GetArrayField(TEXT("spawns")))Ids.Add(Text(Spawn->AsObject(),TEXT("id")));
    const auto& Units=Annex->GetArrayField(TEXT("units"));
    if(Units.Num()>30)return false;
    for(const auto& V:Units)
    {
        if(V->Type!=EJson::Object)return false;
        const auto Unit=V->AsObject();const FString Id=Text(Unit,TEXT("id")),Kind=Text(Unit,TEXT("kind"));
        FVector Position;
        if(Id.IsEmpty()||Ids.Contains(Id)||!MRCoreJson::Point(Field(Unit,TEXT("position")),Position)||
           !Bounds.IsInsideOrOn(Position*100))return false;
        Ids.Add(Id);
        if(Medium(Kind))
        {
            if(!Is(Unit,TEXT("limits"),EJson::Object)||!Is(Unit,TEXT("yaw"),EJson::Number))return false;
            const auto Limits=Box(Unit->GetObjectField(TEXT("limits")));
            if(!Limits.IsValid||!Limits.IsInsideOrOn(Position*100)||!Bounds.IsInsideOrOn(Limits.Min)||
               !Bounds.IsInsideOrOn(Limits.Max))return false;
        }
        else if((Kind!=TEXT("infrastructure")&&Kind!=TEXT("digital")&&Kind!=TEXT("operator"))||
                Text(Unit,TEXT("site")).IsEmpty())return false;
    }
    return true;
}

void AMRWorld::BuildCompetitionAnnex()
{
    const bool Hydraulic=bDisasterCity&&Is(CityLayout,TEXT("hydrology"),EJson::Object);
    const bool Competition=Is(CityLayout,TEXT("competition"),EJson::Object);
    if(!Competition&&!Hydraulic)return;
    const auto Annex=Competition?CityLayout->GetObjectField(TEXT("competition")):Object();
    const auto Basin=Box((Hydraulic?CityLayout->GetObjectField(TEXT("hydrology")):Annex)->GetObjectField(TEXT("basin")));
    const auto Tunnel=Competition?Box(Annex->GetObjectField(TEXT("tunnel"))):FBox(ForceInit);
    auto Enclose=[&](const FBox& Limits,bool Roof)
    {
        const FVector C=Limits.GetCenter(),Size=Limits.GetSize();
        Shape(TEXT("Cube"),FVector(C.X,C.Y,Limits.Min.Z-16),FVector(Size.X+64,Size.Y+64,32),TEXT("MI_Concrete"));
        for(double Side:{-1.,1.})
        {
            Shape(TEXT("Cube"),FVector(C.X+Side*(Size.X*.5+16),C.Y,C.Z),FVector(32,Size.Y+64,Size.Z),TEXT("MI_Concrete"));
            Shape(TEXT("Cube"),FVector(C.X,C.Y+Side*(Size.Y*.5+16),C.Z),FVector(Size.X,32,Size.Z),TEXT("MI_Concrete"));
        }
        if(Roof)Shape(TEXT("Cube"),FVector(C.X,C.Y,Limits.Max.Z+16),FVector(Size.X+64,Size.Y+64,32),TEXT("MI_Concrete"));
    };
    Enclose(Basin,false);if(Competition)Enclose(Tunnel,true);
    const FVector Center=Basin.GetCenter(),Size=Basin.GetSize();
    if(!Hydraulic)Shape(TEXT("Plane"),FVector(Center.X,Center.Y,Basin.Max.Z),FVector(Size.X,Size.Y,100),
        TEXT("M_QuarterWater"),FRotator::ZeroRotator,false);
    Shape(TEXT("Cube"),FVector(Basin.Max.X+175,Center.Y,5),FVector(350,260,20),TEXT("MI_Concrete"));
    for(double X=Tunnel.Min.X+250;Competition&&X<Tunnel.Max.X-125;X+=420)
    {
        Shape(TEXT("Cube"),FVector(X,Tunnel.GetCenter().Y,Tunnel.Max.Z-10),FVector(100,20,8),
            TEXT("MI_WhiteGlow"),FRotator::ZeroRotator,false);
        if(FApp::CanEverRender())
        {
            auto* Lamp=NewObject<UPointLightComponent>(this);AddInstanceComponent(Lamp);Lamp->SetupAttachment(GetRootComponent());
            Lamp->SetMobility(EComponentMobility::Movable);
            Lamp->SetRelativeLocation(FVector(X,Tunnel.GetCenter().Y,Tunnel.Max.Z-45));
            Lamp->SetIntensityUnits(ELightUnits::Lumens);Lamp->SetIntensity(4000);
            Lamp->SetAttenuationRadius(1200);Lamp->SetLightColor(FLinearColor(.87f,.93f,1));
            Lamp->SetCastShadows(true);Lamp->ComponentTags.Add(TEXT("TunnelEmergencyFixture"));
            Generated.Add(Lamp);
        }
    }
}

void AMRWorld::SpawnCompetitionUnits()
{
    if(!Is(CityLayout,TEXT("competition"),EJson::Object))return;
    const auto Annex=CityLayout->GetObjectField(TEXT("competition"));
    for(const auto& V:Annex->GetArrayField(TEXT("units")))
    {
        const auto Unit=V->AsObject();const FString Kind=Text(Unit,TEXT("kind"));FVector Position;
        MRCoreJson::Point(Field(Unit,TEXT("position")),Position);
        double Yaw=0;Unit->TryGetNumberField(TEXT("yaw"),Yaw);
        FActorSpawnParameters Parameters;Parameters.SpawnCollisionHandlingOverride=ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
        auto* Agent=GetWorld()->SpawnActor<AMRAgent>(AMRAgent::StaticClass(),Position*100,FRotator(0,Yaw,0),Parameters);
        Agent->PublicId=Text(Unit,TEXT("id"));
        Agent->InitializeCompetition(this,Agents.Num(),Kind,Text(Unit,TEXT("site")),
            Medium(Kind)?Box(Unit->GetObjectField(TEXT("limits"))):FBox(ForceInit));
        Agents.Add(Agent);
    }
}
