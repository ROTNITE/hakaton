#include "MRAgent.h"
#include "MRWorld.h"
#include "Components/BoxComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Dom/JsonObject.h"
#include "Misc/SecureHash.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#endif

namespace
{
// Each axis stops at the active waypoint. The vertical thrust controller can
// reach its height before XY reaches its point, so a single capped time is not
// sufficient. Split at every stop time and solve the exact closest approach on
// each resulting linear interval, including when just one vehicle has stopped.
double FiniteClosestSquared(FVector P,FVector Velocity,FVector End,FVector Q,FVector OtherVelocity,FVector OtherEnd,double Horizon,double VerticalClearance=0.)
{
    TArray<double,TInlineAllocator<8>> Times;Times.Add(0);Times.Add(Horizon);
    auto AddStops=[&](FVector Start,FVector Speed,FVector Goal)
    {
        for(int32 Axis=0;Axis<3;Axis++)if(FMath::Abs(Speed[Axis])>1.e-6)
        {
            const double T=(Goal[Axis]-Start[Axis])/Speed[Axis];
            if(T>0&&T<Horizon)Times.AddUnique(T);
        }
    };
    auto At=[](FVector Start,FVector Speed,FVector Goal,double Time)
    {
        FVector Result=Start;
        for(int32 Axis=0;Axis<3;Axis++)
        {
            const double Delta=Goal[Axis]-Start[Axis];
            if(FMath::Abs(Delta)>1.e-6)
                Result[Axis]+=Delta*FMath::Clamp(Speed[Axis]*Time/Delta,0.,1.);
        }
        return Result;
    };
    AddStops(P,Velocity,End);AddStops(Q,OtherVelocity,OtherEnd);Times.Sort();
    double Closest=VerticalClearance>0?TNumericLimits<double>::Max():FVector::DistSquared(P,Q);
    for(int32 I=1;I<Times.Num();I++)
    {
        FVector Start=At(P,Velocity,End,Times[I-1])-At(Q,OtherVelocity,OtherEnd,Times[I-1]);
        const FVector Finish=At(P,Velocity,End,Times[I])-At(Q,OtherVelocity,OtherEnd,Times[I]);
        FVector Delta=Finish-Start;
        double First=0,Last=1;
        if(VerticalClearance>0)
        {
            // Rotors have a wide horizontal envelope and a shallow vertical
            // envelope. Solve XY clearance only over intervals where their
            // vertical envelopes overlap. A sphere incorrectly deadlocked
            // neighbouring launches already separated by several metres in Z.
            if(FMath::Abs(Delta.Z)<1.e-9)
            {if(FMath::Abs(Start.Z)>VerticalClearance)continue;}
            else
            {
                const double A=(-VerticalClearance-Start.Z)/Delta.Z,B=(VerticalClearance-Start.Z)/Delta.Z;
                First=FMath::Max(0.,FMath::Min(A,B));Last=FMath::Min(1.,FMath::Max(A,B));
                if(First>Last)continue;
            }
            Start.Z=Delta.Z=0;
        }
        const double T=FMath::Clamp(-FVector::DotProduct(Start,Delta)/FMath::Max(1.e-12,Delta.SizeSquared()),First,Last);
        Closest=FMath::Min(Closest,(Start+Delta*T).SizeSquared());
    }
    return Closest;
}
bool CanLeaveClearanceBuffer(FVector Offset,FVector ActualRelative,double PredictedClosestSquared,double HardSeparation,double SoftSeparation)
{
    const double CurrentSquared=Offset.SizeSquared();
    // The extra clearance is a braking margin, not an impassable wall around
    // parked neighbouring docks. Permit only a trajectory that does not reduce
    // their existing distance, with physical envelopes already separate and
    // actual velocity stationary, tangent, or receding.
    return CurrentSquared<SoftSeparation*SoftSeparation&&CurrentSquared>=HardSeparation*HardSeparation&&
        PredictedClosestSquared>=CurrentSquared-.01&&FVector::DotProduct(Offset,ActualRelative)<=1.;
}

bool CanFinishDockApproach(FVector P,FVector Actual,FVector Plan,FVector End,FVector Q,FVector OtherActual,
    FVector OtherPlan,double ClosestSquared,double HardSeparation,double SoftSeparation)
{
    // The braking margin may contain the endpoint of a slow docking leg, but
    // never an overlapping physical envelope. At <=0.8m/s actual speed, the
    // 0.2m extra gap exceeds a tick of reaction plus bounded braking distance.
    // A moving/intending-to-move neighbour always retains the full margin.
    const double EndGap=FVector::DistSquared2D(End,Q),Protected=FMath::Square(HardSeparation+20.);
    return Actual.Size()<=80.&&Plan.Size()<=70.1&&OtherActual.Size()<=5.&&OtherPlan.Size()<5.&&
        FVector::Dist2D(P,End)<=500.&&EndGap>=Protected&&EndGap<SoftSeparation*SoftSeparation&&ClosestSquared>=Protected;
}

double FiniteGroundLookAhead(double RequestedDistance,double WaypointDistance,double ActualSpeed)
{
    // Integrate the bounded proportional brake: dv/dt=-min(4v,300cm/s2).
    // Keep two fixed ticks of reaction. A slow final waypoint must not sweep
    // another 0.8m beyond its destination into the dock's rear board; a fast
    // vehicle must still sense its entire real stopping distance past a goal.
    constexpr double Gain=4.,Deceleration=300.,Threshold=Deceleration/Gain;
    const double Braking=ActualSpeed<=Threshold?ActualSpeed/Gain:
        (ActualSpeed*ActualSpeed-Threshold*Threshold)/(2*Deceleration)+Threshold/Gain;
    return FMath::Min(RequestedDistance,FMath::Max(WaypointDistance,Braking+ActualSpeed/30.));
}
}

