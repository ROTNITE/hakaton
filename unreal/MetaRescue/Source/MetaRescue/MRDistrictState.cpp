#include "MRWorld.h"
#include "MRAgent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/PointLightComponent.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Engine/World.h"

float AMRWorld::WaterDepth(const FVector& P) const
{
    if(!bRescueQuarter)return 0;
    if(!bCityLayout&&FMath::Abs(P.X-12850)<900&&FMath::Abs(P.Y-13000)<1050)return 60;
    const FIntPoint Tile(FMath::FloorToInt(P.X/50),FMath::FloorToInt(P.Y/50));
    const float* Ground=FloodGroundHeights.Find(Tile);
    return Ground&&Environment.Depth(P)>0?FMath::Max(0.f,Environment.Depth(P)+4-*Ground):0.f;
}
float AMRWorld::MovementCost(const FVector& P) const
{return bRescueQuarter?(bCityLayout?CityGroundCost(P):1.f)*FMath::Max(Environment.Cost(P,false),WaterDepth(P)>4?2.f:1.f):1.f;}
float AMRWorld::GroundSpeedFactor(const FVector& P) const
{ return 1.f/MovementCost(P); }
bool AMRWorld::IsUnsafeGround(const FVector& P) const
{
    return bRescueQuarter&&(WaterDepth(P)>MRDistrictSettings::UnsafeWaterCm||Environment.Unsafe(P,false)||
        (!bCityLayout&&P.X>6800&&P.X<8800&&P.Y>14075&&P.Y<14925)||
        (bCityLayout&&(P.X<0||P.Y<0||P.X>GridSize*1000||P.Y>GridSize*1000)));
}
bool AMRWorld::HasRadio(const FVector& P) const
{
    return !bRescueQuarter||FVector::Dist2D(P,Base)<7600||
        (bRelayOnline&&FVector::Dist2D(P,FVector(6000,9700,0))<8800);
}
float AMRWorld::SensorRange(const FVector& P) const { return 3600; }
float AMRWorld::VisibilityQuality(const FVector& P) const { return bRescueQuarter?Environment.Visibility(P):1; }
int32 AMRWorld::PendingReports() const
{
    int32 Count=0;for(const auto& T:Targets)Count+=T.ObservedAt>=0&&!T.bDiscovered;return Count;
}
void AMRWorld::TickDistrict(float Dt)
{
    const float Time=GetWorld()->GetTimeSeconds();
    for(const auto& E:Environment.Advance(Time)){RecordEnvironmentEvent(E);if(E.Rejection.IsEmpty())ApplyDisturbance(E);}
    TickHazardVisuals(Dt);
    bFloodActive=false;bDustActive=false;
    for(const auto& E:Environment.Applied)
    {
        bFloodActive|=E.Kind==EMRDisturbance::Flood;
        bDustActive|=E.Kind==EMRDisturbance::Collapse&&Time<E.Time+24;
    }
    const float DoorAlpha=FMath::SmoothStep(9.f,13.f,Time);
    if(ServiceVan)
    {
        const FVector Current=ServiceVan->GetComponentLocation();
        const FVector Target=VanPark+FVector(0,650*(1-FMath::SmoothStep(0.f,8.f,Time)),0);
        const FVector Next=FMath::VInterpConstantTo(Current,Target,Dt,110);
        FCollisionQueryParams Params(SCENE_QUERY_STAT(MRVanSafety),false);
        TArray<USceneComponent*> Descendants;ServiceVan->GetChildrenComponents(true,Descendants);
        for(auto* C:Descendants)if(auto* Primitive=Cast<UPrimitiveComponent>(C))Params.AddIgnoredComponent(Primitive);
        TArray<FHitResult> Hits;
        GetWorld()->SweepMultiByChannel(Hits,Current+FVector(0,0,145),Next+FVector(0,0,145),ServiceVan->GetComponentQuat(),
            ECC_Visibility,FCollisionShape::MakeBox(FVector(295,118,125)),Params);
        bool Clear=true;for(const auto& Hit:Hits)if(Hit.bBlockingHit&&Hit.ImpactNormal.Z<.45)Clear=false;
        if(Clear){ServiceVan->SetWorldLocation(Next);VanWheelTravel+=FVector::Dist(Current,Next);}
    }
    for(auto& Part:DistrictMechanisms)
    {
        if(!Part.Mesh)continue;
        if(Part.Role==TEXT("sensor_head"))
            Part.Mesh->SetRelativeRotation(FRotator(0,FMath::Sin(Time*.45f+Part.Rest.GetLocation().X*.001f)*50,0));
        else if(Part.Role==TEXT("case_lid"))
            Part.Mesh->SetRelativeRotation(Part.Rest.GetRotation()*FQuat(FVector::ForwardVector,
                FMath::DegreesToRadians(100*(FMath::SmoothStep(12.f,15.f,Time)-FMath::SmoothStep(75.f,78.f,Time)))));
        else if(Part.Role==TEXT("van_door"))
            Part.Mesh->SetRelativeRotation(Part.Rest.GetRotation()*FQuat(FVector::UpVector,
                FMath::DegreesToRadians(-Part.Side*88*DoorAlpha)));
        else if(Part.Role==TEXT("wheel"))
        {
            const float Travel=VanWheelTravel;
            Part.Mesh->SetRelativeRotation(Part.Rest.GetRotation()*FQuat(FVector(0,1,0),-Travel/FMath::Max(1.f,Part.Radius)));
        }
        else if(Part.Role==TEXT("beacon"))
        {
            if(auto* Mat=Cast<UMaterialInstanceDynamic>(Part.Mesh->GetMaterial(0)))
                Mat->SetScalarParameterValue(TEXT("Intensity"),FMath::Fmod(Time*2+Part.Side*.25f,1.f)<.18f?20:1);
        }
        else if(Part.Role==TEXT("generator_engine"))
            Part.Mesh->SetRelativeLocation(Part.Rest.GetLocation()+FVector(0,0,FMath::Sin(Time*47)*.06f));
    }
    TArray<UPointLightComponent*> Lamps;GetComponents(Lamps);
    for(auto* Lamp:Lamps)if(Lamp->ComponentHasTag(TEXT("RelayStatus")))
        Lamp->SetLightColor(bRelayOnline?FLinearColor(.12,1,.3):FLinearColor(1,.18,.02));
}
bool AMRWorld::RestrictionOnRoute(const FVector& Start,const FVector& End,const FString& Kind,double Radius,double HalfHeight,FBox& Blocker) const
{
    for(const auto& Pair:CoreRestrictions)
    {
        const auto& Region=Pair.Value;
        if(Region.AllowedKinds.Contains(Kind))continue;
        const FBox Expanded=Region.Bounds.ExpandBy(FVector(Radius,Radius,HalfHeight));
        // Existing occupants may withdraw. Entering or crossing from outside
        // must brake using the same physical swept-distance guard as hazards.
        if(!Expanded.IsInsideOrOn(Start)&&FMath::LineBoxIntersection(Expanded,Start,End,End-Start))
        {Blocker=Region.Bounds;return true;}
    }
    return false;
}

