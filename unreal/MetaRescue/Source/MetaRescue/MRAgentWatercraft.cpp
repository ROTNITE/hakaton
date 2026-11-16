#include "MRAgent.h"
#include "MRWorld.h"
#include "MRUrbanWater.h"
#include "MRWatercraftHydro.h"
#include "Components/BoxComponent.h"
#include "Components/StaticMeshComponent.h"
#include "PhysicsEngine/PhysicsConstraintComponent.h"
#include "PhysicalMaterials/PhysicalMaterial.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Dom/JsonObject.h"

bool AMRAgent::InitializeWatercraft(AMRWorld* InWorld,int32 InId,const FString& Id,const TSharedPtr<FMRWatercraftHydro>& Profile)
{
    if(!Profile||!Profile->IsValid())return false;
    Mission=InWorld;AgentId=InId;PublicId=Id;Category=TEXT("surface_water");WatercraftProfile=Profile;bRescueWatercraft=true;
    Dock=Previous=WatercraftHoldPosition=GetActorLocation();
    const auto Bounds=Mission->CityLayout->GetObjectField(TEXT("bounds"));const auto& Low=Bounds->GetArrayField(TEXT("min"));const auto& High=Bounds->GetArrayField(TEXT("max"));
    MediumLimits=FBox(FVector(Low[0]->AsNumber(),Low[1]->AsNumber(),Low[2]->AsNumber())*100,
        FVector(High[0]->AsNumber(),High[1]->AsNumber(),High[2]->AsNumber())*100);
    // A tiny mass carrier plus two separated hulls and the real raised deck.
    // No broad collision slab fills the open space between the two hulls.
    Body->SetBoxExtent(FVector(1));Body->SetEnableGravity(true);Body->SetLinearDamping(.02f);Body->SetAngularDamping(.4f);
    auto* Contact=NewObject<UPhysicalMaterial>(this);Contact->Friction=.045f;Contact->StaticFriction=.06f;
    Contact->bOverrideFrictionCombineMode=true;Contact->FrictionCombineMode=EFrictionCombineMode::Min;
    Body->SetPhysMaterialOverride(Contact);Body->BodyInstance.SetMassOverride(.01f,true);
    Body->BodyInstance.COMNudge=FVector::ZeroVector;Body->SetSimulatePhysics(true);
    // Welded mass properties combine the original BodyInstance of every shape.
    // Setting the parent's mass alone also adds the children's default masses.
    // Distribute dry mass at the hulls/deck, with the chosen dry CG at body origin.
    const double HullCG=Profile->BodyAboveKeelM-.16,DeckCG=Profile->DeckAboveKeelM-.04;
    const double CargoCG=Profile->DeckAboveKeelM+.35;
    const double DeckMass=(Profile->DryMassKg*Profile->BodyAboveKeelM-.01*Profile->BodyAboveKeelM-
        .01*CargoCG-(Profile->DryMassKg-.02)*HullCG)/(DeckCG-HullCG);
    const double HullMass=(Profile->DryMassKg-.02-DeckMass)*.5;
    if(DeckMass<=0||HullMass<=0)return false;
    auto Hull=[&](FVector Position,FVector Half,double MassKg)
    {
        auto* Shape=NewObject<UBoxComponent>(this);AddInstanceComponent(Shape);Shape->SetupAttachment(Body);
        Shape->SetMobility(EComponentMobility::Movable);Shape->SetBoxExtent(Half);Shape->SetRelativeLocation(Position);
        Shape->SetCollisionProfileName(TEXT("PhysicsActor"));Shape->SetCollisionResponseToChannel(ECC_Camera,ECR_Ignore);
        Shape->BodyInstance.SetMassOverride(MassKg,true);Shape->BodyInstance.COMNudge=FVector::ZeroVector;
        Shape->SetPhysMaterialOverride(Contact);Shape->RegisterComponent();Shape->WeldTo(Body);
        Shape->SetNotifyRigidBodyCollision(true);Shape->OnComponentHit.AddDynamic(this,&AMRAgent::OnAgentHit);
        return Shape;
    };
    for(double Side:{-1.,1.})Hull(FVector(0,Side*60,-16),FVector(210,34,29),HullMass);
    Hull(FVector(0,0,(Profile->DeckAboveKeelM-Profile->BodyAboveKeelM)*100-4),FVector(175,85,4),DeckMass);
    WatercraftCargoMass=Hull(FVector(0,0,(CargoCG-Profile->BodyAboveKeelM)*100),FVector(1),.01);
    auto* Mesh=LoadObject<UStaticMesh>(nullptr,TEXT("/Game/RescueAssets/WatercraftV1/SM_RescueWaterCatamaran.SM_RescueWaterCatamaran"));
    if(!Mesh)return false;
    auto* Visual=NewObject<UStaticMeshComponent>(this);AddInstanceComponent(Visual);Visual->SetupAttachment(Body);
    Visual->SetMobility(EComponentMobility::Movable);Visual->SetStaticMesh(Mesh);Visual->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    Visual->SetRelativeLocation(FVector(0,0,-100*Profile->BodyAboveKeelM));Visual->RegisterComponent();Parts.Add(Visual);
    BatteryCapacityWh=Energy=Profile->BatteryWh;MaxSpeed=Profile->MaximumSpeedMPerSecond*100;
    if(!SetWatercraftPayloadKg(0))return false;
    MakeWatercraftMooring();State=TEXT("moored");
    UE_LOG(LogTemp,Display,TEXT("MR_WATERCRAFT id=%s mass_kg=%.3f draft_m=%.4f deck_m=%.4f"),
        *PublicId,Body->GetMass(),Profile->EquilibriumDraftM(Profile->DryMassKg).Get(0),Profile->DeckAboveKeelM);
    return true;
}

