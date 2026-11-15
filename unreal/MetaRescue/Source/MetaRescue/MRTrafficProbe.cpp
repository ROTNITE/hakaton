#include "MRWorld.h"
#include "MRAgent.h"
#include "Components/BoxComponent.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Engine/World.h"

void AMRAgent::ResetTestPose(FVector P,FRotator R)
{
    // Only called by the explicit -MRTrafficProbe fixture, before telemetry.
    Body->SetSimulatePhysics(false);SetActorLocationAndRotation(P,R);
    Body->SetSimulatePhysics(true);Body->SetPhysicsLinearVelocity(FVector::ZeroVector);
    Body->SetPhysicsAngularVelocityInRadians(FVector::ZeroVector);
    Previous=P;DistanceTravelled=0;StopReason.Empty();bRouteBlocked=false;
}
void AMRWorld::InitializeTrafficProbe()
{
    if(!FParse::Value(FCommandLine::Get(),TEXT("MRTrafficProbe="),TrafficProbe))return;
    bDemoDispatcherEnabled=false;
    auto Find=[&](bool Air,int32 Id)->AMRAgent*
    {for(AMRAgent* A:Agents)if(A->bAerial==Air&&A->AgentId==Id)return A;return nullptr;};
    auto Route=[&](bool Air,int32 Id,FVector Start,float Yaw,TArray<FVector> Points)
    {
        if(auto* A=Find(Air,Id))
        {A->ResetTestPose(Start,FRotator(0,Yaw,0));A->AcceptRoute(TEXT("probe_initial"),Points);}
    };
    if(TrafficProbe==TEXT("following"))
    {
        Route(false,0,FVector(5500,7100,53),90,{FVector(5500,10800,49)});
        Route(false,1,FVector(5500,7800,53),90,{FVector(5500,11500,49)});
    }
    else if(TrafficProbe==TEXT("crossing"))
    {
        Route(false,0,FVector(5500,8700,53),90,{FVector(5500,11300,49)});
        Route(false,1,FVector(4200,10000,53),0,{FVector(6800,10000,49)});
    }
    else if(TrafficProbe==TEXT("meeting"))
    {
        Route(false,0,FVector(5280,7300,53),90,{FVector(5280,10500,49)});
        Route(false,1,FVector(5720,10500,53),-90,{FVector(5720,7300,49)});
    }
    else if(TrafficProbe==TEXT("reverse"))
        Route(false,0,FVector(-1100,200,95),90,{FVector(-1100,-750,49),FVector(600,-750,49)});
    else if(TrafficProbe==TEXT("flight"))
    {
        Route(true,0,FVector(4000,5500,2200),0,{FVector(7000,5500,2200)});
        Route(true,1,FVector(7000,5500,2650),180,{FVector(4000,5500,2650)});
        // A third vehicle creates a genuine same-altitude crossing, while the
        // opposite-direction pair also verifies vertical separation.
        Route(true,2,FVector(5500,4000,2200),90,{FVector(5500,7000,2200)});
    }
    else if(TrafficProbe==TEXT("landing"))
    {
        auto* A=Find(true,0);const FVector Pad=A->Dock;
        Route(true,0,Pad+FVector(0,0,2200),0,{Pad});
    }
    else if(TrafficProbe==TEXT("obstacle_replace"))
    {
        auto* A=Find(false,0);A->ResetTestPose(FVector(5500,7100,53),FRotator(0,90,0));
        A->TargetIndex=0;A->State=TEXT("inbound");A->bCarrying=true;A->Body->SetMassOverrideInKg(NAME_None,320);
        auto& T=Targets[0];T.bAssigned=T.bDiscovered=true;
        T.Visual->AttachToActor(A,FAttachmentTransformRules::KeepWorldTransform);
        T.Visual->SetActorRelativeLocation(FVector(0,0,15));T.Visual->SetActorRelativeRotation(FRotator::ZeroRotator);
        DistrictMesh(TEXT("Barrier"),FVector(5500,8300,4));
        A->AcceptRoute(TEXT("blocked_route"),{FVector(5500,10400,49)});
    }
    else {UE_LOG(LogTemp,Error,TEXT("MR unknown traffic fixture"));return;}
    AppendEvent(TEXT("traffic_probe_initialized"));
}
void AMRWorld::TickTrafficProbe()
{
    if(TrafficProbe!=TEXT("obstacle_replace")||bProbeRouteReplaced||GetWorld()->GetTimeSeconds()<40)return;
    bProbeRouteReplaced=true;
    const TArray<FVector> Replacement={FVector(55,76,.49),FVector(57.7,76,.49),FVector(57.7,90,.49),FVector(55,104,.49)};
    if(!SubmitRouteMeters(TEXT("ground_0"),TEXT("replacement_route"),Replacement))
    {UE_LOG(LogTemp,Error,TEXT("MR probe replacement was rejected"));return;}
    // These are real adapter calls. Neither a stale command replay nor a
    // conflicting body may replace the newly accepted route or move the load.
    AMRAgent* A=nullptr;for(AMRAgent* Candidate:Agents)if(Candidate->AgentKey()==TEXT("ground_0"))A=Candidate;
    const FVector Before=A->GetActorLocation();
    const bool Replay=SubmitRouteMeters(TEXT("ground_0"),TEXT("blocked_route"),{FVector(55,104,.49)});
    const bool Conflict=SubmitRouteMeters(TEXT("ground_0"),TEXT("replacement_route"),{FVector(1,1,.49)});
    if(!Replay||Conflict||A->CommandId!=TEXT("replacement_route")||!A->GetActorLocation().Equals(Before,.001)||!A->bCarrying)
    {UE_LOG(LogTemp,Error,TEXT("MR probe route idempotency/cargo invariant failed"));}
    else AppendEvent(TEXT("traffic_probe_command_invariants_verified"));
    AppendEvent(TEXT("traffic_probe_route_replaced"));
}
