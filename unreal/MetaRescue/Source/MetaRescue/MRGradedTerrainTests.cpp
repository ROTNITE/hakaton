#include "MRGradedTerrain.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRBaseTerrain,"MetaRescue.Environment.GradedBaseTerrain",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRBaseTerrain::RunTest(const FString&)
{
    TSharedPtr<FJsonObject> Source;
    const FString Text=TEXT(R"({"format":"metarescue.graded-terrain.v1","base":{"min":[0,0],"max":[71,42]},"base_elevation_m":3.4,"grade_width_m":45,"ramp":{"min":[71,4],"max":[116,16]},"pads":[{"min":[120,20],"max":[130,30],"elevation_m":0.8}],"depressions":[{"min":[-99,24],"max":[-63,62],"elevation_m":-7.2}]})");
    if(!TestTrue(TEXT("terrain fixture parses"),FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Source)))return false;
    FMRGradedTerrain Terrain;
    if(!TestTrue(TEXT("public initial profile accepted"),Terrain.Read(Source)))return false;
    TestEqual(TEXT("base has real elevation"),Terrain.Height(FVector(2000,2000,0)),340.);
    TestTrue(TEXT("the northern street follows the same 45m grade"),FMath::Abs(Terrain.Height(FVector(5000,5000,0))-340.*(1.-8./45))<1.e-8);
    TestEqual(TEXT("distant city stays at its original datum"),Terrain.Height(FVector(15000,15000,0)),0.);
    TestEqual(TEXT("basin has an open seven metre depression"),Terrain.Height(FVector(-8100,4300,0)),-720.);
    for(int32 X=7100;X<=11600;X+=100)
        TestTrue(TEXT("ramp agrees with the public metre model"),FMath::Abs(Terrain.Height(FVector(X,1000,0))-340.*(11600-X)/4500)<1.e-8);
    TestEqual(TEXT("foundation feather has no hard one-metre ledge"),Terrain.Height(FVector(13050,2500,0)),40.);
    Source->SetNumberField(TEXT("grade_width_m"),44);
    TestFalse(TEXT("a ramp with inconsistent physical extent is rejected"),Terrain.Read(Source));
    TestEqual(TEXT("failed reads do not retain partial geometry"),Terrain.Height(FVector(2000,2000,0)),0.);
    TestTrue(TEXT("legacy missing terrain remains supported"),Terrain.Read(nullptr));
    TestFalse(TEXT("legacy profile is disabled"),Terrain.IsEnabled());
    return true;
}
#endif
