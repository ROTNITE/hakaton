#include "MRStructureState.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "UObject/StrongObjectPtr.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRStructureOwnership,"MetaRescue.Environment.StructureOwnership",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRStoreyFailure,"MetaRescue.Environment.StoreyFailure",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)

bool FMRStoreyFailure::RunTest(const FString&)
{
    FMRStructureState Building;Building.Bounds=FBox(FVector(-450,-450,0),FVector(450,450,924));
    auto Add=[&](double Bottom,double Top)
    {FMRStructurePiece Piece;Piece.Bounds=FBox(FVector(-450,-450,Bottom),FVector(450,450,Top));Building.Pieces.Add(Piece);};
    Add(0,16);Add(16,294);Add(300,316);Add(316,594);Add(600,616);Add(616,894);Add(900,924);
    auto Failure=Building.UpperStoreyPieces();
    TestTrue(TEXT("the unsupported upper wall and roof fail"),Failure.Contains(5)&&Failure.Contains(6));
    TestFalse(TEXT("the supported slab below the failure remains"),Failure.Contains(4));
    TestFalse(TEXT("the lower storey remains supported"),Failure.Contains(3));
    TestFalse(TEXT("the foundation is never replaced with airborne rubble"),Failure.Contains(0));
    for(int32 Index:Failure)Building.Pieces[Index].Removed=true;
    TestEqual(TEXT("smoke emission follows the remaining geometry"),Building.RemainingTopCm(),616.);
    Failure=Building.UpperStoreyPieces();
    TestTrue(TEXT("a subsequent event can remove the next storey"),Failure.Contains(3));
    TestFalse(TEXT("the already missing roof cannot fall twice"),Failure.Contains(6));
    return true;
}
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
