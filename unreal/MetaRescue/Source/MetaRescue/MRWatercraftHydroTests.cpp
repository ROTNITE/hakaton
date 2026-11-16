#include "MRWatercraftHydro.h"
#include "MRCoreValues.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
using namespace MRCoreValues;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRWatercraftDisplacement,"MetaRescue.Environment.WatercraftDisplacement",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRWatercraftDisplacement::RunTest(const FString&)
{
    // Eight rectangular tanks give an exact reference waterplane of 2.4m2.
    // This checks units and loading independently of the catamaran geometry.
    TArray<Value> X,Y,Rows;
    for(int32 I=0;I<8;++I)
    {
        X.Add(Num(-1.5+(I%4)));Y.Add(Num(I<4?-.6:.6));TArray<Value> Curve;
        for(int32 J=0;J<=10;++J)Curve.Add(Num(J*.05*.3));Rows.Add(Arr(Curve));
    }
    auto Data=Obj({{TEXT("format"),Str(TEXT("metarescue.watercraft-hydrostatics.v1"))},
        {TEXT("asset_id"),Str(TEXT("RescueWaterCatamaran-r1"))},{TEXT("model_source_sha256"),Str(FString::ChrN(64,'0'))},
        {TEXT("height_step_m"),Num(.05)},{TEXT("sealed_top_m"),Num(.5)},
        {TEXT("dry_mass_kg"),Num(475)},{TEXT("person_and_stretcher_mass_kg"),Num(98)},
        {TEXT("payload_limit_kg"),Num(130)},{TEXT("body_origin_above_keel_m"),Num(.45)},
        {TEXT("cargo_deck_above_keel_m"),Num(1.03)},{TEXT("battery_wh"),Num(3000)},
        {TEXT("maximum_jet_thrust_n"),Num(900)},{TEXT("maximum_speed_m_s"),Num(2.8)},
        {TEXT("section_x_m"),Arr(X)},{TEXT("section_y_m"),Arr(Y)},{TEXT("section_volume_m3"),Arr(Rows)}});
    FMRWatercraftHydro Hull;
    if(!TestTrue(TEXT("bounded measured volume table"),Hull.Read(Data)))return false;
    TestEqual(TEXT("dry hull cannot displace negative water"),Hull.DisplacementM3(-1),0.);
    TestTrue(TEXT("fully submerged volume is capped at the sealed hull"),FMath::Abs(Hull.DisplacementM3(2)-1.2)<1.e-12);
    const auto Empty=Hull.EquilibriumDraftM(475),Loaded=Hull.EquilibriumDraftM(573);
    if(!TestTrue(TEXT("rated load has a floating equilibrium"),Empty.IsSet()&&Loaded.IsSet()))return false;
    TestTrue(TEXT("Archimedes equilibrium uses kg and m3"),FMath::Abs(Empty.GetValue()-475./2400)<1.e-10);
    TestTrue(TEXT("cargo changes draft by its displaced water volume"),FMath::Abs(Loaded.GetValue()-Empty.GetValue()-98./2400)<1.e-10);
    TestFalse(TEXT("a load beyond the sealed displacement has no fabricated target Z"),Hull.EquilibriumDraftM(1500).IsSet());
    auto Broken=Rows[0]->AsArray();Broken[4]=Num(.8);Rows[0]=Arr(Broken);Data->SetArrayField(TEXT("section_volume_m3"),Rows);
    TestFalse(TEXT("nonmonotone measured curves fail closed"),Hull.Read(Data));
    TestFalse(TEXT("failed data reads invalidate the profile"),Hull.IsValid());
    return true;
}
#endif
