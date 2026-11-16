#include "MRExplorationGrid.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRPermanentExploration,"MetaRescue.Core.PermanentExploration",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRPermanentExploration::RunTest(const FString&)
{
    FMRExplorationGrid Grid;
    TestTrue(TEXT("configured knowledge grid"),Grid.Reset(50,50));
    TestEqual(TEXT("unexplored at reset"),Grid.OpenCount(),0);
    TestEqual(TEXT("base opens only its declared cells"),Grid.RevealBase(FBox(FVector(0,0,-20),FVector(1000,1000,500))),4);
    TestFalse(TEXT("outside base stays unknown"),Grid.IsOpen(FIntPoint(2,2)));
    const TArray<FIntPoint> Delivered={FIntPoint(2,2),FIntPoint(3,2),FIntPoint(3,2),FIntPoint(-1,2)};
    TestEqual(TEXT("delivered observations open distinct, valid cells"),Grid.Reveal(Delivered),2);
    const int32 Revision=Grid.GetRevision();
    TestEqual(TEXT("an empty or lost report cannot revoke exploration"),Grid.Reveal({}),0);
    TestEqual(TEXT("repeated delivery is idempotent"),Grid.Reveal(Delivered),0);
    TestEqual(TEXT("revision changes only on new knowledge"),Grid.GetRevision(),Revision);
    TestTrue(TEXT("exploration persists independently of altitude"),Grid.IsOpen(FVector(1250,1250,9000)));
    TestFalse(TEXT("right boundary does not wrap to the next row"),Grid.IsOpen(FVector(25000,0,0)));
    const auto Spans=Grid.RowSpans();
    TestEqual(TEXT("deterministic compact snapshot"),Spans.Num(),3);
    TestTrue(TEXT("adjacent delivered cells merge into one span"),Spans.Contains(FIntVector(2,2,4)));
    Grid.Reset(300,300);
    TestEqual(TEXT("new episode clears previous exploration"),Grid.OpenCount(),0);
    TestFalse(TEXT("new map cannot inherit old cells"),Grid.IsOpen(FIntPoint(2,2)));
    TestTrue(TEXT("largest accepted map fits its grid"),Grid.Reveal({FIntPoint(299,299)})==1);
    return true;
}
#endif
