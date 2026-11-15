#if WITH_DEV_AUTOMATION_TESTS
#include "MRCoreClock.h"
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRClockTest,"MetaRescue.Core.ClockBoundaries",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRClockTest::RunTest(const FString&)
{
    FMRCoreClock Clock;TArray<double> Boundaries={.123,.246,.5,1.,1.123,1.246,1.5,2.};
    TSet<double> Reached;
    for(int32 Step=0;Step<3;Step++)
    {
        Clock.BeginStep(2.005);int32 Guard=0;
        while(!Clock.StepFinished()&&++Guard<100)
        {
            const double Dt=Clock.NextDelta(Boundaries);
            TestTrue(TEXT("valid execution delta"),Dt>0&&Dt<=FMRCoreClock::Quantum);
            TestTrue(TEXT("advance after physics"),Clock.Advance(Dt));
            for(double At:Boundaries)if(FMath::Abs(Clock.Time()-At)<1.e-12)Reached.Add(At);
        }
        TestTrue(TEXT("external step terminates"),Guard<100);
        TestTrue(TEXT("exact external/fractional endpoint"),FMath::Abs(Clock.Time()-(Step<2?Step+1.:2.005))<1.e-12);
    }
    TestEqual(TEXT("every known boundary reached"),Reached.Num(),Boundaries.Num());
    const double Before=Clock.Time();TestFalse(TEXT("invalid negative delta rejected"),Clock.Advance(-.1));
    TestEqual(TEXT("invalid delta/getters leave time"),Clock.Time(),Before);
    Clock.Reset();TestEqual(TEXT("reset"),Clock.Time(),0.);return true;
}
#endif
