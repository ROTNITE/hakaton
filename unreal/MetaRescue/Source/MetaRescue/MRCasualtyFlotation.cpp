#include "MRWorld.h"
#include "MRUrbanWater.h"
#include "Components/BoxComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "PhysicalMaterials/PhysicalMaterial.h"

// The existing rescue stretcher receives two sealed foam floats. Human 80 kg,
// stretcher/floats 18 kg; 157.5 litres total sealed displacement. This is a
// bounded game model, not a certification of a real medical device.
USceneComponent* AMRWorld::MakeCasualtyRoot(AActor* Visual,FMRTarget& Target)
{
    if(!bDisasterCity||!UrbanWater)
    {
        auto* Root=NewObject<USceneComponent>(Visual);Visual->SetRootComponent(Root);
        Visual->AddInstanceComponent(Root);Root->RegisterComponent();return Root;
    }
    auto* Body=NewObject<UBoxComponent>(Visual);Visual->SetRootComponent(Body);Visual->AddInstanceComponent(Body);
    Body->SetMobility(EComponentMobility::Movable);Body->SetBoxExtent(FVector(95,25,12));
    Body->SetCollisionProfileName(TEXT("PhysicsActor"));Body->SetCollisionResponseToChannel(ECC_Visibility,ECR_Ignore);
    Body->SetCollisionResponseToChannel(ECC_Camera,ECR_Ignore);Body->BodyInstance.SetMassOverride(80,true);
    Body->SetLinearDamping(.05);Body->SetAngularDamping(.6);Body->RegisterComponent();
    Target.VisualAnchorOffsetCm=41.25;Target.FloatBody=Body;Target.Position.Z+=Target.VisualAnchorOffsetCm;
    Visual->SetActorLocation(Target.Position);Body->SetSimulatePhysics(true);
    for(double Side:{-1.,1.})
    {
        auto* Float=NewObject<UBoxComponent>(Visual);Visual->AddInstanceComponent(Float);Float->SetupAttachment(Body);
        Float->SetMobility(EComponentMobility::Movable);Float->SetBoxExtent(FVector(105,12.5,7.5));
        Float->SetRelativeLocation(FVector(0,Side*40,7.5-Target.VisualAnchorOffsetCm));
        Float->SetCollisionProfileName(TEXT("PhysicsActor"));Float->SetCollisionResponseToChannel(ECC_Visibility,ECR_Ignore);
        Float->SetCollisionResponseToChannel(ECC_Camera,ECR_Ignore);Float->BodyInstance.SetMassOverride(9,true);
        Float->RegisterComponent();Float->WeldTo(Body);
        auto* Mesh=NewObject<UStaticMeshComponent>(Visual);Visual->AddInstanceComponent(Mesh);Mesh->SetupAttachment(Float);
        Mesh->SetMobility(EComponentMobility::Movable);Mesh->SetStaticMesh(LoadObject<UStaticMesh>(nullptr,TEXT("/Engine/BasicShapes/Cube.Cube")));
        Mesh->SetRelativeScale3D(FVector(2.1,.25,.15));Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        Mesh->SetMaterial(0,LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/Materials/MI_Orange.MI_Orange")));Mesh->RegisterComponent();
    }
    Body->BodyInstance.UpdateMassProperties();
    // Bands run around both foam blocks below the stretcher pad.
    for(double X:{-70.,70.})for(double Side:{-1.,1.})
    {
        auto* Band=NewObject<UStaticMeshComponent>(Visual);Visual->AddInstanceComponent(Band);Band->SetupAttachment(Body);
        Band->SetMobility(EComponentMobility::Movable);Band->SetStaticMesh(LoadObject<UStaticMesh>(nullptr,TEXT("/Engine/BasicShapes/Cube.Cube")));
        Band->SetRelativeLocation(FVector(X,Side*40,15.5-Target.VisualAnchorOffsetCm));Band->SetRelativeScale3D(FVector(.04,.28,.01));
        Band->SetCollisionEnabled(ECollisionEnabled::NoCollision);Band->SetMaterial(0,LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/Materials/MI_Dark.MI_Dark")));Band->RegisterComponent();
    }
    ensureAlwaysMsgf(FMath::Abs(Body->GetMass()-98)<.05,TEXT("Floating stretcher welded mass must be 98 kg"));
    return Body;
}

void AMRWorld::TickFloatingCasualties(float Dt)
{
    if(!UrbanWater)return;
    const double Gravity=FMath::Abs(GetWorld()->GetGravityZ())/100;
    for(auto& Target:Targets)
    {
        auto* Body=Target.FloatBody.Get();
        if(!Body||Target.bAssigned||Target.bRescued||Target.SupportCarrier.IsValid()||!Target.Visual||!Body->IsSimulatingPhysics())continue;
        Target.Position=Target.Visual->GetActorLocation();
        const FTransform Pose=Target.Visual->GetActorTransform();
        Target.FloatDisplacedM3=0;
        for(double X:{-.7875,-.2625,.2625,.7875})for(double Side:{-1.,1.})
        {
            const FVector Keel=Pose.TransformPosition(FVector(X*100,Side*40,-Target.VisualAnchorOffsetCm));
            const auto Water=WaterAtCm(Keel);if(!Water.InDomain||Water.DepthCm<=0)continue;
            const double Height=Pose.InverseTransformPosition(FVector(Keel.X,Keel.Y,Water.StageCm)).Z/100+Target.VisualAnchorOffsetCm/100;
            const double Draft=FMath::Clamp(Height,0.,.15),Area=.525*.25,Volume=Draft*Area;
            if(Volume<=0)continue;
            Target.FloatDisplacedM3+=Volume;
            const FVector Point=Pose.TransformPosition(FVector(X*100,Side*40,Draft*50-Target.VisualAnchorOffsetCm));
            const FVector Relative=(Body->GetPhysicsLinearVelocityAtPoint(Point)-Water.CurrentCmPerSecond)/100;
            const double Damping=2*.6*FMath::Sqrt((98./8+1000*Volume)*1000*Gravity*Area);
            const FVector Drag=FVector(Relative.X,Relative.Y,0)*(-.5*1000*(Volume/.5)*Relative.Size2D());
            Body->AddForceAtLocation((Drag+FVector(0,0,1000*Gravity*Volume-Damping*Relative.Z))*100,Point);
        }
    }
}
