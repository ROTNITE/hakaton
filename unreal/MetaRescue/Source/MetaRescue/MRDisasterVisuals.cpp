#include "MRWorld.h"
#include "MRCoreJson.h"
#include "MRCoreValues.h"
#include "Components/StaticMeshComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/DecalComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "NiagaraComponent.h"
#include "NiagaraSystem.h"
#include "Misc/App.h"
#include "Misc/Crc.h"

namespace
{
constexpr const TCHAR* ArtFolder=TEXT("/Game/EffectsV3/Revision5/");
UMaterialInterface* DisasterMaterial(const FString& Name)
{
    const FString Path=FString(ArtFolder)+Name+TEXT(".")+Name;
    auto* Result=LoadObject<UMaterialInterface>(nullptr,*Path);
    if(!Result)UE_LOG(LogTemp,Error,TEXT("MR_DISASTER required revision5 material missing: %s"),*Path);
    return Result;
}
}

UNiagaraComponent* AMRWorld::SpawnDisasterEffect(const FString& Name,const FVector& Position,
    const FVector& Scale,const FMRDisturbance& Event)
{
    if(!FApp::CanEverRender())return nullptr;
    const FString Object=TEXT("NS_")+Name;
    const FString Path=FString(ArtFolder)+Object+TEXT(".")+Object;
    auto* System=LoadObject<UNiagaraSystem>(nullptr,*Path);
    if(!System)
    {
        UE_LOG(LogTemp,Error,TEXT("MR_DISASTER required revision5 Niagara missing: %s"),*Path);
        return nullptr;
    }
    // The world owns every effect, so command-view hiding also covers fire,
    // smoke sprites and their shadows. No independent emitter actor can leak.
    auto* Component=NewObject<UNiagaraComponent>(this);
    AddInstanceComponent(Component);Component->SetupAttachment(GetRootComponent());
    Component->SetMobility(EComponentMobility::Movable);
    Component->SetAsset(System);Component->SetRelativeLocation(Position);
    Component->SetRandomSeedOffset(FCrc::StrCrc32(*Event.Id)^GetTypeHash(Position));
    Component->SetRelativeScale3D(Scale);Component->SetAutoActivate(false);
    Component->SetCastShadow(false);Component->SetCullDistance(65000);
    Component->ComponentTags={FName(*Event.Id),FName(*Name)};
    Component->RegisterComponent();
    if(auto* Material=DisasterMaterial(TEXT("M_")+Name))
        Component->SetVariableMaterial(TEXT("User.EffectMaterial"),UMaterialInstanceDynamic::Create(Material,Component));
    Component->Activate(true);HazardVisuals.Add(Component);
    return Component;
}

void AMRWorld::BuildDisasterSmoke(const FMRDisturbance& Event)
{
    if(!FApp::CanEverRender())return;
    auto* Material=DisasterMaterial(TEXT("M_PhysicalSmoke"));
    auto* Cube=LoadObject<UStaticMesh>(nullptr,TEXT("/Engine/BasicShapes/Cube.Cube"));
    if(!Material||!Cube)return;
    auto* Component=NewObject<UStaticMeshComponent>(this);
    AddInstanceComponent(Component);Component->SetupAttachment(GetRootComponent());
    Component->SetMobility(EComponentMobility::Movable);Component->SetStaticMesh(Cube);
    Component->bDisallowNanite=true;
    Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    Component->SetGenerateOverlapEvents(false);Component->SetCanEverAffectNavigation(false);
    Component->SetCastShadow(false);Component->bAffectDistanceFieldLighting=false;
    Component->SetCullDistance(65000);Component->SetTranslucentSortPriority(3);
    Component->SetMaterial(0,UMaterialInstanceDynamic::Create(Material,Component));
    Component->ComponentTags={FName(*Event.Id),TEXT("PhysicalSmoke")};
    Component->RegisterComponent();HazardVisuals.Add(Component);
    TickDisasterSmoke(Component,Event);
    if(Event.Kind==EMRDisturbance::Smoke||Event.Kind==EMRDisturbance::Fire)
    {
        FVector Source=Event.Source;Source.Z=Event.SmokeEmissionHeightCm+120;
        SpawnDisasterEffect(TEXT("HeavySmoke"),Source,FVector(Event.Kind==EMRDisturbance::Fire?1.6:2.4),Event);
    }
}