bool AMRAgent::AcceptRoute(const FString& Id,const TArray<FVector>& Points,bool PreciseStop)
{
    if(Id.IsEmpty()||Points.IsEmpty()||Points.Num()>4096||!CanMove())return false;
    for(const auto& P:Points)
    {
        if(P.ContainsNaN()||(MediumLimits.IsValid?!MediumPointAllowed(P):P.Z<0||P.Z>15000))return false;
        if(Mission&&Mission->bCityLayout)
        {
            const auto Bounds=Mission->CityLayout->GetObjectField(TEXT("bounds"));
            const auto& Low=Bounds->GetArrayField(TEXT("min"));const auto& High=Bounds->GetArrayField(TEXT("max"));
            if(P.X<Low[0]->AsNumber()*100||P.X>High[0]->AsNumber()*100||
               P.Y<Low[1]->AsNumber()*100||P.Y>High[1]->AsNumber()*100||P.Z>High[2]->AsNumber()*100)return false;
        }
        else if(FMath::Abs(P.X)>70000||FMath::Abs(P.Y)>70000)return false;
    }
    FSHA1 Hash;const uint8 Type=PreciseStop?2:1;Hash.Update(&Type,1);
    for(const FVector& P:Points)for(int32 Axis=0;Axis<3;Axis++)
    {const double Number=P[Axis];Hash.Update(reinterpret_cast<const uint8*>(&Number),sizeof(Number));}
    Hash.Final();uint8 Bytes[20];Hash.GetHash(Bytes);const FString Signature=BytesToHex(Bytes,20);
    // Replays of an older command must not replace the newer active command.
    if(const auto* Prior=AcceptedCommands.Find(Id))return *Prior==Signature;
    if(Mission&&Mission->bCoreControlled&&(!IsOperational()||IsCharging()||State==TEXT("loading")||State==TEXT("unloading")))return false;
    AcceptedCommands.Add(Id,Signature);
    CommandId=Id;bExternalHold=false;SetWaypoints(Points);
    bPreciseFinalStop=PreciseStop;
    if(!bAerial&&TargetIndex<0)State=TEXT("external_route");
    StopReason.Empty();return true;
}
bool AMRAgent::Hold(const FString& Id)
{
    if(Id.IsEmpty())return false;
    if(const auto* Prior=AcceptedCommands.Find(Id))return *Prior==TEXT("hold");
    if(IsCharging())EndCharge();
    AcceptedCommands.Add(Id,TEXT("hold"));
    CommandId=Id;bExternalHold=true;IntendedVelocity=FVector::ZeroVector;
    if(bAerial)FlightAltitude=GetActorLocation().Z;
    return true;
}
bool AMRAgent::IsHoldingStable() const
{
    return bExternalHold&&Body->GetPhysicsLinearVelocity().Size()<10&&
        (!bAerial||Energy<=0||FMath::Abs(FlightAltitude-GetActorLocation().Z)<15)&&
        State!=TEXT("loading")&&State!=TEXT("unloading");
}
void AMRAgent::OnAgentHit(UPrimitiveComponent*,AActor* Other,UPrimitiveComponent*,FVector Impulse,const FHitResult&)
{
    if(Cast<AMRAgent>(Other)&&((Mission&&Mission->bRescueQuarter)||Impulse.Size()>1))
    {
        AgentContacts++;
        if(Mission)Mission->AppendEvent(TEXT("agent_vehicle_contact"),AgentId);
    }
}
FVector AMRAgent::PlannedVelocity() const
{
    if(bExternalHold||!IsOperational()||State==TEXT("loading")||State==TEXT("unloading")||
        State==TEXT("landed")||GetWorld()->GetTimeSeconds()<DepartAt)return FVector::ZeroVector;
    FVector Desired=FVector::ZeroVector;
    if(Path.IsValidIndex(PathIndex))
    {
        FVector Delta=Path[PathIndex]-GetActorLocation();if(!bAerial)Delta.Z=0;
        Desired=Delta.GetSafeNormal()*FMath::Min(double(MaxSpeed*SpeedFactor),Delta.Size()*1.2);
    }
    if(bAerial)
    {
        // A neighbour must see the route intention, not the transient thrust
        // altitude frozen by its previous safety stop.
        const double Altitude=Path.IsValidIndex(PathIndex)?Path[PathIndex].Z:FlightAltitude;
        Desired.Z=FMath::Clamp((Altitude-GetActorLocation().Z)*1.2,-250.,500.);
    }
    return Desired;
}
FVector AMRAgent::SafeVelocity(const FVector& Requested,float Dt)
{
    const FString PreviousReason=StopReason;StopReason.Empty();StopObstacle.Empty();SensedBlocker=FBox(ForceInit);
    FVector Desired=Requested;
    const FVector P=GetActorLocation(),V=Body->GetPhysicsLinearVelocity();
    const float Now=GetWorld()->GetTimeSeconds();
    // The thrust controller owns Z, but its climb/descent must go through the
    // same swept-volume check as lateral movement, including the final landing.
    FVector Motion=Requested;
    if(bAerial&&State!=TEXT("landed"))Motion.Z=FMath::Clamp((FlightAltitude-P.Z)*1.2,-250.,500.);
    if(bExternalHold){StopReason=FailureReason.IsEmpty()?TEXT("external_hold"):FailureReason;Desired=FVector::ZeroVector;}
    const float Speed=FMath::Max(float(V.Size()),float(Motion.Size()));
    float LookAhead=FMath::Clamp(Speed*.6f+Speed*Speed/(bAerial?1600.f:700.f)+60.f,80.f,bAerial?1800.f:650.f);
    if(!bAerial&&!bExternalHold&&Path.IsValidIndex(PathIndex))
        LookAhead=FiniteGroundLookAhead(LookAhead,FVector::Dist2D(P,Path[PathIndex]),V.Size2D());
    FVector Direction=Motion.GetSafeNormal();
    if(StopReason.IsEmpty()&&!Direction.IsNearlyZero())
    {
        if(Mission->RestrictionOnRoute(P,P+Direction*LookAhead,Kind(),SafetyRadius(),bAerial?40:110,SensedBlocker))
        {
            StopReason=TEXT("hazard_on_route");StopObstacle=TEXT("restricted_volume");Desired=FVector::ZeroVector;
        }
        if(!bAerial&&StopReason.IsEmpty())for(float Fraction:{0.f,.35f,.7f,1.f})
            if(Mission->IsUnsafeGround(P+Direction*LookAhead*Fraction))
            {
                StopReason=TEXT("hazard_on_route");Desired=FVector::ZeroVector;
                const FVector Sensed=P+Direction*LookAhead*Fraction;
                SensedBlocker=FBox(Sensed-FVector(100,100,100),Sensed+FVector(100,100,100));break;
            }
        FCollisionQueryParams Params(SCENE_QUERY_STAT(MRLocalSafety),false,this);
        for(AMRAgent* Other:Mission->Agents)if(Other)Params.AddIgnoredActor(Other);
        TArray<FHitResult> Hits;
        const FVector Half=bAerial?FVector(115,115,22):FVector(125,70,45);
        const FVector SweepOrigin=P+(bAerial?FVector::ZeroVector:FVector(0,0,15));
        GetWorld()->SweepMultiByChannel(Hits,SweepOrigin,SweepOrigin+Direction*LookAhead,GetActorQuat(),ECC_Visibility,
            FCollisionShape::MakeBox(Half),Params);
        for(const auto& Hit:Hits)
            if(Hit.bBlockingHit&&(bAerial||Hit.ImpactNormal.Z<.45f))
            {
                // The conservative rotor sweep extends below the physical
                // hull. Its initial 2 cm overlap with the launch pad is a
                // support contact, not a wall blocking upward departure.
                const bool OwnPadSupport=bAerial&&Hit.ImpactNormal.Z>.8&&FVector::Dist2D(Hit.ImpactPoint,Dock)<170&&
                    Hit.ImpactPoint.Z<=Dock.Z+5;
                const bool DepartingPad=Motion.Z>0&&P.Z<=Dock.Z+50&&FVector::Dist2D(P,Dock)<170;
                if(OwnPadSupport&&(FlightAltitude<=Dock.Z+100||DepartingPad))continue;
                if(StopObstacle==TEXT("restricted_volume"))break;
                StopReason=TEXT("obstacle_on_route");Desired=FVector::ZeroVector;
                StopObstacle=GetNameSafe(Hit.GetComponent());
                if(auto* Primitive=Hit.GetComponent())SensedBlocker=Primitive->Bounds.GetBox();
                if(auto* Instanced=Cast<UInstancedStaticMeshComponent>(Hit.GetComponent()))
                {
                    FTransform Instance;
                    if(Instanced->GetStaticMesh()&&Instanced->GetInstanceTransform(Hit.Item,Instance,true))
                        SensedBlocker=Instanced->GetStaticMesh()->GetBoundingBox().TransformBy(Instance);
                }
                if(auto* Mesh=Cast<UStaticMeshComponent>(Hit.GetComponent()))
                    StopObstacle+=TEXT(":")+GetNameSafe(Mesh->GetStaticMesh())+TEXT(":")+GetNameSafe(Mesh->GetMaterial(0))+FString::Printf(TEXT(":instance_%d"),Hit.Item);
                break;
            }
    }
    // Predict the unmodified route intentions. Comparing to a yielding actor's
    // already-braked velocity made both actors exchange priority every frame.
    // A fixed route-origin order reserves a crossing until its trajectories no
    // longer conflict. Following traffic always leaves priority to its leader.
    if(StopReason.IsEmpty()&&Motion.Size()>5)
        for(AMRAgent* Other:Mission->Agents)
        {
            if(!Other||Other==this||!Other->Category.IsEmpty())continue;
            const FVector Q=Other->GetActorLocation();
            const bool AirPair=bAerial||Other->bAerial;
            FVector Offset=Q-P;if(!AirPair)Offset.Z=0;
            if(Offset.Size()>4500)continue;
            FVector OtherPlan=Other->PlannedVelocity(),OwnPlan=Motion;
            if(!AirPair){OtherPlan.Z=0;OwnPlan.Z=0;}
            FVector OwnEnd=ActiveWaypoint(),OtherEnd=Other->ActiveWaypoint();
            OwnEnd.Z=bAerial?FlightAltitude:P.Z;
            OtherEnd.Z=Other->bAerial?(!Other->bExternalHold&&Other->Path.IsValidIndex(Other->PathIndex)?Other->Path[Other->PathIndex].Z:Other->FlightAltitude):Q.Z;
            if(!AirPair){OwnEnd.Z=0;OtherEnd.Z=0;}
            FVector PredictionP=P,PredictionQ=Q;
            if(!AirPair){PredictionP.Z=0;PredictionQ.Z=0;}
            const float Separation=SafetyRadius()+Other->SafetyRadius()+(AirPair?100.f:65.f);
            const double VerticalClearance=AirPair?((bAerial?40.:110.)+(Other->bAerial?40.:110.)+100.):0.;
            FVector OtherActual=Other->Body->GetPhysicsLinearVelocity();if(!AirPair)OtherActual.Z=0;
            FVector OwnActual=V;if(!AirPair)OwnActual.Z=0;
            const double PredictedClosest=FiniteClosestSquared(PredictionP,OwnPlan,OwnEnd,PredictionQ,OtherPlan,OtherEnd,3,VerticalClearance);
            FVector BufferOffset=Offset,BufferRelative=OwnActual-OtherActual;
            if(AirPair){BufferOffset.Z=0;BufferRelative.Z=0;}
            if((!AirPair||FMath::Abs(Offset.Z)<=VerticalClearance)&&
                CanLeaveClearanceBuffer(BufferOffset,BufferRelative,PredictedClosest,SafetyRadius()+Other->SafetyRadius(),Separation))continue;
            if(!AirPair&&IsDockEntryLeg()&&CanFinishDockApproach(P,OwnActual,OwnPlan,OwnEnd,Q,OtherActual,OtherPlan,
                PredictedClosest,SafetyRadius()+Other->SafetyRadius(),Separation))continue;
            // Priority cannot make an occupied lane traversable. If the loser
            // has stopped directly on our swept path, brake before its hull.
            const bool Occupied=OtherActual.Size()<30&&
                FiniteClosestSquared(PredictionP,OwnPlan,OwnEnd,PredictionQ,FVector::ZeroVector,PredictionQ,3,VerticalClearance)<Separation*Separation&&
                Offset.Size()<Separation+Speed*.65f+Speed*Speed/700.f;
            if(Occupied)
            {StopReason=TEXT("yield_to_vehicle");StopObstacle=Other->AgentKey();Desired=FVector::ZeroVector;break;}
            if(PredictedClosest>=Separation*Separation)continue;
            const bool Ahead=FVector::DotProduct(Offset,OwnPlan.GetSafeNormal())>0;
            const bool Following=FVector::DotProduct(OwnPlan.GetSafeNormal(),OtherPlan.GetSafeNormal())>.75f;
            const bool OtherStatic=OtherPlan.Size()<5;
            const FVector Priority=Other->RoutePriorityOrigin-RoutePriorityOrigin;
            const bool OtherFirst=Priority.X<-.1||(FMath::Abs(Priority.X)<=.1&&
                (Priority.Y<-.1||(FMath::Abs(Priority.Y)<=.1&&Other->GetFName().LexicalLess(GetFName()))));
            if((Following&&Ahead)||(OtherStatic&&Ahead)||(!Following&&!OtherStatic&&OtherFirst))
            {
                StopReason=TEXT("yield_to_vehicle");StopObstacle=Other->AgentKey();Desired=FVector::ZeroVector;break;
            }
        }
    if(bAerial&&!StopReason.IsEmpty()&&StopReason!=TEXT("external_hold"))FlightAltitude=P.Z;
    if(StopReason.StartsWith(TEXT("yield")))
    {if(WaitingSince<0)WaitingSince=Now;}
    else WaitingSince=-1;
    if(PreviousReason!=StopReason&&Mission)
        Mission->AppendEvent(StopReason.IsEmpty()?TEXT("agent_motion_resumed"):
            StopReason.StartsWith(TEXT("yield"))?TEXT("agent_yielding"):TEXT("agent_safe_stop"),AgentId);
    return Desired;
}

