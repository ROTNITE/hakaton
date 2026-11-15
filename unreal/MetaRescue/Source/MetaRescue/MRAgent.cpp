#include "MRAgent.h"
#include "MRWorld.h"
#include "Components/BoxComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Materials/MaterialInterface.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Dom/JsonObject.h"
#include "NiagaraComponent.h"
#include "NiagaraFunctionLibrary.h"
#include "NiagaraSystem.h"

namespace
{
void TrafficLane(TArray<FVector>& Points,const FVector& Start,int32 First,int32 End)
{
    const TArray<FVector> Centerline=Points;
    for(int32 I=First;I<End;I++)
    {
        FVector In=(Centerline[I]-(I?Centerline[I-1]:Start)).GetSafeNormal2D();
        FVector Out=(Centerline[I+1]-Centerline[I]).GetSafeNormal2D();
        if(In.IsNearlyZero())In=Out;
        if(Out.IsNearlyZero())Out=In;
        const FVector Right=FVector::CrossProduct(FVector::UpVector,In+Out);
        Points[I]+=Right*(220.f/FMath::Max(.35f,1.f+FVector::DotProduct(In,Out)));
    }
}
void RemoveRepeatedPoints(TArray<FVector>& Points)
{
    for(int32 I=Points.Num()-1;I>0;I--)
        if(FVector::Dist2D(Points[I],Points[I-1])<1)Points.RemoveAt(I);
}
}

AMRAgent::AMRAgent()
{
    PrimaryActorTick.bCanEverTick = true;
    PrimaryActorTick.TickGroup = TG_PrePhysics;
    Body = CreateDefaultSubobject<UBoxComponent>(TEXT("PhysicsBody"));
    SetRootComponent(Body);
    Body->SetBoxExtent(FVector(95,66,43));
    Body->SetCollisionProfileName(TEXT("PhysicsActor"));
    Body->SetCollisionResponseToChannel(ECC_Camera,ECR_Ignore);
    Body->SetLinearDamping(.25f);
    Body->SetAngularDamping(4.f);
    Body->SetNotifyRigidBodyCollision(true);
    Body->OnComponentHit.AddDynamic(this,&AMRAgent::OnAgentHit);
}

UStaticMeshComponent* AMRAgent::Part(const FString& Mesh, FVector Position, FVector Size,
    const FString& Material, FRotator Rotation)
{
    auto* C = NewObject<UStaticMeshComponent>(this);
    AddInstanceComponent(C); C->SetupAttachment(Body);
    C->SetStaticMesh(LoadObject<UStaticMesh>(nullptr, *(TEXT("/Engine/BasicShapes/")+Mesh+TEXT(".")+Mesh)));
    C->SetMaterial(0, LoadObject<UMaterialInterface>(nullptr, *(TEXT("/Game/Materials/")+Material+TEXT(".")+Material)));
    C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    C->SetRelativeLocation(Position); C->SetRelativeRotation(Rotation);
    C->SetRelativeScale3D(Size/100.f); C->RegisterComponent();
    Parts.Add(C); return C;
}

