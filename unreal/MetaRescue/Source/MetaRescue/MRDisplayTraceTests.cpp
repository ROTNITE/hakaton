#if WITH_DEV_AUTOMATION_TESTS
#include "MRDisplayTrace.h"
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRDisplayTraceTest,"MetaRescue.UI.DisplayTraceBoundaries",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRDisplayTraceTest::RunTest(const FString&)
{
    FMRDisplayTrace Trace;
    Trace.Add(0,FVector::ZeroVector);
    for(int32 I=0;I<100;I++)Trace.Add(0,FVector(100,0,0));
    TestEqual(TEXT("paused/repeated sample cannot fabricate movement"),Trace.Points.Num(),1);
    Trace.Add(.1,FVector(100,0,0));
    TestTrue(TEXT("actual adjacent movement connects"),Trace.Points.Last().Connected);
    Trace.Add(.2,FVector(10000,0,0));
    TestFalse(TEXT("teleport does not draw a bridge"),Trace.Points.Last().Connected);
    Trace.Reset();Trace.Add(0,FVector::ZeroVector,true);Trace.Add(.5,FVector(100,0,0),true);
    TestTrue(TEXT("delivered adjacent poses connect"),Trace.Points.Last().Connected);
    Trace.Add(10,FVector(2000,0,0),true);
    TestFalse(TEXT("radio gap is not invented as a known path"),Trace.Points.Last().Connected);
    Trace.Reset();
    for(int32 I=0;I<20000;I++)Trace.Add(I*.1,FVector(I*20,0,0));
    TestTrue(TEXT("long mission has bounded storage"),Trace.Points.Num()<=FMRDisplayTrace::MaximumPoints);
    TestEqual(TEXT("retains latest physical point"),Trace.Points.Last().Position.X,399980.);
    const int32 Before=Trace.Points.Num();Trace.Add(0,FVector::ZeroVector);
    TestEqual(TEXT("old report cannot rewind trace"),Trace.Points.Num(),Before);
    Trace.Reset();TestEqual(TEXT("reset clears previous episode"),Trace.Points.Num(),0);
    TestEqual(TEXT("opaque ID produces stable color"),MRDisplayColor(TEXT("renamed/rescuer")),MRDisplayColor(TEXT("renamed/rescuer")));
    return true;
}
#endif