#if WITH_DEV_AUTOMATION_TESTS
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRFiniteRoutePrediction,"MetaRescue.Safety.FiniteRoutePrediction",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRFiniteRoutePrediction::RunTest(const FString&)
{
    const FVector Zero=FVector::ZeroVector;
    auto Distance=[](FVector P,FVector V,FVector End,FVector Q,FVector W,FVector OtherEnd)
    {return FMath::Sqrt(FiniteClosestSquared(P,V,End,Q,W,OtherEnd,10));};
    TestTrue(TEXT("follower does not extrapolate beyond destination into a parked leader"),
        FMath::IsNearlyEqual(Distance(Zero,FVector(300,0,0),FVector(1000,0,0),FVector(1400,0,0),Zero,FVector(1400,0,0)),400.,.001));
    TestTrue(TEXT("one arrival stops while the other continues"),
        FMath::IsNearlyEqual(Distance(Zero,FVector(300,0,0),FVector(1000,0,0),FVector(1400,0,0),FVector(-300,0,0),FVector(1300,0,0)),300.,.001));
    TestTrue(TEXT("crossing inside both finite legs still conflicts"),
        Distance(FVector(-1000,0,0),FVector(300,0,0),FVector(1000,0,0),FVector(0,-1000,0),FVector(0,300,0),FVector(0,1000,0))<.001);
    TestTrue(TEXT("opposite occupied lane still conflicts"),
        Distance(Zero,FVector(300,0,0),FVector(1000,0,0),FVector(1400,0,0),FVector(-300,0,0),FVector(500,0,0))<.001);
    TestTrue(TEXT("vertical height may finish before horizontal motion"),
        FMath::IsNearlyEqual(Distance(Zero,FVector(300,0,200),FVector(600,0,100),FVector(1000,0,100),Zero,FVector(1000,0,100)),400.,.001));
    const double ExitClosest=FiniteClosestSquared(Zero,FVector(0,-100,0),FVector(0,-950,0),FVector(330,0,0),Zero,FVector(330,0,0),3);
    TestTrue(TEXT("a tangent departure can leave a neighbouring dock's soft margin"),
        CanLeaveClearanceBuffer(FVector(330,0,0),FVector(0,-100,0),ExitClosest,290,355));
    TestFalse(TEXT("a vehicle moving toward the neighbour cannot escape the margin"),
        CanLeaveClearanceBuffer(FVector(330,0,0),FVector(20,0,0),ExitClosest,290,355));
    TestFalse(TEXT("a future approaching trajectory cannot escape the margin"),
        CanLeaveClearanceBuffer(FVector(330,0,0),Zero,300.*300.,290,355));
    TestFalse(TEXT("overlapping physical envelopes are never exempted"),
        CanLeaveClearanceBuffer(FVector(270,0,0),Zero,270.*270.,290,355));
    TestTrue(TEXT("vertically separated rotors can cross the same XY point"),
        FiniteClosestSquared(FVector(-1000,0,2000),FVector(1000,0,0),FVector(1000,0,2000),
            FVector(0,0,2230),Zero,FVector(0,0,2230),3,180)>430.*430.);
    TestTrue(TEXT("same-height rotor trajectories still conflict"),
        FiniteClosestSquared(FVector(-1000,0,2000),FVector(1000,0,0),FVector(1000,0,2000),
            FVector(0,-1000,2000),FVector(0,1000,0),FVector(0,1000,2000),3,180)<.001);
    TestTrue(TEXT("descent into an occupied altitude is not exempted by its initial height"),
        FiniteClosestSquared(FVector(0,0,2500),FVector(0,0,-250),FVector(0,0,2000),
            FVector(0,0,2000),Zero,FVector(0,0,2000),3,180)<.001);
    TestTrue(TEXT("a later height overlap is evaluated at its actual XY position"),
        FiniteClosestSquared(FVector(0,0,2500),FVector(1000,0,-250),FVector(3000,0,2000),
            FVector(0,0,2000),Zero,FVector(0,0,2000),3,180)>430.*430.);
    auto DockArrival=[&](FVector Actual,FVector Plan,FVector End,FVector OtherActual,FVector OtherPlan,double Closest)
    {return CanFinishDockApproach(FVector(350,-400,0),Actual,Plan,End,Zero,OtherActual,OtherPlan,Closest,290,355);};
    TestTrue(TEXT("a slow finite dock arrival may finish inside a parked neighbour's braking margin"),
        DockArrival(FVector(0,60,0),FVector(0,70,0),FVector(350,0,0),Zero,Zero,350.*350.));
    TestFalse(TEXT("docking exception never permits excessive actual speed"),
        DockArrival(FVector(0,120,0),FVector(0,70,0),FVector(350,0,0),Zero,Zero,350.*350.));
    TestFalse(TEXT("docking exception never permits an overlapping destination"),
        DockArrival(Zero,FVector(0,70,0),FVector(280,0,0),Zero,Zero,280.*280.));
    TestFalse(TEXT("docking exception never reserves another moving vehicle's space"),
        DockArrival(Zero,FVector(0,70,0),FVector(350,0,0),FVector(0,10,0),Zero,350.*350.));
    TestFalse(TEXT("a temporarily braked neighbour with a route is still moving traffic"),
        DockArrival(Zero,FVector(0,70,0),FVector(350,0,0),Zero,FVector(0,30,0),350.*350.));
    TestTrue(TEXT("a slow docking sweep stops at its finite endpoint"),
        FMath::IsNearlyEqual(FiniteGroundLookAhead(80,20,35),20.,.001));
    TestTrue(TEXT("a fast vehicle still senses braking distance beyond a close waypoint"),
        FiniteGroundLookAhead(400,20,300)>160.);
    TestTrue(TEXT("a distant route keeps its full requested safety horizon"),
        FMath::IsNearlyEqual(FiniteGroundLookAhead(400,1000,300),400.,.001));
    return true;
}
#endif
