#include "MRAgent.h"
#include "MRWorld.h"
#include "Components/BoxComponent.h"
#include "Engine/World.h"

void AMRAgent::ForgetCompletedCoreCommand(const FString& Id)
{
    // Exact Core retries are owned by the server's disk replay. The local
    // digest is only needed while that physical command is pending.
    if(Mission&&Mission->bCoreControlled)AcceptedCommands.Remove(Id);
}

void AMRAgent::ResetForEpisode(const FTransform& Pose,bool UnlimitedEnergy)
{
    AcceptedCommands.Empty();Path.Empty();PathIndex=0;TargetIndex=-1;
    bCarrying=false;bExternalHold=false;bRouteBlocked=false;bReverseInitialLeg=false;bFaulted=false;
    FailureReason.Empty();SpeedFactor=SensorFactor=1;
    CommandId.Empty();StopReason.Empty();StopObstacle.Empty();SensedBlocker=FBox(ForceInit);IntendedVelocity=FVector::ZeroVector;
    ServiceRemaining=0;ServiceElapsed=0;RampDeployment=0;ObstructionTime=0;DepartAt=0;
    SetActorTransform(Pose,false,nullptr,ETeleportType::TeleportPhysics);
    if(Body->IsSimulatingPhysics())
    {
        if(Category.IsEmpty()){Body->SetMassOverrideInKg(NAME_None,bAerial?12.f:240.f);Body->SetCenterOfMass(FVector::ZeroVector);}
        Body->SetPhysicsLinearVelocity(FVector::ZeroVector);Body->SetPhysicsAngularVelocityInRadians(FVector::ZeroVector);
    }
    Previous=Pose.GetLocation();Dock=Pose.GetLocation();FlightAltitude=Dock.Z;
    State=bAerial?TEXT("landed"):TEXT("idle");Energy=BatteryCapacityWh;
    ConsumedWh=MotionWh=StandbyWh=SensorWh=ServiceWh=ChargedWh=0;DistanceTravelled=0;
    GroundContacts=0;AgentContacts=0;bUnlimitedEnergy=UnlimitedEnergy;WaitingSince=-1;
}

bool AMRAgent::BeginPickup(int32 Index,const FString& Id)
{
    if(!Mission||!CanCarry()||bCarrying||IsCharging()||State==TEXT("loading")||State==TEXT("unloading")||
       !Mission->Targets.IsValidIndex(Index)||!IsOperational())return false;
    auto& T=Mission->Targets[Index];
    if(T.bAssigned||T.bRescued||FVector::Dist2D(GetActorLocation(),T.Position)>370||Body->GetPhysicsLinearVelocity().Size()>30)return false;
    TargetIndex=Index;T.bAssigned=true;CommandId=Id;Path.Empty();PathIndex=0;bExternalHold=true;
    State=TEXT("loading");ServiceRemaining=8;ServiceElapsed=0;
    ServiceHeading=(GetActorLocation()-T.Position).Rotation().Yaw;
    if(T.Visual){PickupStart=T.Visual->GetActorLocation();PickupRotation=T.Visual->GetActorQuat();}
    return true;
}

bool AMRAgent::BeginHandover(const FString& Id)
{
    if(!Mission||!CanCarry()||!bCarrying||!Mission->Targets.IsValidIndex(TargetIndex)||
       State==TEXT("unloading")||IsCharging()||!IsOperational()||FVector::Dist2D(GetActorLocation(),Mission->Base)>500||
       Body->GetPhysicsLinearVelocity().Size()>30)return false;
    CommandId=Id;Path.Empty();PathIndex=0;bExternalHold=true;State=TEXT("unloading");
    ServiceRemaining=6;ServiceElapsed=0;ServiceHeading=GetActorRotation().Yaw;return true;
}

void AMRAgent::Spend(double Wh,double& Expense)
{
    const double Used=bUnlimitedEnergy?Wh:FMath::Min(Energy,Wh);
    Expense+=Used;ConsumedWh+=Used;
    if(!bUnlimitedEnergy)Energy-=Used;
}

void AMRAgent::AccountPoweredTime(double Dt)
{
    if(Energy<=0)return;
    const bool Airborne=bAerial&&State!=TEXT("landed")&&!IsCharging();
    const bool Service=State==TEXT("loading")||State==TEXT("unloading");
    Spend(Dt*(Airborne?130.:bAerial?12.:35.)/3600.,StandbyWh);
    if(!bFaulted&&CanSense())Spend(Dt*(bAerial?14.:9.)/3600.,SensorWh);
    if(Service)Spend(Dt*55./3600.,ServiceWh);
}

bool AMRAgent::ChargeDocked(const FVector& Position,double RadiusCm) const
{
    const FVector Pose=GetActorLocation();
    if(FVector::Dist2D(Pose,Position)>RadiusCm||Body->GetPhysicsLinearVelocity().Size()>25)return false;
    if(!bAerial)return FMath::Abs(Pose.Z-Position.Z)<125;
    return (State==TEXT("landed")||State==TEXT("power_lost")||IsCharging())&&FMath::Abs(Pose.Z-Position.Z)<25;
}

bool AMRAgent::BeginCharge(const FString& Id)
{
    if(bUnlimitedEnergy||IsCharging()||State==TEXT("loading")||State==TEXT("unloading"))return false;
    CommandId=Id;Path.Empty();PathIndex=0;bExternalHold=true;IntendedVelocity=FVector::ZeroVector;
    StopReason.Empty();State=TEXT("charge_wait");return true;
}

double AMRAgent::ReceiveCharge(double AvailableWh)
{
    State=TEXT("charging");
    const double Accepted=FMath::Min(AvailableWh,FMath::Max(0.,BatteryCapacityWh-Energy));
    Energy+=Accepted;ChargedWh+=Accepted;
    if(Energy>0&&!bFaulted)FailureReason.Empty();
    return Accepted;
}

void AMRAgent::EndCharge()
{
    State=bAerial?TEXT("landed"):bCarrying?TEXT("loaded"):TEXT("idle");
}

int32 AMRAgent::StopAndRelease(const FString& Reason)
{
    bExternalHold=true;Path.Empty();PathIndex=0;State=Energy>0?TEXT("faulted"):TEXT("power_lost");
    StopReason=FailureReason=Reason;IntendedVelocity=FVector::ZeroVector;
    if(bAerial)FlightAltitude=GetActorLocation().Z;
    if(!Mission->Targets.IsValidIndex(TargetIndex))return INDEX_NONE;
    auto& Target=Mission->Targets[TargetIndex];
    if(Target.Visual)
    {
        Target.Visual->DetachFromActor(FDetachmentTransformRules::KeepWorldTransform);
        Target.Position=Target.Visual->GetActorLocation();
    }
    Target.bAssigned=false;Target.bDiscovered=false;Target.DiscoveredAt=-1;++Target.ObservationEpoch;
    const int32 Released=TargetIndex;TargetIndex=INDEX_NONE;bCarrying=false;
    Body->SetMassOverrideInKg(NAME_None,240.f);Body->SetCenterOfMass(FVector::ZeroVector);
    return Released;
}