void AMRAgent::Initialize(AMRWorld* InWorld, int32 InId, bool Aerial, const TArray<FVector>& InitialPath)
{
    Mission=InWorld; AgentId=InId; bAerial=Aerial; Dock=GetActorLocation(); Previous=Dock;
    Body->SetBoxExtent(Aerial?FVector(38,38,18):FVector(95,66,43));
    Body->SetMassOverrideInKg(NAME_None,Aerial?12.f:240.f);
    Body->SetEnableGravity(!Aerial);
    if(Mission->bRescueQuarter)
    {
        InitializeDistrictVisual();Body->SetSimulatePhysics(true);SetWaypoints(InitialPath);return;
    }
    if(Aerial)
    {
        Energy=120;MaxSpeed=1800;
        Part("Sphere",FVector::ZeroVector,FVector(85,62,28),"MI_Blue");
        Part("Cube",FVector(12,0,-24),FVector(25,25,25),"MI_Dark");
        for(int32 X:{-1,1}) for(int32 Y:{-1,1})
        {
            Part("Cube",FVector(X*33,Y*33,0),FVector(100,8,7),"MI_Metal",FRotator(0,X*Y*45,0));
            Part("Cylinder",FVector(X*65,Y*65,4),FVector(21,21,15),"MI_Dark");
            Part("Cylinder",FVector(X*65,Y*65,13),FVector(67,67,1.5),"MI_Rotor");
            Part("Sphere",FVector(X*65,Y*65,-4),FVector(10,10,7),"MI_CyanGlow");
        }
        Part("Sphere",FVector(35,0,-26),FVector(16,16,16),"MI_Glass");
    }
    else
    {
        Energy=Mission->Scenario->GetNumberField(TEXT("ground_battery_Wh"));
        Part("Cube",FVector(0,0,-6),FVector(180,128,62),"MI_Dark");
        Part("Cube",FVector(0,0,22),FVector(174,106,42),"MI_Orange");
        Part("Cube",FVector(-5,0,50),FVector(125,82,12),"MI_White");
        Part("Cube",FVector(-5,0,59),FVector(105,61,9),"MI_Teal");
        for(int32 Side:{-1,1}) for(int32 Wheel=0;Wheel<5;Wheel++)
        {
            Part("Cylinder",FVector(-69+Wheel*34,Side*65,-10),FVector(49,49,15),"MI_Rubber",FRotator(0,0,90));
            Part("Cylinder",FVector(-69+Wheel*34,Side*74,-10),FVector(26,26,3),"MI_Metal",FRotator(0,0,90));
        }
        Part("Cylinder",FVector(-63,0,83),FVector(8,8,63),"MI_Metal");
        Part("Cube",FVector(-63,0,120),FVector(33,33,21),"MI_Dark");
        Part("Sphere",FVector(-49,0,120),FVector(7,21,9),"MI_CyanGlow");
        for(int32 Y:{-1,1})
        {
            Part("Cube",FVector(89,Y*34,25),FVector(4,29,10),"MI_WhiteGlow");
            Part("Cube",FVector(0,Y*46,65),FVector(139,5,5),"MI_Metal");
        }
    }
    Body->SetSimulatePhysics(true);
    BatteryCapacityWh=Energy;
    SetWaypoints(InitialPath);
}

void AMRAgent::SetWaypoints(const TArray<FVector>& Waypoints)
{
    Path=Waypoints;PathIndex=0;
    bPreciseFinalStop=false;
    RoutePriorityOrigin=GetActorLocation();
    bReverseInitialLeg=!bAerial&&!Path.IsEmpty()&&FVector::Dist2D(GetActorLocation(),Dock)<450&&
        FVector::DotProduct(GetActorForwardVector(),(Path[0]-GetActorLocation()).GetSafeNormal2D())<-.5;
    if(bAerial&&!Path.IsEmpty())FlightAltitude=Path.Last().Z;
    if(bAerial) State=Path.IsEmpty()?"idle":"surveying";
}

bool AMRAgent::IsDockEntryLeg() const
{
    return !bAerial&&Path.IsValidIndex(PathIndex)&&PathIndex==Path.Num()-1&&
        (State==TEXT("inbound")||(Mission&&Mission->bCoreControlled&&FVector::Dist2D(Path.Last(),Dock)<30));
}

void AMRAgent::StartRescue(int32 Index)
{
    TargetIndex=Index;State="outbound";
    if(Mission->bRescueQuarter)DepartAt=GetWorld()->GetTimeSeconds()+AgentId*4.f;
    auto& T=Mission->Targets[Index];T.bAssigned=true;
    TArray<FVector> Points=T.Path;
    const float Offset=(AgentId-1.5f)*150.f;
    if(!Mission->bRescueQuarter)
        for(int32 I=0;I<Points.Num()-1;I++) Points[I]+=FVector(Offset,Offset,0);
    for(auto& P:Points) P.Z=48;
    if(Mission->bRescueQuarter&&Points.Num()>1)
        Points.Last()-=(Points.Last()-Points[Points.Num()-2]).GetSafeNormal2D()*300;
    if(Mission->bRescueQuarter)
    {
        Points.RemoveAt(0);
        // Separate marked departures merge at different places along the road;
        // four vehicles must not compete for one precise turning point.
        const float ExitY=-600-AgentId*320;
        Points.Insert(FVector(1000,ExitY,48),0);
        Points.Insert(FVector(Dock.X,ExitY,48),0);
        RemoveRepeatedPoints(Points);
        TrafficLane(Points,GetActorLocation(),1,Points.Num()-1);
    }
    SetWaypoints(Points);
    Mission->AppendEvent(TEXT("demo_rescue_assigned"),T.Id);
}

