#include "MRAgent.h"
#include "MRWorld.h"
#include "Components/BoxComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "PhysicalMaterials/PhysicalMaterial.h"
#include "Dom/JsonObject.h"

void AMRAgent::InitializeCompetition(AMRWorld* InWorld,int32 InId,const FString& Mobility,const FString& Site,const FBox& Limits)
{
    Mission=InWorld;AgentId=InId;Category=Mobility;InfrastructureSite=Site;MediumLimits=Limits;
    Dock=GetActorLocation();Previous=Dock;
    if(!MediumLimits.IsValid)
    {
        Body->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        if(IsSpatial())
        {
            // The service actor controls the already placed sensor instrument.
            // Do not draw another pole and camera on top of the real model.
            if(Mission->CityLayout)for(const auto& Entry:Mission->CityLayout->GetArrayField(TEXT("infrastructure")))
            {
                const auto Node=Entry->AsObject();
                if(Node->GetStringField(TEXT("id"))==Site&&Node->GetStringField(TEXT("kind"))==TEXT("sensor_node"))return;
            }
            const double Height=FMath::Max(60.,Dock.Z);
            Part(TEXT("Cylinder"),FVector(0,0,-Height*.5),FVector(38,38,Height),TEXT("MI_Metal"));
            Part(TEXT("Cylinder"),FVector(0,0,-Height+3),FVector(65,65,6),TEXT("MI_Metal"));
            Part(TEXT("Cube"),FVector::ZeroVector,FVector(50,46,29),TEXT("MI_Dark"));
            Part(TEXT("Sphere"),FVector(24,0,0),FVector(14,24,24),TEXT("MI_CyanGlow"));
        }
        return;
    }
    const bool Underground=Category==TEXT("underground");
    const bool Surface=Category==TEXT("surface_water");
    Body->SetBoxExtent(Underground?FVector(55,34,25):FVector(71,40,Surface?50:25));
    Body->SetMassOverrideInKg(NAME_None,Underground?82:Surface?61:45);
    Body->SetEnableGravity(Underground);Body->SetLinearDamping(Underground?.32:1.05);
    if(Underground)
    {
        // The contact material models rolling resistance for driven tracks.
        auto* TrackContact=NewObject<UPhysicalMaterial>(this);
        TrackContact->Friction=.15f;TrackContact->StaticFriction=.18f;
        TrackContact->bOverrideFrictionCombineMode=true;TrackContact->FrictionCombineMode=EFrictionCombineMode::Min;
        Body->SetPhysMaterialOverride(TrackContact);
    }
    MaxSpeed=Underground?190:Surface?240:165;
    const FString Model=Underground?TEXT("SM_HuskyTunnel"):Surface?TEXT("SM_BlueBoatSurface"):TEXT("SM_BlueROV2Submerged");
    const FString Package=TEXT("/Game/RescueAssets/Competition/")+Model+TEXT(".")+Model;
    if(auto* Mesh=LoadObject<UStaticMesh>(nullptr,*Package))
    {
        auto* Visual=NewObject<UStaticMeshComponent>(this);
        AddInstanceComponent(Visual);
        Visual->SetupAttachment(Body);
        Visual->SetMobility(EComponentMobility::Movable);
        Visual->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        Visual->SetStaticMesh(Mesh);
        Visual->SetRelativeLocation(FVector(0,0,Underground?-6.5:Surface?-20.:0.));
        Visual->RegisterComponent();
        UE_LOG(LogTemp,Display,TEXT("MR_COMPETITION_VEHICLE %s %s; native contact body preserved"),*Category,*Mesh->GetPathName());
        Body->SetSimulatePhysics(true);
        return;
    }
    Part(Underground?TEXT("Cube"):TEXT("Sphere"),FVector(0,0,Surface?-20:0),FVector(139,79,49),
        Underground?TEXT("MI_Orange"):Surface?TEXT("MI_White"):TEXT("MI_Teal"));
    Part(TEXT("Cube"),FVector(-15,0,Surface?12:28),FVector(62,44,18),TEXT("MI_Dark"));
    Part(TEXT("Sphere"),FVector(55,0,Surface?0:12),FVector(14,20,17),TEXT("MI_CyanGlow"));
    for(float Side:{-1.f,1.f})
        Part(Underground?TEXT("Cube"):TEXT("Sphere"),FVector(0,Side*40,Surface?-36:-8),FVector(120,21,20),TEXT("MI_Rubber"));
    Body->SetSimulatePhysics(true);
}