bool AMRAgent::SetWatercraftPayloadKg(double MassKg)
{
    if(!WatercraftCargoMass||!WatercraftProfile||!FMath::IsFinite(MassKg)||
       MassKg<0||MassKg>WatercraftProfile->PayloadLimitKg)return false;
    // Use the child's own instance: GetBodyInstance() resolves to the welded parent.
    WatercraftCargoMass->BodyInstance.SetMassOverride(.01+MassKg,true);
    Body->BodyInstance.UpdateMassProperties();
    const double Expected=WatercraftProfile->DryMassKg+MassKg;
    if(FMath::Abs(Body->GetMass()-Expected)>.05)
    {UE_LOG(LogTemp,Error,TEXT("MR_WATERCRAFT_MASS id=%s expected=%.3f actual=%.3f"),*PublicId,Expected,Body->GetMass());return false;}
    return true;
}

void AMRAgent::MakeWatercraftMooring()
{
    if(WatercraftMooring)WatercraftMooring->DestroyComponent();
    WatercraftMooring=NewObject<UPhysicsConstraintComponent>(this);AddInstanceComponent(WatercraftMooring);
    WatercraftMooring->SetupAttachment(Body);WatercraftMooring->SetWorldLocation(GetActorLocation());WatercraftMooring->SetWorldRotation(FRotator::ZeroRotator);WatercraftMooring->RegisterComponent();
    WatercraftMooring->SetLinearXLimit(ELinearConstraintMotion::LCM_Locked,0);
    WatercraftMooring->SetLinearYLimit(ELinearConstraintMotion::LCM_Locked,0);
    WatercraftMooring->SetLinearZLimit(ELinearConstraintMotion::LCM_Free,0);
    WatercraftMooring->SetAngularTwistLimit(EAngularConstraintMotion::ACM_Free,0);
    WatercraftMooring->SetAngularSwing1Limit(EAngularConstraintMotion::ACM_Locked,0);
    WatercraftMooring->SetAngularSwing2Limit(EAngularConstraintMotion::ACM_Free,0);
    WatercraftMooring->SetDisableCollision(true);WatercraftMooring->SetConstrainedComponents(Body,NAME_None,nullptr,NAME_None);
    bWatercraftMoored=true;
}
void AMRAgent::ReleaseWatercraftMooring()
{
    if(!bWatercraftMoored)return;
    if(WatercraftMooring){WatercraftMooring->DestroyComponent();WatercraftMooring=nullptr;}
    bWatercraftMoored=false;State=TEXT("launching");Mission->AppendEvent(TEXT("watercraft_mooring_released"),AgentId);
}
void AMRAgent::ResetWatercraft()
{
    SetWatercraftPayloadKg(0);
    WatercraftHoldPosition=GetActorLocation();WatercraftDisplacedM3=WatercraftLeftJetN=WatercraftRightJetN=0;
    MakeWatercraftMooring();State=TEXT("moored");
}