void AMRAgent::Arrived()
{
    if(!CommandId.IsEmpty())
    {
        const bool AtPad=bAerial&&FVector::Dist2D(GetActorLocation(),Dock)<150&&GetActorLocation().Z<Dock.Z+100;
        State=AtPad?TEXT("landing"):bAerial?TEXT("holding"):TEXT("idle");
        if(bAerial)FlightAltitude=AtPad?Dock.Z:GetActorLocation().Z;
        Mission->AppendEvent(TEXT("agent_route_completed"),AgentId);return;
    }
    if(bAerial)
    {
        if(Mission->bRescueQuarter){State="landing";FlightAltitude=Dock.Z;Mission->AppendEvent(TEXT("agent_landing_started"),AgentId);}
        else State="idle";
        return;
    }
    if(State=="outbound")
    {
        State="loading";ServiceRemaining=Mission->bRescueQuarter?8:5;ServiceElapsed=0;
        if(TargetIndex>=0)
        {
            const auto& Target=Mission->Targets[TargetIndex];
            ServiceHeading=(GetActorLocation()-Target.Position).Rotation().Yaw;
            if(Target.Visual){PickupStart=Target.Visual->GetActorLocation();PickupRotation=Target.Visual->GetActorQuat();}
        }
    }
    else if(State=="inbound"){State="unloading";ServiceRemaining=Mission->bRescueQuarter?6:3;ServiceElapsed=0;ServiceHeading=GetActorRotation().Yaw;}
}

void AMRAgent::AccountExecutedMovement()
{
    if(!Mission||!Body->IsSimulatingPhysics())return;
    const FVector Current=GetActorLocation();
    const float Travel=FVector::Dist(Current,Previous);Previous=Current;
    DistanceTravelled+=Travel;
    const float SurfaceCost=MediumLimits.IsValid?(Category==TEXT("underground")?1.2f:1.3f):
        Mission->bRescueQuarter&&!bAerial?Mission->QuerySurfaceMeters(Current/100.f).MovementCost:1.f;
    const double Wh=Travel/1000.f*(bAerial?.69f:bCarrying?1.18f:.82f)*SurfaceCost;
    Spend(Wh,MotionWh);
}

