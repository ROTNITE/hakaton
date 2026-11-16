#include "MRAgent.h"
#include "MRWorld.h"
#include "Components/BoxComponent.h"
#include "Dom/JsonObject.h"

void AMRAgent::InitializeGroundPayload()
{
    if(bAerial||!Mission->bDisasterCity||!Mission->CityLayout->HasField(TEXT("hydrology")))return;
    GroundPayloadCollision=NewObject<UBoxComponent>(this);AddInstanceComponent(GroundPayloadCollision);
    GroundPayloadCollision->SetupAttachment(Body);GroundPayloadCollision->SetMobility(EComponentMobility::Movable);
    GroundPayloadCollision->SetBoxExtent(FVector(1));GroundPayloadCollision->SetRelativeLocation(FVector(0,0,50));
    GroundPayloadCollision->SetCollisionProfileName(TEXT("PhysicsActor"));GroundPayloadCollision->SetCollisionResponseToChannel(ECC_Camera,ECR_Ignore);
    GroundPayloadCollision->BodyInstance.SetMassOverride(.01f,true);GroundPayloadCollision->RegisterComponent();GroundPayloadCollision->WeldTo(Body);
    GroundPayloadCollision->SetNotifyRigidBodyCollision(true);GroundPayloadCollision->OnComponentHit.AddDynamic(this,&AMRAgent::OnAgentHit);
    SetGroundPayloadKg(0);
}

void AMRAgent::SetGroundPayloadKg(double MassKg)
{
    if(!ensure(FMath::IsFinite(MassKg)&&MassKg>=0&&MassKg<=130))return;
    if(!GroundPayloadCollision)
    {
        Body->SetMassOverrideInKg(NAME_None,240+MassKg);Body->SetCenterOfMass(MassKg>0?FVector(0,0,16):FVector::ZeroVector);return;
    }
    const FVector Half=MassKg>0?FVector(105,55,35):FVector(1);
    if(GroundPayloadCollision->GetUnscaledBoxExtent()!=Half)
    {
        GroundPayloadCollision->UnWeldFromParent();GroundPayloadCollision->SetBoxExtent(Half,false);GroundPayloadCollision->WeldTo(Body);
    }
    GroundPayloadCollision->BodyInstance.SetMassOverride(.01+MassKg,true);GroundPayloadCollision->BodyInstance.COMNudge=FVector::ZeroVector;
    Body->BodyInstance.SetMassOverride(239.99f,true);Body->BodyInstance.COMNudge=FVector::ZeroVector;Body->BodyInstance.UpdateMassProperties();
    ensureAlwaysMsgf(FMath::Abs(Body->GetMass()-(240+MassKg))<.05,TEXT("Rover welded payload mass mismatch"));
}
