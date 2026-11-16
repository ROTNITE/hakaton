#include "MRStructureState.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "UObject/StrongObjectPtr.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRStructureOwnership,"MetaRescue.Environment.StructureOwnership",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRStructureOwnership::RunTest(const FString&)
{
    auto* Cube=LoadObject<UStaticMesh>(nullptr,TEXT("/Engine/BasicShapes/Cube.Cube"));
    if(!TestNotNull(TEXT("engine geometry exists"),Cube))return false;
    TStrongObjectPtr<UInstancedStaticMeshComponent> Batch(NewObject<UInstancedStaticMeshComponent>());
    Batch->SetStaticMesh(Cube);Batch->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    const FTransform PoseA(FVector(1000,0,0)),PoseB(FVector(2000,0,0));
    FMRStructurePiece A,B;A.Component=Batch.Get();B.Component=Batch.Get();A.Instanced=B.Instanced=true;
    A.InitialTransform=PoseA;B.InitialTransform=PoseB;
    A.Instance=Batch->AddInstanceById(PoseA,true);B.Instance=Batch->AddInstanceById(PoseB,true);
    const auto BId=B.Instance;
    if(!TestTrue(TEXT("two persistent instance identities"),A.Instance.IsValid()&&B.Instance.IsValid()))return false;
    TestTrue(TEXT("one damaged part is removed"),A.Remove());
    TestEqual(TEXT("the neighboring house still owns its part"),Batch->GetNumInstances(),1);
    FTransform Actual;
    const int32 IndexB=Batch->GetInstanceIndexForId(BId);
    TestTrue(TEXT("the surviving ID remains resolvable after compaction"),IndexB!=INDEX_NONE);
    if(IndexB!=INDEX_NONE)
    {
        Batch->GetInstanceTransform(IndexB,Actual,true);
        TestTrue(TEXT("removal never moves the neighbor's geometry"),Actual.Equals(PoseB));
    }
    TestFalse(TEXT("duplicate removal is idempotent"),A.Remove());
    TestTrue(TEXT("episode reset restores the real original part"),A.Restore());
    TestEqual(TEXT("restored instance count"),Batch->GetNumInstances(),2);
    TestTrue(TEXT("neighbor identity survives restoration"),B.Instance==BId);
    TestFalse(TEXT("duplicate restore cannot duplicate a wall"),A.Restore());
    return true;
}
#endif
