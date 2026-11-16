#include "MRAgent.h"
#include "MRWorld.h"
#include "MRWatercraftHydro.h"
#include "MRCoreJson.h"
#include "MRCoreValues.h"
#include "Components/BoxComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/World.h"

using namespace MRCoreValues;

namespace
{
void RigSegment(UStaticMeshComponent* Mesh,FVector A,FVector B,double Diameter)
{
    const FVector Delta=B-A;
    Mesh->SetWorldTransform(FTransform(FQuat::FindBetweenNormals(FVector::UpVector,Delta.IsNearlyZero()?FVector::UpVector:Delta.GetSafeNormal()),
        (A+B)*.5,FVector(Diameter/100,Diameter/100,FMath::Max(1.,Delta.Size())/100)));
    Mesh->SetVisibility(true);
}
}

bool AMRAgent::BeginWatercraftPickup(int32 Index,const FString& Id)
{
    if(!Mission||!Mission->Targets.IsValidIndex(Index)||!IsOperational()||bCarrying||bWatercraftMoored||
       State==TEXT("loading")||State==TEXT("unloading")||Body->GetPhysicsLinearVelocity().Size2D()>30)return false;
    auto& Target=Mission->Targets[Index];
    if(Target.bAssigned||Target.bRescued||!Target.Visual||!Target.ShoreStation.IsEmpty()||
       FVector::Dist2D(GetActorLocation(),Target.Position)>440||
       FMath::Abs(GetActorLocation().Z-Target.Position.Z)>350||WatercraftProfile->PayloadKg>WatercraftProfile->PayloadLimitKg)return false;
    const FVector Mast=GetActorTransform().TransformPosition(FVector(60,70,0));
    if(FVector::Dist2D(Mast,Target.Position)>500)return false;
    if(auto* Source=Target.SupportCarrier.Get())
    {if(Source->IsOperational())return false;if(Source->bRescueWatercraft)Source->SetWatercraftPayloadKg(0);}
    else if(Target.FloatBody&&(Target.FloatBody->GetPhysicsLinearVelocity()-Body->GetPhysicsLinearVelocity()).Size2D()>30)return false;
    if(Target.FloatBody)Target.FloatBody->SetSimulatePhysics(false);
    Target.Visual->DetachFromActor(FDetachmentTransformRules::KeepWorldTransform);Target.Visual->SetActorEnableCollision(false);
    PickupStart=Target.Visual->GetActorLocation();PickupRotation=Target.Visual->GetActorQuat();Target.SupportCarrier.Reset();
    Target.FloatDisplacedM3=0;
    Target.bAssigned=true;++Target.ObservationEpoch;TargetIndex=Index;CommandId=Id;
    Path.Empty();PathIndex=0;bExternalHold=true;WatercraftHoldPosition=GetActorLocation();
    ServiceShoreStation.Empty();ServiceRemaining=12;ServiceElapsed=0;State=TEXT("loading");return true;
}

