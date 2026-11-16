#include "MRExplorationGrid.h"
#include "MRExplorationMemory.h"
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
    TestTrue(TEXT("harbor and largest city share one bounded grid"),Grid.Reset(321,300,500,FVector2D(-10500,0)));
    Grid.Reveal({FIntPoint(5,8)});
    TestTrue(TEXT("negative harbor coordinates do not wrap"),Grid.IsOpen(FVector(-7750,4250,0)));
    TestFalse(TEXT("right edge stays outside after an origin shift"),Grid.IsOpen(FVector(150000,0,0)));
    TestFalse(TEXT("oversized allocation is rejected"),Grid.Reset(384,384));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRDeliveredSurfaceMemory,"MetaRescue.Core.DeliveredSurfaceMemory",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRDeliveredSurfaceMemory::RunTest(const FString&)
{
    FMRExplorationMemory Memory;Memory.Reset(4,4,500,FVector2D(-1000,0));
    FMRSeenSurface Early;Early.Cell=FIntPoint(1,1);Early.PointCm=FVector(-250,750,12);Early.Source=TEXT("scout-a");
    Early.Quality=.8;Early.ObservedAt=2;Early.ReceivedAt=8;
    TestFalse(TEXT("sensor collection alone does not open terrain"),Memory.Grid.IsOpen(Early.Cell));
    TestEqual(TEXT("delivered observation opens and stores a surface"),Memory.Apply({Early}),1);
    auto Later=Early;Later.ObservedAt=10;Later.ReceivedAt=11;Later.PointCm.Z=-220;
    TestEqual(TEXT("revisiting an opened cell updates remembered geometry"),Memory.Apply({Later}),1);
    const int32 Revision=Memory.GetRevision();
    Early.ReceivedAt=12;
    TestEqual(TEXT("late older delivery cannot restore old geometry"),Memory.Apply({Early}),0);
    TestEqual(TEXT("remembered height stays at last observed collapse"),Memory.Last(Early.Cell)->PointCm.Z,-220.);
    TestEqual(TEXT("camera reads and duplicate delivery do not change revision"),Memory.Apply({Later}),0);
    TestEqual(TEXT("state revision stays stable"),Memory.GetRevision(),Revision);
    auto Invalid=Later;Invalid.ObservedAt=20;Invalid.ReceivedAt=19;
    TestEqual(TEXT("future observation is rejected"),Memory.Apply({Invalid}),0);
    Invalid=Later;Invalid.Quality=.1;
    TestEqual(TEXT("opaque smoke cannot open ground"),Memory.Apply({Invalid}),0);
    Memory.Reset(4,4,500,FVector2D(-1000,0));
    TestFalse(TEXT("reset clears permanent opening"),Memory.Grid.IsOpen(Early.Cell));
    TestNull(TEXT("reset clears remembered changes"),Memory.Last(Early.Cell));return true;
}
#endif
