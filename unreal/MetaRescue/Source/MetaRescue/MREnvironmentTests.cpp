#if WITH_DEV_AUTOMATION_TESTS
#include "MREnvironment.h"
#include "Misc/AutomationTest.h"

namespace
{
TArray<FMREventSite> Sites()
{
    TArray<FMREventSite> Out;
    for(int32 Kind=0;Kind<8;Kind++)for(int32 I=0;I<20;I++)
    {
        FMREventSite S;S.Kind=EMRDisturbance(Kind);S.Id=FString::Printf(TEXT("%d_%d"),Kind,I);
        S.Position=FVector(5000+I*500,6000,4);const auto C=FMRDistrictEnvironment::Cell(S.Position);
        for(int32 X=-3;X<=3;X++)for(int32 Y=-3;Y<=3;Y++)S.Cells.Add(C+FIntPoint(X,Y));
        Out.Add(S);
    }
    return Out;
}
FMRDisturbance At(EMRDisturbance Kind,double Time)
{
    FMRDisturbance E;E.Id=MRDisturbanceName(Kind);E.Kind=Kind;E.Time=Time;E.Cells.Add(FIntPoint(10,10));return E;
}
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRZeroEvents,"MetaRescue.Environment.ZeroAndFullProbability",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRZeroEvents::RunTest(const FString&)
{
    FMRDistrictEnvironment E;for(float& P:E.Probabilities)P=0;E.Generate(Sites());
    TestEqual(TEXT("zero disables every event including propagation"),E.Tape.Num(),0);
    for(float& P:E.Probabilities)P=100;E.Generate(Sites());
    for(int32 Kind=0;Kind<8;Kind++)
    {int32 Count=0;for(const auto& Row:E.Tape)if(int32(Row.Kind)==Kind&&!Row.bPropagation&&Row.Rejection.IsEmpty())Count++;
     TestEqual(FString::Printf(TEXT("15 primary events kind %d"),Kind),Count,15);}
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRReplay,"MetaRescue.Environment.ReplayAndWindowBoundaries",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRReplay::RunTest(const FString&)
{
    FMRDistrictEnvironment A,B;for(float& P:A.Probabilities)P=100;for(float& P:B.Probabilities)P=100;
    A.Generate(Sites());B.Generate(Sites());TestEqual(TEXT("same length"),A.Tape.Num(),B.Tape.Num());
    int32 Growth=0;
    for(int32 I=0;I<A.Tape.Num();I++)
    {TestEqual(TEXT("time"),A.Tape[I].Time,B.Tape[I].Time);TestEqual(TEXT("id"),A.Tape[I].Id,B.Tape[I].Id);
     TestTrue(TEXT("same geometry"),A.Tape[I].Cells==B.Tape[I].Cells);
     TestTrue(TEXT("30 second windows"),FMath::Fmod(A.Tape[I].Time,30)==0);Growth+=A.Tape[I].bPropagation;}
    TestTrue(TEXT("conditional propagation generated"),Growth>0);
    TestEqual(TEXT("nothing before 30"),A.Advance(29.99).Num(),0);
    TestTrue(TEXT("boundary applies"),A.Advance(30).Num()>0);
    A.Advance(480);B.Advance(480);TestEqual(TEXT("large steps cannot skip events"),A.Applied.Num(),B.Applied.Num());
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRConsequences,"MetaRescue.Environment.ConsequencesAndExpiry",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRConsequences::RunTest(const FString&)
{
    FMRDistrictEnvironment E;const FVector P=FMRDistrictEnvironment::Center(FIntPoint(10,10));
    E.Tape={At(EMRDisturbance::Mud,30),At(EMRDisturbance::RoadDamage,30),At(EMRDisturbance::Smoke,30),At(EMRDisturbance::LowVisibility,30),At(EMRDisturbance::Flood,30)};
    E.Advance(30);TestEqual(TEXT("mud dominates road cost"),E.Cost(P),2.25f);
    TestTrue(TEXT("independent visibility effects multiply"),FMath::IsNearlyEqual(E.Visibility(P),.52f*.62f));
    E.Advance(50);TestTrue(TEXT("shallow water still traversable"),!E.Unsafe(P));
    E.Advance(70);TestTrue(TEXT("deep water unsafe"),E.Unsafe(P));
    TestTrue(TEXT("water rises"),E.Depth(P)>25);E.Advance(120);
    TestTrue(TEXT("smoke expires exactly at 90 sec"),FMath::IsNearlyEqual(E.Visibility(P),.62f));
    E.Advance(130);TestEqual(TEXT("fog expires at 100 sec"),E.Visibility(P),1.f);
    TestEqual(TEXT("persistent water caps at 42 cm"),E.Depth(P),42.f);
    E.Advance(480);TestEqual(TEXT("permanent mud remains"),E.Cost(P),2.25f);
    FMRDistrictEnvironment Fire;Fire.Tape={At(EMRDisturbance::Fire,30)};Fire.Advance(99.99);
    TestEqual(TEXT("fire smoke before 70 sec"),Fire.Visibility(P),.52f);
    const int32 Before=Fire.Revision;Fire.Advance(100);
    TestEqual(TEXT("fire smoke ends at 70 sec"),Fire.Visibility(P),1.f);
    TestTrue(TEXT("visibility expiry invalidates surface cache"),Fire.Revision>Before);
    TestTrue(TEXT("fire remains blocking after its smoke"),Fire.Unsafe(P));return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRProtected,"MetaRescue.Environment.ProtectedBaseAndExhaustion",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRProtected::RunTest(const FString&)
{
    auto S=Sites();for(auto& Site:S)Site.Position=FVector(-700,1000,0);
    FMRDistrictEnvironment E;for(float& P:E.Probabilities)P=100;E.Generate(S);
    TestTrue(TEXT("rejected attempts retained"),E.Tape.Num()>0);E.Advance(480);
    TestEqual(TEXT("protected base never changes"),E.Applied.Num(),0);
    E.Generate({});TestTrue(TEXT("empty catalog explicitly rejected"),E.Tape.Num()>0);return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRExplicitExpiry,"MetaRescue.Environment.CoreExpiryAndSpatialLookup",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRExplicitExpiry::RunTest(const FString&)
{
    FMRDistrictEnvironment E;const FVector P=FMRDistrictEnvironment::Center({10,10});
    auto Mud=At(EMRDisturbance::Mud,.123);Mud.ExpiresAt=2.005;
    auto Smoke=At(EMRDisturbance::Smoke,.246);Smoke.ExpiresAt=1.123;Smoke.VisibilityExpiresAt=1.123;Smoke.VisibilityTopCm=600;
    auto Fire=At(EMRDisturbance::Fire,.3);Fire.Cells={FIntPoint(11,10)};Fire.VisibilityExpiresAt=1.246;
    E.Tape={Mud,Smoke,Fire};E.Advance(.2);
    TestEqual(TEXT("active mud cost"),E.Cost(P),2.25f);TestTrue(TEXT("indexed id lookup"),E.FindApplied(Mud.Id)!=nullptr);
    E.Advance(.5);TestEqual(TEXT("visible ground"),E.Visibility(P),MRDistrictSettings::SmokeQuality);
    TestEqual(TEXT("high point still sees adjacent fire smoke"),E.Visibility(P+FVector(0,0,800)),MRDistrictSettings::SmokeQuality);
    E.Advance(1.246);TestEqual(TEXT("both visibility expiries apply"),E.Visibility(P),1.f);
    TestTrue(TEXT("fire hazard persists after smoke"),E.Unsafe(P+FVector(500,0,0)));
    E.Advance(2.005);TestEqual(TEXT("mud expires exactly"),E.Cost(P),1.f);
    TestFalse(TEXT("expired effect absent from active lookup"),E.HasEffect(EMRDisturbance::Mud,P));
    E.Mode=TEXT("static");E.Generate({});TestTrue(TEXT("reset clears indexed history"),E.FindApplied(Mud.Id)==nullptr);
    return true;
}
#endif