bool AMRAgent::BeginDisembark(const FString& StationId,const FString& Id)
{
    if(!bRescueWatercraft||!Mission||!bCarrying||!Mission->Targets.IsValidIndex(TargetIndex)||!IsOperational()||
       State==TEXT("loading")||State==TEXT("unloading")||Body->GetPhysicsLinearVelocity().Size2D()>30)return false;
    const auto Station=Mission->ShoreStation();if(!Station||Text(Station,TEXT("id"))!=StationId)return false;
    const auto& XY=Station->GetArrayField(TEXT("boat_position_xy"));const FVector DockPoint(XY[0]->AsNumber()*100,XY[1]->AsNumber()*100,GetActorLocation().Z);
    if(FVector::Dist2D(GetActorLocation(),DockPoint)>85||
       FMath::Abs(FMath::FindDeltaAngleDegrees(GetActorRotation().Yaw,Station->GetNumberField(TEXT("boat_yaw_degrees"))))>15)return false;
    for(int32 I=0;I<Mission->Targets.Num();++I)if(I!=TargetIndex&&!Mission->Targets[I].bRescued&&Mission->Targets[I].ShoreStation==StationId)return false;
    for(const auto& Other:Mission->Agents)if(Other!=this&&Other->ServiceShoreStation==StationId&&Other->State==TEXT("unloading"))return false;
    FVector Landing;MRCoreJson::Point(Field(Station,TEXT("patient_position")),Landing);Landing*=100;
    if(Mission->WaterDepth(Landing+FVector(0,0,40))>1)return false;
    for(int32 I=0;I<Mission->Targets.Num();++I)if(I!=TargetIndex)
    {
        const auto& Other=Mission->Targets[I];
        if(!Other.bRescued&&FVector::Dist2D(Other.Position,Landing)<250&&FMath::Abs(Other.Position.Z-Landing.Z)<150)return false;
    }
    auto& Target=Mission->Targets[TargetIndex];PickupStart=Target.Visual->GetActorLocation();PickupRotation=Target.Visual->GetActorQuat();
    CommandId=Id;Path.Empty();PathIndex=0;bExternalHold=true;WatercraftHoldPosition=GetActorLocation();
    ServiceShoreStation=StationId;ServiceRemaining=12;ServiceElapsed=0;State=TEXT("unloading");return true;
}