void AMRAgent::Tick(float Dt)
{
    Super::Tick(Dt);
    if(!Mission||!Body->IsSimulatingPhysics())return;
    AccountExecutedMovement();
    if(MediumLimits.IsValid){DriveCompetitionMedium(Dt);return;}
    const FVector Current=GetActorLocation();
    if(Mission->bRescueQuarter)AnimateMechanisms(Dt);
    if(State=="loading"||State=="unloading")
    {
        const bool Ready=!Mission->bRescueQuarter||(RampDeployment>.98f&&Body->GetPhysicsLinearVelocity().Size()<20);
        if(Ready){ServiceRemaining-=Dt;ServiceElapsed+=Dt;}
        if(Mission->bRescueQuarter&&Ready&&TargetIndex>=0)
        {
            auto& T=Mission->Targets[TargetIndex];
            if(T.Visual)
            {
                const float Alpha=FMath::SmoothStep(0.f,State=="loading"?8.f:6.f,ServiceElapsed);
                const FVector Bed=GetActorTransform().TransformPosition(FVector(0,0,15));
                if(State=="loading")
                {
                    T.Visual->SetActorLocation(FMath::Lerp(PickupStart,Bed,Alpha));
                    T.Visual->SetActorRotation(FQuat::Slerp(PickupRotation,GetActorQuat(),Alpha));
                }
                else T.Visual->SetActorRelativeLocation(FMath::Lerp(FVector(0,0,15),FVector(-285,0,-42),Alpha));
            }
        }
        if(ServiceRemaining<=0&&TargetIndex>=0)
        {
            auto& T=Mission->Targets[TargetIndex];
            if(State=="loading")
            {
                if(T.Visual){T.Visual->AttachToActor(this,FAttachmentTransformRules::KeepWorldTransform);T.Visual->SetActorRelativeLocation(FVector(0,0,Mission->bRescueQuarter?15:87));T.Visual->SetActorRelativeRotation(FRotator::ZeroRotator);}
                State="inbound";
                bCarrying=true;
                if(Mission->bRescueQuarter){Body->SetMassOverrideInKg(NAME_None,320.f);Body->SetCenterOfMass(FVector(0,0,16));}
                if(Mission->bCoreControlled)
                {State=TEXT("loaded");bExternalHold=true;Mission->AppendEvent(TEXT("person_loaded"),T.Id);}
                else
                {
                TArray<FVector> Return;
                for(int32 I=T.Path.Num()-2;I>=0;I--)
                {
                    FVector P=T.Path[I];P.Z=48;
                    if(!Mission->bRescueQuarter)P+=FVector((AgentId-1.5f)*150,(AgentId-1.5f)*150,0);
                    Return.Add(P);
                }
                if(Mission->bRescueQuarter)
                {
                    Return.RemoveAt(Return.Num()-1);
                    Return.Add(FVector(1000,-300,48));Return.Add(FVector(Dock.X,-300,48));
                }
                Return.Add(Dock);
                if(Mission->bRescueQuarter)
                {
                    RemoveRepeatedPoints(Return);
                    TrafficLane(Return,GetActorLocation(),0,Return.Num()-2);
                }
                SetWaypoints(Return);Mission->AppendEvent(TEXT("person_loaded"),T.Id);
                }
            }
            else
            {
                T.bRescued=true;
                if(T.Visual)
                {if(Mission->bCoreControlled){T.Visual->DetachFromActor(FDetachmentTransformRules::KeepWorldTransform);T.Position=T.Visual->GetActorLocation();}T.Visual->SetActorHiddenInGame(true);}
                bCarrying=false;
                Mission->AppendEvent(TEXT("person_delivered"),T.Id);TargetIndex=-1;State="idle";
                if(Mission->bRescueQuarter){Body->SetMassOverrideInKg(NAME_None,240.f);Body->SetCenterOfMass(FVector::ZeroVector);}
            }
        }
    }
    FVector Desired=FVector::ZeroVector;
    if(!bExternalHold&&PathIndex<Path.Num()&&IsOperational()&&GetWorld()->GetTimeSeconds()>=DepartAt&&State!="loading"&&State!="unloading"&&(!Mission->bRescueQuarter||bAerial||RampDeployment<.02f))
    {
        FVector Delta=Path[PathIndex]-Current;
        if(bAerial&&Mission->bRescueQuarter)FlightAltitude=Path[PathIndex].Z;
        if(!bAerial)Delta.Z=0;
        // Dock rails leave little lateral clearance. Finish the approach point
        // before turning, and brake proportionally rather than cutting across it.
        const bool DockEntry=IsDockEntryLeg();
        const bool DockApproach=Mission->bRescueQuarter&&!bAerial&&(DockEntry||
            (Mission->bCoreControlled?FVector::Dist2D(Current,Dock)<1000&&FVector::Dist2D(Path[PathIndex],Dock)<1000:
                Current.Y<650&&Path[PathIndex].Y<650));
        // A carrier approaching a recovered stretcher needs a service pose
        // inside pickup range while stopping outside the failed body's margin.
        const bool PreciseStop=!bAerial&&bPreciseFinalStop&&PathIndex==Path.Num()-1;
        const bool SlowApproach=DockEntry||(PreciseStop&&Delta.Size2D()<250.);
        const float ArrivalRadius=bAerial?(Mission->bRescueQuarter?75:180):PreciseStop?10:DockApproach?20:95;
        if(Delta.Size()<ArrivalRadius)
        {
            PathIndex++;
            if(PathIndex==Path.Num())Arrived();
        }
        // A contact box has static friction. Do not let the proportional speed
        // taper below breakaway traction before entering the arrival radius.
        else
        {
            const double Speed=MaxSpeed*SpeedFactor;
            Desired=Delta.GetSafeNormal()*(bAerial?FMath::Min(Speed,Delta.Size()*2):
                FMath::Min(Speed,FMath::Clamp(Delta.Size()*1.2,(DockApproach||SlowApproach)?35.:75.,SlowApproach?70.:double(MaxSpeed))));
        }
    }
    // A temporary traffic stop freezes thrust at the current height. Restore
    // the landing target once per tick so descent resumes when space clears.
    if(bAerial&&Mission->bRescueQuarter&&State==TEXT("landing"))FlightAltitude=Dock.Z;
    IntendedVelocity=Desired;
    if(Mission->bRescueQuarter)Desired=SafeVelocity(Desired,Dt);
    FVector V=Body->GetPhysicsLinearVelocity();
    if(Mission->bRescueQuarter&&!bAerial)
    {
        const bool PermanentStop=StopReason==TEXT("obstacle_on_route")||StopReason==TEXT("hazard_on_route");
        if((Desired.Size2D()>100||PermanentStop)&&V.Size2D()<15)
        {
            ObstructionTime+=Dt;
            if(ObstructionTime>4&&!bRouteBlocked){bRouteBlocked=true;Mission->AppendEvent(TEXT("agent_route_blocked"),AgentId);}
        }
        else if(V.Size2D()>40||Desired.Size2D()<5)
        {
            if(bRouteBlocked)Mission->AppendEvent(TEXT("agent_route_resumed"),AgentId);
            bRouteBlocked=false;ObstructionTime=0;
        }
    }
    if(!bAerial&&Mission->bRescueQuarter){DriveDistrictGround(Desired);return;}
    FVector Accel=(Desired-V)*3;
    if(!bAerial)Accel.Z=0;
    Accel=Accel.GetClampedToMaxSize(bAerial?3800:2400);
    if(bAerial&&Mission->bRescueQuarter)
    {
        // A bounded thrust controller balances actual gravity, including during a hold.
        const float HeightError=FlightAltitude-Current.Z;
        const float VerticalTarget=FMath::Clamp(HeightError*1.2f,-250.f,500.f);
        Accel.Z=State=="landed"||IsCharging()||Energy<=0?0:FMath::Clamp(980.f+(VerticalTarget-V.Z)*4,0.f,2600.f);
        if(State=="landing"&&Current.Z<Dock.Z+12&&FMath::Abs(V.Z)<15)
        {State="landed";Mission->AppendEvent(TEXT("agent_landed"),AgentId);}
    }
    Body->AddForce(Accel,NAME_None,true);
    const FVector Angular=Body->GetPhysicsAngularVelocityInRadians();
    FVector Torque=FVector::CrossProduct(GetActorUpVector(),FVector::UpVector)*50-Angular*6;
    if(Desired.Size2D()>20)
        Torque.Z+=FMath::DegreesToRadians(FMath::FindDeltaAngleDegrees(GetActorRotation().Yaw,Desired.Rotation().Yaw))*8;
    Body->AddTorqueInRadians(Torque,NAME_None,true);
}