void AMRWorld::TickDisasterSmoke(USceneComponent* Component,const FMRDisturbance& Event)
{
    auto* Mesh=Cast<UStaticMeshComponent>(Component);
    if(!Mesh)return;
    const auto& Volumes=Environment.SmokeVolumes();
    const auto* Volume=Volumes.FindByPredicate([&](const auto& V){return V.EventId==Event.Id;});
    Mesh->SetVisibility(Volume!=nullptr);
    if(!Volume)return;
    const FBox Bounds=Volume->Bounds();
    Mesh->SetWorldLocation(Bounds.GetCenter());Mesh->SetWorldScale3D(Bounds.GetSize()/100.);
    if(auto* Material=Cast<UMaterialInstanceDynamic>(Mesh->GetMaterial(0)))
    {
        Material->SetVectorParameterValue(TEXT("SmokeSource"),FLinearColor(Volume->Source));
        Material->SetVectorParameterValue(TEXT("SmokeWind"),FLinearColor(Volume->WindCmPerSecond));
        Material->SetVectorParameterValue(TEXT("SmokeShape"),
            FLinearColor(Volume->HeightCm,Volume->RadiusCm,Volume->RadiusGrowth));
        Material->SetScalarParameterValue(TEXT("SmokeRise"),Volume->RiseCmPerSecond);
        Material->SetScalarParameterValue(TEXT("SmokeExtinction"),Volume->ExtinctionPerCm);
        Material->SetScalarParameterValue(TEXT("SmokeStrength"),Volume->Strength);
        const auto Color=Event.Kind==EMRDisturbance::LowVisibility?FLinearColor(.55,.58,.6):
            Event.Kind==EMRDisturbance::Collapse?FLinearColor(.25,.21,.16):FLinearColor(.045,.048,.05);
        Material->SetVectorParameterValue(TEXT("SmokeAlbedo"),Color);
    }
}