void AMRAgent::TickWatercraftService(float Dt)
{
    if((State!=TEXT("loading")&&State!=TEXT("unloading"))||!Mission->Targets.IsValidIndex(TargetIndex)||!IsOperational())return;
    auto& Target=Mission->Targets[TargetIndex];if(!Target.Visual)return;
    if(Body->GetPhysicsLinearVelocity().Size2D()>30||FMath::Abs(GetActorRotation().Roll)>12||FMath::Abs(GetActorRotation().Pitch)>12)return;
    const bool Loading=State==TEXT("loading");const double Deck=(WatercraftProfile->DeckAboveKeelM-WatercraftProfile->BodyAboveKeelM)*100;
    FVector End=GetActorTransform().TransformPosition(WatercraftBedLocal+FVector(0,0,Target.VisualAnchorOffsetCm));
    if(!Loading)
    {
        const auto Station=Mission->ShoreStation();if(!Station)return;
        MRCoreJson::Point(Field(Station,TEXT("patient_position")),End);End*=100;End.Z+=Target.VisualAnchorOffsetCm;
    }
    const double Lift=FMath::Max(PickupStart.Z,End.Z)+90;
    auto CargoAt=[&](double T)
    {
        if(T<3)return FMath::Lerp(PickupStart,FVector(PickupStart.X,PickupStart.Y,Lift),FMath::SmoothStep(0.,3.,T));
        if(T<9)return FMath::Lerp(FVector(PickupStart.X,PickupStart.Y,Lift),FVector(End.X,End.Y,Lift),FMath::SmoothStep(3.,9.,T));
        return FMath::Lerp(FVector(End.X,End.Y,Lift),End,FMath::SmoothStep(9.,12.,T));
    };
    const FVector PreviousCargo=Target.Visual->GetActorLocation();const double Gravity=FMath::Abs(GetWorld()->GetGravityZ())/100;
    auto LiftWh=[&](FVector P){return Loading?WatercraftProfile->PayloadKg*Gravity*FMath::Max(0.,P.Z-PreviousCargo.Z)/100/(.6*3600):0.;};
    double T=FMath::Min(12.,double(ServiceElapsed)+Dt);
    if(!bUnlimitedEnergy&&LiftWh(CargoAt(T))>Energy)
    {
        double Low=ServiceElapsed,High=T;
        for(int32 I=0;I<20;++I){const double Mid=(Low+High)*.5;if(LiftWh(CargoAt(Mid))>Energy)High=Mid;else Low=Mid;}
        T=Low;
    }
    const FVector Cargo=CargoAt(T);Spend(LiftWh(Cargo),ServiceWh);ServiceElapsed=T;ServiceRemaining=12-T;
    Target.Visual->SetActorLocation(Cargo);
    Target.Visual->SetActorRotation(FQuat::Slerp(PickupRotation,Loading?GetActorQuat():FQuat::Identity,FMath::SmoothStep(3.,9.,T)));
    Target.Position=Cargo;
    // During loading the boat-mounted hoist takes the weight. At the pier a
    // fixed gantry takes it off the boat as soon as the stretcher lifts free.
    const double Fraction=Loading?FMath::Clamp((Cargo.Z-PickupStart.Z)/15,0.,1.):
        T<3?1.-FMath::Clamp((Cargo.Z-PickupStart.Z)/15,0.,1.):0.;
    SetWatercraftPayloadKg(WatercraftProfile->PayloadKg*Fraction);
    // The load's lever arm follows the suspended stretcher, including pitching
    // moments while it is outside the deck. The hoist supplies the constraint.
    const FVector CG=Target.Visual->GetActorTransform().TransformPosition(FVector(0,0,Target.VisualAnchorOffsetCm>0?-6.2:35));
    MoveWatercraftPayloadTo(CG);
    const FVector Mast=GetActorTransform().TransformPosition(FVector(60,70,Deck+250));
    const FVector Tip(Cargo.X,Cargo.Y,Loading?Mast.Z:Mission->ShoreHoistHeightCm());
    if(Loading)RigSegment(WatercraftBoom,Mast,Tip,10);else WatercraftBoom->SetVisibility(false);
    WatercraftTrolley->SetWorldLocation(Tip);WatercraftTrolley->SetWorldRotation(FRotator::ZeroRotator);WatercraftTrolley->SetVisibility(true);
    RigSegment(WatercraftCable,Tip,Cargo+FVector(0,0,35),2);
    int32 SlingIndex=0;
    for(double X:{-80.,80.})for(double Y:{-24.,24.})
        RigSegment(WatercraftSlings[SlingIndex++],Cargo+FVector(0,0,35),
            Target.Visual->GetActorTransform().TransformPosition(FVector(X,Y,15-Target.VisualAnchorOffsetCm)),1.2);
    if(ServiceRemaining>0)return;
    WatercraftCable->SetVisibility(false);WatercraftBoom->SetVisibility(false);WatercraftTrolley->SetVisibility(false);
    for(auto& Sling:WatercraftSlings)Sling->SetVisibility(false);
    if(Loading)
    {
        Target.Visual->AttachToActor(this,FAttachmentTransformRules::KeepWorldTransform);
        Target.Visual->SetActorRelativeLocation(WatercraftBedLocal+FVector(0,0,Target.VisualAnchorOffsetCm));Target.Visual->SetActorRelativeRotation(FRotator::ZeroRotator);
        Target.SupportCarrier=this;Target.ShoreStation.Empty();bCarrying=true;SetWatercraftPayloadKg(WatercraftProfile->PayloadKg);
        State=TEXT("loaded");Mission->AppendEvent(TEXT("person_loaded"),Target.Id);
    }
    else
    {
        Target.Visual->DetachFromActor(FDetachmentTransformRules::KeepWorldTransform);Target.SupportCarrier.Reset();
        Target.Visual->SetActorLocation(End);Target.Visual->SetActorRotation(FRotator::ZeroRotator);Target.Position=End;
        Target.ShoreStation=ServiceShoreStation;Target.bAssigned=false;++Target.ObservationEpoch;
        if(Target.FloatBody)
        {
            Target.Visual->SetActorEnableCollision(true);Target.FloatBody->SetSimulatePhysics(true);
            Target.FloatBody->SetPhysicsLinearVelocity(FVector::ZeroVector);Target.FloatBody->SetPhysicsAngularVelocityInRadians(FVector::ZeroVector);
        }
        bCarrying=false;SetWatercraftPayloadKg(0);State=TEXT("idle");Mission->AppendEvent(TEXT("person_disembarked"),Target.Id);TargetIndex=INDEX_NONE;
    }
    ServiceShoreStation.Empty();
}