void AMRAgent::InitializeDistrictVisual()
{
    const FString Name=bAerial?TEXT("Drone"):TEXT("Rover");
    MRBuildAssembly(this,Body,Name,FVector(0,0,bAerial?-18:-44),FRotator::ZeroRotator,FVector::OneVector,false,true,Mechanisms);
    for(auto& Part:Mechanisms)
    {
        Parts.Add(Part.Mesh);
        if(Part.Role==TEXT("track"))Part.Mesh->CreateAndSetMaterialInstanceDynamic(0);
    }
    if(bAerial)
    {
        const int32 Count=Mechanisms.Num();
        for(int32 I=0;I<Count;I++)if(Mechanisms[I].Role==TEXT("rotor"))
        {
            FMRAssemblyPart Blur;Blur.Role=TEXT("rotor_blur");
            Blur.Mesh=Part("Plane",Mechanisms[I].Rest.GetLocation()+FVector(0,0,-15),FVector(60,60,100),"M_RotorBlur");
            Blur.Mesh->SetVisibility(false);Mechanisms.Add(Blur);
        }
    }
    // The collision hull represents the rigid chassis belly, not the empty volume below it.
    Body->SetBoxExtent(bAerial?FVector(110,110,18):FVector(110,54,17));
    Body->SetEnableGravity(true);
    if(bAerial){Energy=120;MaxSpeed=1000;FlightAltitude=Dock.Z;}
    else{Energy=Mission->Scenario->GetNumberField(TEXT("ground_battery_Wh"));MaxSpeed=300;}
}