void AMRWorld::BuildDisasterFire(const FMRDisturbance& Event)
{
    if(!FApp::CanEverRender()||!CityLayout)return;
    using namespace MRCoreValues;
    FBox Bounds(ForceInit);
    for(const auto& Value:CityLayout->GetArrayField(TEXT("buildings")))
    {
        const auto Building=Value->AsObject();
        if(Text(Building,TEXT("id"))!=Event.SiteId)continue;
        FVector Low,High;
        const auto Box=Building->GetObjectField(TEXT("bounds"));
        if(MRCoreJson::Point(Field(Box,TEXT("min")),Low)&&MRCoreJson::Point(Field(Box,TEXT("max")),High))
            Bounds=FBox(Low*100,High*100);
        break;
    }
    if(!Bounds.IsValid)
    {
        UE_LOG(LogTemp,Error,TEXT("MR_DISASTER fire has no source building: %s"),*Event.SiteId);return;
    }
    const FVector Center=Bounds.GetCenter(),Size=Bounds.GetSize();
    const FVector Toward=Event.Source-Center;
    const bool FaceX=FMath::Abs(Toward.X/Size.X)>FMath::Abs(Toward.Y/Size.Y);
    const FVector Normal=FaceX?FVector(Toward.X>=0?1:-1,0,0):FVector(0,Toward.Y>=0?1:-1,0);
    const FVector Along(-Normal.Y,Normal.X,0);
    const double Span=FaceX?Size.Y:Size.X,Depth=FaceX?Size.X:Size.Y;
    const int32 Floors=FMath::Clamp(FMath::FloorToInt(Size.Z/310.),1,4);
    const int32 Columns=FMath::Clamp(FMath::FloorToInt(Span/340.),1,3);
    auto* SootMaterial=DisasterMaterial(TEXT("M_FireSoot"));
    FCollisionQueryParams SupportQuery(SCENE_QUERY_STAT(MRFireSupport),false);
    int32 Sources=0;
    for(int32 Floor=0;Floor<Floors;++Floor)for(int32 Column=0;Column<Columns;++Column)
    {
        FVector Window=Center+Normal*(Depth*.5+12)+Along*((Column-(Columns-1)*.5)*FMath::Min(Span*.28,320.));
        Window.Z=Bounds.Min.Z+150+Floor*310.;
        FHitResult Wall;
        const FVector Ledge=Window-FVector(0,0,85);
        if(!GetWorld()->LineTraceSingleByChannel(Wall,Ledge+Normal*60,Ledge-Normal*200,ECC_Visibility,SupportQuery))continue;
        const float Delay=Floor*7.f+Column*1.5f;
        const FName DelayTag(*FString::Printf(TEXT("IgnitionDelay_%.2f"),Delay));
        if(auto* Flame=SpawnDisasterEffect(TEXT("BuildingFire"),Window,FVector(.58,.58,.78),Event))
            Flame->ComponentTags.Add(DelayTag);
        ++Sources;
        if(SootMaterial)
        {
            auto* Stain=NewObject<UDecalComponent>(this);AddInstanceComponent(Stain);
            Stain->SetupAttachment(GetRootComponent());Stain->SetMobility(EComponentMobility::Movable);
            Stain->SetRelativeLocation(Window+Normal*8+FVector(0,0,110));
            Stain->SetRelativeRotation(FRotationMatrix::MakeFromX(-Normal).Rotator());
            Stain->DecalSize=FVector(60,175,240);
            auto* Dynamic=UMaterialInstanceDynamic::Create(SootMaterial,Stain);
            Dynamic->SetScalarParameterValue(TEXT("BurnFraction"),0);Stain->SetDecalMaterial(Dynamic);
            Stain->ComponentTags={FName(*Event.Id),TEXT("Scorch"),DelayTag};
            Stain->RegisterComponent();HazardVisuals.Add(Stain);
        }
    }
    for(int32 I=-1;I<=1;++I)
    {
        FVector Roof=Center+Along*(I*FMath::Min(Span*.25,360.));
        Roof.Z=Bounds.Max.Z+6;
        FHitResult Support;
        if(!GetWorld()->LineTraceSingleByChannel(Support,Roof+FVector(0,0,180),Roof-FVector(0,0,180),ECC_Visibility,SupportQuery)||
            Support.ImpactNormal.Z<.5||FMath::Abs(Support.ImpactPoint.Z-Bounds.Max.Z)>120)continue;
        Roof.Z=Support.ImpactPoint.Z+8;
        if(auto* Flame=SpawnDisasterEffect(TEXT("BuildingFire"),Roof,FVector(1.6,1.6,1.8),Event))
            Flame->ComponentTags.Add(TEXT("IgnitionDelay_28"));
        ++Sources;
    }
    // A completely ruined source may still contain combustible debris. It
    // burns at its real ground support, never at nonexistent upper windows.
    if(Sources==0)
    {
        FHitResult Ground;
        if(GetWorld()->LineTraceSingleByChannel(Ground,Event.Source+FVector(0,0,180),Event.Source-FVector(0,0,300),ECC_Visibility,SupportQuery))
            SpawnDisasterEffect(TEXT("BuildingFire"),Ground.ImpactPoint+FVector(0,0,8),FVector(1.3),Event);
    }
    int32 LightCount=0;
    for(const auto& Item:HazardVisuals)if(Cast<UPointLightComponent>(Item))++LightCount;
    if(LightCount<8)
    {
        auto* Light=NewObject<UPointLightComponent>(this);AddInstanceComponent(Light);
        Light->SetupAttachment(GetRootComponent());Light->SetMobility(EComponentMobility::Movable);
        FVector Position=Center+Normal*(Depth*.5+150);Position.Z=Bounds.Min.Z+350;
        Light->SetRelativeLocation(Position);Light->SetIntensity(60000);
        Light->SetLightColor(FLinearColor(1,.24,.025));Light->SetAttenuationRadius(2000);
        Light->SetCastShadows(false);Light->ComponentTags={FName(*Event.Id),TEXT("FireLight")};
        Light->RegisterComponent();HazardVisuals.Add(Light);
    }
}