void AMRAgent::DriveWatercraft(float Dt)
{
    const auto& Hull=*WatercraftProfile;const FTransform Pose=GetActorTransform();const FVector P=GetActorLocation();
    const FVector Forward=GetActorForwardVector(),Side=GetActorRightVector();
    const double Gravity=FMath::Abs(GetWorld()->GetGravityZ())/100,Mass=Body->GetMass();
    WatercraftDisplacedM3=0;GroundContacts=0;
    for(int32 I=0;I<8;++I)
    {
        const FVector Local(Hull.SectionX[I]*100,Hull.SectionY[I]*100,-Hull.BodyAboveKeelM*100+25);
        FVector Point=Pose.TransformPosition(Local);const auto Water=Mission->WaterAtCm(Point);
        if(!Water.InDomain||Water.DepthCm<=.1)continue;
        const double Height=Pose.InverseTransformPosition(FVector(Point.X,Point.Y,Water.StageCm)).Z/100+Hull.BodyAboveKeelM;
        const double Volume=Hull.SectionVolumeM3(I,Height);if(Volume<=0)continue;
        WatercraftDisplacedM3+=Volume;
        // Horizontal drag acts below the waterline, not at a fixed dry point.
        Point=Pose.TransformPosition(FVector(Local.X,Local.Y,
            (FMath::Clamp(Height,0.,.55)*.5-Hull.BodyAboveKeelM)*100));
        const FVector Relative=(Body->GetPhysicsLinearVelocityAtPoint(Point)-Water.CurrentCmPerSecond)/100;
        const double Area=FMath::Max(0.,(Hull.SectionVolumeM3(I,Height+.005)-Hull.SectionVolumeM3(I,Height-.005))/.01);
        const double Radiation=2*.55*FMath::Sqrt((Mass/8+1000*Volume)*1000*Gravity*Area);
        const double Vertical=1000*Gravity*Volume-Radiation*Relative.Z;
        const double U=FVector::DotProduct(Relative,Forward),V=FVector::DotProduct(Relative,Side);
        const FVector Drag=Forward*(-.5*1000*.35*(Volume/1.15)*FMath::Abs(U)*U)+
            Side*(-.5*1000*1.0*(Volume/.7)*FMath::Abs(V)*V);
        Body->AddForceAtLocation((Drag+FVector(0,0,Vertical))*100,Point);
    }
    const auto Water=Mission->WaterAtCm(P);WatercraftCurrentCmPerSecond=Water.CurrentCmPerSecond;
    FVector Desired=FVector::ZeroVector;
    if(!bExternalHold&&Path.IsValidIndex(PathIndex))
    {
        FVector Delta=Path[PathIndex]-P;Delta.Z=0;
        const bool Last=PathIndex==Path.Num()-1;
        if(Delta.Size()<50&&(!Last||Body->GetPhysicsLinearVelocity().Size2D()<30))
        {
            WatercraftHoldPosition=Path[PathIndex];++PathIndex;
            if(RouteFinished())Arrived();
        }
        if(Path.IsValidIndex(PathIndex))
        {Delta=Path[PathIndex]-P;Delta.Z=0;Desired=Delta.GetSafeNormal()*FMath::Min(double(MaxSpeed),Delta.Size()*1.2);}
    }
    else if(!bWatercraftMoored)
    {
        FVector Error=WatercraftHoldPosition-P;Error.Z=0;
        if(Error.Size2D()>25)Desired=Error.GetClampedToMaxSize2D(100);
    }
    IntendedVelocity=Desired;
    WatercraftLeftJetN=WatercraftRightJetN=0;
    if(bWatercraftMoored||!IsOperational())return;
    StopReason.Empty();StopObstacle.Empty();
    const FVector Velocity=Body->GetPhysicsLinearVelocity();
    if(Desired.Size2D()>5&&WatercraftDisplacedM3*1000>Mass*.6)
    {
        const double Ahead=FMath::Clamp(Velocity.Size2D()*.8+150,150.,800.);
        const FVector End=P+Desired.GetSafeNormal2D()*Ahead;
        const double Draft=Hull.EquilibriumDraftM(Mass).Get(.5)*100;
        FHitResult Hit;FCollisionQueryParams Query(SCENE_QUERY_STAT(MRWatercraftSafety),false,this);
        const bool Obstacle=GetWorld()->SweepSingleByChannel(Hit,P+FVector(0,0,40),End+FVector(0,0,40),GetActorQuat(),
            ECC_Visibility,FCollisionShape::MakeBox(FVector(235,105,80)),Query)&&Hit.ImpactNormal.Z<.7;
        if(!MediumPointAllowed(End)||Mission->WaterAtCm(End).DepthCm<Draft+8||Obstacle)
        {Desired=FVector::ZeroVector;StopReason=Obstacle?TEXT("obstacle_on_route"):TEXT("shallow_water_on_route");
         StopObstacle=Obstacle?GetNameSafe(Hit.GetComponent()):TEXT("measured_depth");WatercraftHoldPosition=P;}
    }
    FVector Heading=Desired;
    if(Heading.Size2D()<10&&WatercraftCurrentCmPerSecond.Size2D()>20)Heading=-WatercraftCurrentCmPerSecond;
    const double Angle=Heading.Size2D()>5?FMath::DegreesToRadians(FMath::FindDeltaAngleDegrees(GetActorRotation().Yaw,Heading.Rotation().Yaw)):0;
    const double SpeedTarget=Desired.Size2D()*FMath::Pow(FMath::Max(0.,FMath::Cos(Angle)),3.);
    const double Actual=FVector::DotProduct(Velocity,Forward)/100;
    const double Relative=FVector::DotProduct(Velocity-WatercraftCurrentCmPerSecond,Forward)/100;
    const double DragFeed=.5*1000*.35*(WatercraftDisplacedM3/1.15)*FMath::Abs(Relative)*Relative;
    const double Total=Mass*(SpeedTarget/100-Actual)*2+DragFeed;
    const double Inertia=Body->GetInertiaTensor().Z/10000;
    const double Torque=Inertia*FMath::Clamp(Angle*2-Body->GetPhysicsAngularVelocityInRadians().Z*2,-1.2,1.2);
    double Left=FMath::Clamp(Total*.5+Torque/1.2,-Hull.MaximumJetThrustN,Hull.MaximumJetThrustN);
    double Right=FMath::Clamp(Total*.5-Torque/1.2,-Hull.MaximumJetThrustN,Hull.MaximumJetThrustN);
    auto JetPower=[&](double Force)
    {
        const double F=FMath::Abs(Force),Speed=FMath::Abs(Relative);
        const double Induced=(FMath::Sqrt(Speed*Speed+2*F/(1000*.025))-Speed)*.5;
        return F*(Speed+Induced)/.65;
    };
    if(!bUnlimitedEnergy)
    {
        double Low=0,High=1;
        for(int32 I=0;I<16;++I){const double M=(Low+High)*.5;
            if((JetPower(Left*M)+JetPower(Right*M))*Dt/3600>Energy)High=M;else Low=M;}
        Left*=Low;Right*=Low;
    }
    double UsedPower=0;
    for(int32 I=0;I<2;++I)
    {
        const FVector Jet=Pose.TransformPosition(FVector(-180,I?60:-60,-Hull.BodyAboveKeelM*100+8));
        const auto Medium=Mission->WaterAtCm(Jet);double Force=I?Right:Left;
        if(Medium.DepthCm<=0||Medium.StageCm-Jet.Z<3)Force=0;
        Body->AddForceAtLocation(Forward*(Force*100),Jet);UsedPower+=JetPower(Force);
        (I?WatercraftRightJetN:WatercraftLeftJetN)=Force;
    }
    Spend(UsedPower*Dt/3600,MotionWh);
}