void AMRAgent::AnimateMechanisms(float Dt)
{
    const float ForwardSpeed=FVector::DotProduct(Body->GetPhysicsLinearVelocity(),GetActorForwardVector());
    const float YawSpeed=Body->GetPhysicsAngularVelocityInRadians().Z;
    if(!bAerial)
    {
        const bool Wet=Mission->GroundSpeedFactor(GetActorLocation())<.8f&&FMath::Abs(ForwardSpeed)>60;
        if(Wet&&!SurfaceSpray)
            if(auto* System=LoadObject<UNiagaraSystem>(nullptr,TEXT("/Game/EffectsV3/NS_WheelSplash.NS_WheelSplash")))
                SurfaceSpray=UNiagaraFunctionLibrary::SpawnSystemAttached(System,Body,NAME_None,FVector(0,0,-40),FRotator::ZeroRotator,EAttachLocation::KeepRelativeOffset,false);
        if(SurfaceSpray){if(Wet&&!SurfaceSpray->IsActive())SurfaceSpray->Activate();else if(!Wet&&SurfaceSpray->IsActive())SurfaceSpray->Deactivate();}
    }
    const bool Service=(State==TEXT("loading")||State==TEXT("unloading"))&&
        FMath::Abs(FMath::FindDeltaAngleDegrees(GetActorRotation().Yaw,ServiceHeading))<6;
    RampDeployment=FMath::FInterpConstantTo(RampDeployment,Service?1.f:0.f,Dt,.55f);
    const float RPMTarget=!bAerial||State==TEXT("landed")||IsCharging()||Energy<=0?0:State==TEXT("landing")?2100:4800;
    RotorRPM=FMath::FInterpTo(RotorRPM,RPMTarget,Dt,2.2f);
    for(auto& Part:Mechanisms)
    {
        if(!Part.Mesh)continue;
        const float TreadSpeed=ForwardSpeed-YawSpeed*Part.Side*53;
        if(Part.Role==TEXT("rotor"))
        {
            Part.Phase=FMath::Fmod(Part.Phase+RotorRPM*2*PI/60*Dt*Part.Spin,2*PI);
            Part.Mesh->SetRelativeRotation(Part.Rest.GetRotation()*FQuat(FVector::UpVector,Part.Phase));
            Part.Mesh->SetVisibility(RotorRPM<2200);
        }
        else if(Part.Role==TEXT("rotor_blur"))Part.Mesh->SetVisibility(RotorRPM>=2200);
        else if(Part.Role==TEXT("wheel"))
        {
            Part.Phase=FMath::Fmod(Part.Phase+TreadSpeed/FMath::Max(1.f,Part.Radius)*Dt,2*PI);
            Part.Mesh->SetRelativeRotation(Part.Rest.GetRotation()*FQuat(FVector(0,1,0),Part.Phase));
        }
        else if(Part.Role==TEXT("track"))
        {
            Part.Phase=FMath::Fmod(Part.Phase+TreadSpeed*Dt/505.f,1.f);
            if(auto* Mat=Cast<UMaterialInstanceDynamic>(Part.Mesh->GetMaterial(0)))Mat->SetScalarParameterValue(TEXT("Travel"),Part.Phase);
        }
        else if(Part.Role==TEXT("ramp"))
            Part.Mesh->SetRelativeRotation(FRotator(-FMath::Lerp(80.f,-27.f,RampDeployment),0,0));
        else if(Part.Role==TEXT("ramp_extension"))
            Part.Mesh->SetRelativeLocation(Part.Rest.GetLocation()+FVector(-52*FMath::Clamp((RampDeployment-.5f)*2,0.f,1.f),0,0));
        else if(Part.Role==TEXT("winch"))
        {
            if(Service&&RampDeployment>.8f)Part.Phase+=Dt*5;
            Part.Mesh->SetRelativeRotation(Part.Rest.GetRotation()*FQuat(FVector(0,1,0),Part.Phase));
        }
        else if(Part.Role==TEXT("gimbal"))
            Part.Mesh->SetRelativeRotation(FRotator(State==TEXT("surveying")?-20:0,FMath::Sin(GetWorld()->GetTimeSeconds()*.35f)*18,0));
    }
}