bool AMRAgent::MediumPointAllowed(const FVector& Position) const
{
    if(!MediumLimits.IsValid)return false;
    const FVector Half=Body->GetScaledBoxExtent();
    if(Category==TEXT("surface_water")&&FMath::Abs(Position.Z-Dock.Z)>12)return false;
    if(Category==TEXT("underground")&&FMath::Abs(Position.Z-(MediumLimits.Min.Z+Half.Z))>60)return false;
    const double Margin=FMath::Sqrt(FMath::Square(Half.X)+FMath::Square(Half.Y));
    const double VerticalMargin=Category==TEXT("surface_water")?0:Category==TEXT("underground")?Half.Z-1.5:Half.Z;
    const FVector Pad(Margin,Margin,VerticalMargin);
    return FBox(MediumLimits.Min+Pad,MediumLimits.Max-Pad).IsInsideOrOn(Position);
}

void AMRAgent::DriveCompetitionMedium(float Dt)
{
    const FVector Position=GetActorLocation();
    const FVector Velocity=Body->GetPhysicsLinearVelocity();
    const bool Underground=Category==TEXT("underground");
    const bool Surface=Category==TEXT("surface_water");
    FVector Desired=FVector::ZeroVector;
    if(IsOperational()&&!bExternalHold&&Path.IsValidIndex(PathIndex))
    {
        FVector Delta=Path[PathIndex]-Position;
        if(Underground||Surface)Delta.Z=0;
        if(Delta.Size()<38)
        {
            ++PathIndex;if(RouteFinished())Arrived();
        }
        else Desired=Delta.GetSafeNormal()*FMath::Min<double>(MaxSpeed*SpeedFactor,FMath::Max(55.,Delta.Size()*2.));
    }
    IntendedVelocity=Desired;
    if(!Desired.IsNearlyZero())
    {
        FHitResult Hit;FCollisionQueryParams Query(SCENE_QUERY_STAT(MediumRoute),false,this);
        const FVector Direction=Desired.GetSafeNormal();
        const FVector Probe=Position+FVector(0,0,Underground?2.:0.);
        const FVector End=Probe+Direction*FMath::Max(45.,Velocity.Size()*.35);
        const FVector Half=Body->GetScaledBoxExtent();
        if(!MediumPointAllowed(End)){Desired=FVector::ZeroVector;StopReason=TEXT("medium_boundary");}
        else if(Mission->RestrictionOnRoute(Probe,End,Category,Half.Size2D(),Half.Z,SensedBlocker))
        {Desired=FVector::ZeroVector;StopReason=TEXT("restricted_volume");}
        else if(GetWorld()->SweepSingleByChannel(Hit,Probe,End,GetActorQuat(),ECC_Visibility,
            FCollisionShape::MakeBox(Body->GetScaledBoxExtent()*.94),Query))
        {Desired=FVector::ZeroVector;StopReason=TEXT("medium_obstacle");}
        else StopReason.Empty();
    }
    if(Surface)Desired.Z=FMath::Clamp((Dock.Z-Position.Z)*2.,-65.,65.);
    FVector Acceleration=(Desired-Velocity)*5.;
    if(Underground)Acceleration.Z=0;
    Body->AddForce(Acceleration.GetClampedToMaxSize(1400.),NAME_None,true);
    const FVector Angular=Body->GetPhysicsAngularVelocityInRadians();
    FVector Torque=FVector::CrossProduct(GetActorUpVector(),FVector::UpVector)*46.-Angular*8.;
    if(Desired.Size2D()>20)
        Torque.Z+=FMath::DegreesToRadians(FMath::FindDeltaAngleDegrees(GetActorRotation().Yaw,Desired.Rotation().Yaw))*10.;
    Body->AddTorqueInRadians(Torque,NAME_None,true);
}
