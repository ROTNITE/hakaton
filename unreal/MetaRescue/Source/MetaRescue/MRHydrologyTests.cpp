#include "MRHydrology.h"
#include <limits>
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRWaterConservation,"MetaRescue.Environment.WaterConservation",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRWaterBarriers,"MetaRescue.Environment.WaterBarriers",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRWaterBoundary,"MetaRescue.Environment.WaterBoundaryAndDrain",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRWaterOpenOutlet,"MetaRescue.Environment.WaterOpenOutlet",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)

bool FMRWaterConservation::RunTest(const FString&)
{
    FMRHydrology Grid;TArray<double> Bed,Water;TBitArray<> Solid(false,40);
    Bed.Init(0,40);Water.Init(0,40);for(int32 I=0;I<10;++I)Water[I]=2;
    if(!TestTrue(TEXT("valid finite storage grid"),Grid.Configure(10,4,5,Bed,Solid,Water)))return false;
    const double Volume=Grid.VolumeM3();
    TestTrue(TEXT("a wet front can advance into dry cells"),Grid.Advance(20));
    TestTrue(TEXT("water moves beyond the original wet patch"),Grid.DepthM(Grid.Index(5,2))>.02);
    TestTrue(TEXT("closed-domain volume is conserved"),FMath::Abs(Grid.VolumeM3()-Volume)<1.e-7);
    TestTrue(TEXT("ledger closes"),FMath::Abs(Grid.BalanceErrorM3())<1.e-7);
    for(int32 I=0;I<40;++I)TestTrue(TEXT("wet/dry update never creates negative depth"),Grid.DepthM(I)>=0);
    Grid.Reset();
    TestEqual(TEXT("reset restores the initial front"),Grid.DepthM(Grid.Index(5,2)),0.);
    TestEqual(TEXT("reset restores time"),Grid.Time(),0.);
    TestTrue(TEXT("reset restores volume"),FMath::Abs(Grid.VolumeM3()-Volume)<1.e-8);
    return true;
}

bool FMRWaterBarriers::RunTest(const FString&)
{
    FMRHydrology Grid;TArray<double> Bed={0,.4,.8,1.2,1.6},Water={1.6,1.2,.8,.4,0};
    TBitArray<> Solid(false,5);
    if(!TestTrue(TEXT("sloping bed"),Grid.Configure(5,1,5,Bed,Solid,Water)))return false;
    TestTrue(TEXT("advance a lake at rest"),Grid.Advance(10));
    for(int32 I=0;I<5;++I)TestTrue(TEXT("hydrostatic equilibrium is retained"),FMath::Abs(Grid.DepthM(I)-Water[I])<1.e-7);
    Bed={0,0,0,0,0};Water={2,2,0,0,0};
    Grid.Configure(5,1,5,Bed,Solid,Water);Grid.SetCrestX(1,0,3.4,true);
    TestTrue(TEXT("closed bank advance"),Grid.Advance(15));
    TestEqual(TEXT("a high bank prevents flooding"),Grid.DepthM(2),0.);
    Grid.SetCrestX(1,0,0);TestTrue(TEXT("opened gate advance"),Grid.Advance(15));
    TestTrue(TEXT("water passes through the opened gate"),Grid.DepthM(2)>.05);
    TestTrue(TEXT("gate opening does not create water"),FMath::Abs(Grid.BalanceErrorM3())<1.e-7);
    Grid.Reset();Grid.Advance(15);
    TestEqual(TEXT("reset restores the authored closed bank"),Grid.DepthM(2),0.);
    Solid[2]=true;Grid.Configure(5,1,5,Bed,Solid,Water);Grid.Advance(20);
    TestEqual(TEXT("a solid building cell remains impermeable"),Grid.DepthM(2),0.);
    TestEqual(TEXT("a building wall blocks the downstream street"),Grid.DepthM(3),0.);
    return true;
}

bool FMRWaterBoundary::RunTest(const FString&)
{
    FMRHydrology Grid;TArray<double> Bed={0,0,3.4},Water={0,0,0};TBitArray<> Solid(false,3);
    Grid.Configure(3,1,5,Bed,Solid,Water);Grid.SetDrain(1,.1);
    // A rising flood, not an instantaneous 2.8m dam break. The latter has
    // momentum and can run up onto a bank above its eventual static stage.
    // Never make the bank impermeable merely because it belongs to the base.
    bool Healthy=true;
    for(int32 I=1;I<=140;++I)
    {Grid.SetBoundaryStage(0,I*.02);Healthy=Grid.Advance(.5)&&Healthy;}
    TestTrue(TEXT("rising flood supplied from an explicit boundary"),Healthy);
    TestTrue(TEXT("inflow is accounted for"),Grid.AddedM3()>0);
    TestTrue(TEXT("outflow and drains are accounted for"),Grid.RemovedM3()>0);
    AddInfo(FString::Printf(TEXT("boundary stages %.9f %.9f %.9f; raised depth %.12f; balance error %.12f"),
        Grid.StageM(0),Grid.StageM(1),Grid.StageM(2),Grid.DepthM(2),Grid.BalanceErrorM3()));
    TestTrue(TEXT("raised base stays dry from geometry, without a protected-area exception"),Grid.DepthM(2)==0);
    TestTrue(TEXT("open-system water balance closes"),FMath::Abs(Grid.BalanceErrorM3())<1.e-7);
    const double Before=Grid.VolumeM3();Grid.SetBed(1,-1);
    TestEqual(TEXT("road subsidence changes storage elevation without deleting water"),Grid.VolumeM3(),Before);
    TestFalse(TEXT("nonfinite boundary rejected"),Grid.SetBoundaryStage(0,std::numeric_limits<double>::quiet_NaN()));
    return true;
}

bool FMRWaterOpenOutlet::RunTest(const FString&)
{
    FMRHydrology Grid;TArray<double> Bed,Water;TBitArray<> Solid(false,90);
    Bed.Init(0,90);Water.Init(0,90);
    for(int32 Y=0;Y<3;++Y)for(int32 X=0;X<3;++X){Bed[Y*30+X]=-7.2;Water[Y*30+X]=7.25;}
    if(!TestTrue(TEXT("basin and receiving street"),Grid.Configure(30,3,5,Bed,Solid,Water)))return false;
    bool Healthy=true;
    for(int32 Step=1;Step<=1500;++Step)
    {
        for(int32 Y=0;Y<3;++Y)
        {Grid.SetBoundaryStage(Grid.Index(0,Y),.05+2.75*FMath::Min(1.,Step*.1/70));Grid.SetBoundaryStage(Grid.Index(29,Y),0);}
        Healthy=Grid.Advance(.1)&&Healthy;
    }
    TestTrue(TEXT("rising reservoir and open receiving boundary remain healthy"),Healthy);
    TestTrue(TEXT("a wet front reaches the receiving street"),Grid.DepthM(Grid.Index(15,1))>.1);
    TestTrue(TEXT("water really leaves the domain and is accounted for"),Grid.RemovedM3()>1);
    TestTrue(TEXT("open boundaries conserve the complete supplied/removed ledger"),FMath::Abs(Grid.BalanceErrorM3())<1.e-6);
    for(int32 Y=0;Y<3;++Y)TestEqual(TEXT("receiving tailwater is enforced"),Grid.DepthM(Grid.Index(29,Y)),0.);
    return true;
}
#endif