void AMRAgent::DriveDistrictGround(const FVector& Desired)
{
    if(GetActorUpVector().Z<.3)
    {
        if(State!="overturned"){State="overturned";Mission->AppendEvent(TEXT("agent_overturned"),AgentId);}
        return;
    }
    const float Mass=Body->GetMass();float Support=0;GroundContacts=0;
    FCollisionQueryParams Params;Params.AddIgnoredActor(this);
    for(AMRAgent* Other:Mission->Agents)if(Other!=this)Params.AddIgnoredActor(Other);
    for(float X:{-90.f,0.f,90.f})for(float Y:{-48.f,48.f})
    {
        const FVector Point=GetActorTransform().TransformPosition(FVector(X,Y,0));
        FHitResult Hit;
        if(GetWorld()->LineTraceSingleByChannel(Hit,Point+FVector(0,0,30),Point-FVector(0,0,90),ECC_Visibility,Params)
            &&Hit.ImpactNormal.Z>.35)
        {
            const float Height=Point.Z-Hit.ImpactPoint.Z;
            const float Speed=Body->GetPhysicsLinearVelocityAtPoint(Point).Z;
            const float Force=FMath::Clamp((53.f-Height)*Mass*20.f-Speed*Mass*1.3f,0.f,Mass*980.f*.7f);
            Body->AddForceAtLocation(FVector(0,0,Force),Point);Support+=Force;GroundContacts++;
        }
    }
    if(GroundContacts<2)return;
    FVector Forward=GetActorForwardVector();Forward.Z=0;Forward.Normalize();
    const FVector Side=FVector::CrossProduct(FVector::UpVector,Forward);
    const FVector V=Body->GetPhysicsLinearVelocity();
    // A returned rover faces the dock head. Back down the guide rails before
    // turning in the open apron; a 2.5 m chassis cannot rotate in a 2 m dock.
    const bool Reverse=bReverseInitialLeg&&PathIndex==0;
    const FVector DriveDirection=Reverse?-Desired:Desired;
    const float Alignment=Desired.IsNearlyZero()?1:FMath::Clamp(FVector::DotProduct(Forward,DriveDirection.GetSafeNormal()),0.f,1.f);
    const bool DockEntry=IsDockEntryLeg();
    const bool DockTurn=DockEntry&&!Desired.IsNearlyZero()&&
        FMath::Abs(FMath::FindDeltaAngleDegrees(GetActorRotation().Yaw,Desired.Rotation().Yaw))>12;
    const bool Unsafe=Mission->IsUnsafeGround(GetActorLocation()+Desired.GetSafeNormal()*230);
    const float SpeedTarget=Unsafe||DockTurn?0:(Reverse?-FMath::Min(100.f,float(Desired.Size())):Desired.Size())*
        FMath::Pow(Alignment,3.f)*(bCarrying?.8f:1.f)*Mission->GroundSpeedFactor(GetActorLocation());
    FVector Acceleration=Forward*((SpeedTarget-FVector::DotProduct(V,Forward))*4.f)
        -Side*FVector::DotProduct(V,Side)*5.f;
    // A frame with unloaded springs can still have tyre/track contact with the
    // ground. Keep bounded braking at that contact instead of coasting through
    // a safety stop until the next spring compression.
    const float Traction=FMath::Max(Support/Mass,490.f)*.72f;
    Acceleration=Acceleration.GetClampedToMaxSize(Traction);
    Body->AddForce(Acceleration*Mass);
    float Yaw=0;
    if(State=="loading"||State=="unloading")Yaw=FMath::DegreesToRadians(FMath::FindDeltaAngleDegrees(GetActorRotation().Yaw,ServiceHeading))*5;
    if(Desired.Size2D()>5)Yaw=FMath::DegreesToRadians(FMath::FindDeltaAngleDegrees(GetActorRotation().Yaw,DriveDirection.Rotation().Yaw))*5;
    Yaw-=Body->GetPhysicsAngularVelocityInRadians().Z*3;
    Body->AddTorqueInRadians(FVector(0,0,FMath::Clamp(Yaw,-4.f,4.f)),NAME_None,true);
}
