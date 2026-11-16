#include "MRUrbanWater.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRHydraulicBlueprint,"MetaRescue.Environment.HydraulicBlueprint",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRHydraulicBlueprint::RunTest(const FString&)
{
    TSharedPtr<FJsonObject> Source;
    const FString Text=TEXT(R"({"format":"metarescue.hydrology.v1","boundary":"river_fed_retention_basin","cell_m":5,"origin_m":[-105,0],"width":321,"height":300,"initial_stage_m":0.05,"storm_stage_m":2.8,"rise_seconds":70,"drain_capacity_m3_s":0.025,"basin":{"min":[-99,24,-7.2],"max":[-63,62,0.05]}})");
    if(!TestTrue(TEXT("hydraulic fixture parses"),FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Source)))return false;
    TestTrue(TEXT("1500m city plus the actual basin fits the bounded profile"),FMRUrbanWater::Validate(Source,150));
    Source->SetNumberField(TEXT("width"),320);
    TestFalse(TEXT("a field that cuts off the east edge is rejected"),FMRUrbanWater::Validate(Source,150));
    Source->SetNumberField(TEXT("width"),384);Source->SetNumberField(TEXT("height"),384);
    TestFalse(TEXT("the total allocation cap is enforced"),FMRUrbanWater::Validate(Source,150));
    Source->SetNumberField(TEXT("width"),71);Source->SetNumberField(TEXT("height"),50);
    TestTrue(TEXT("250m city with the same source"),FMRUrbanWater::Validate(Source,25));
    Source->SetNumberField(TEXT("rise_seconds"),0);
    TestFalse(TEXT("an instantaneous boundary jump is outside this forcing profile"),FMRUrbanWater::Validate(Source,25));
    Source->SetNumberField(TEXT("rise_seconds"),70);Source->SetBoolField(TEXT("width"),true);
    TestFalse(TEXT("boolean grid dimensions are not integers"),FMRUrbanWater::Validate(Source,25));
    Source->SetNumberField(TEXT("width"),71);Source->SetNumberField(TEXT("tailwater_stage_m"),0);
    Source->SetArrayField(TEXT("outlet_edges"),{MakeShared<FJsonValueString>(TEXT("east")),MakeShared<FJsonValueString>(TEXT("north")),MakeShared<FJsonValueString>(TEXT("south"))});
    TestTrue(TEXT("declared receiving floodplain edges are accepted"),FMRUrbanWater::Validate(Source,25));
    Source->SetArrayField(TEXT("outlet_edges"),{MakeShared<FJsonValueString>(TEXT("teleport"))});
    TestFalse(TEXT("unmodelled outlets are rejected"),FMRUrbanWater::Validate(Source,25));
    return true;
}
#endif
