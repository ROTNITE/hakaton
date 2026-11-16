#include "MRUrbanTerrain.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRRoadCavityShape,"MetaRescue.Environment.RoadCavityShape",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRRoadCavityShape::RunTest(const FString&)
{
    FMRRoadCavity Cavity;Cavity.Along=FVector(0,1,0);Cavity.AlongCm=650;Cavity.AcrossCm=400;
    TestEqual(TEXT("the road's failed support is two metres lower at its core"),Cavity.DropCm(FVector::ZeroVector),200.);
    TestEqual(TEXT("intact support beyond the failure stays level"),Cavity.DropCm(FVector(1000,1000,0)),0.);
    TestTrue(TEXT("the failure follows the actual road's heading"),Cavity.DropCm(FVector(0,550,0))>Cavity.DropCm(FVector(550,0,0)));
    for(int32 Degrees=0;Degrees<360;Degrees+=5)
    {
        const double A=FMath::DegreesToRadians(double(Degrees));
        const FVector Outside(FMath::Cos(A)*800,FMath::Sin(A)*800,0);
        TestEqual(TEXT("bounded damage cannot excavate a remote parcel"),Cavity.DropCm(Outside),0.);
    }
    return true;
}
#endif
