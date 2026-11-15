#include "MRCoreExpressions.h"
#include "MRCoreValues.h"
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS
using namespace MRCoreValues;
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FMRPredicateTest,"MetaRescue.Core.Predicates",
    EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FMRPredicateTest::RunTest(const FString&)
{
    const auto Compare=[](const FString& Op,const Value& Left,const Value& Right)
    {return Obj({{TEXT("op"),Str(Op)},{TEXT("left"),Left},{TEXT("right"),Right}});};
    const auto Path=[](const FString& Name){return Json(Obj({{TEXT("path"),Str(Name)}}));};
    const auto Literal=[](const Value& Value){return Json(Obj({{TEXT("value"),Value}}));};
    const auto Missing=Compare(TEXT("eq"),Path(TEXT("mission.missing")),Literal(Bool(true)));
    TestFalse(TEXT("missing evidence remains unknown"),MRCoreExpressions::Evaluate(Missing,Obj()).IsValid());
    const auto Bad=Compare(TEXT("ge"),Literal(Bool(true)),Literal(Num(1)));
    TestFalse(TEXT("boolean is not a number"),MRCoreExpressions::Validate(Bad));
    const auto Private=Compare(TEXT("eq"),Path(TEXT("truth.targets")),Literal(Num(1)));
    TestFalse(TEXT("hidden roots rejected"),MRCoreExpressions::Validate(Private));
    const auto And=Obj({{TEXT("op"),Str(TEXT("and"))},{TEXT("args"),Arr({Literal(Bool(false)),Json(Missing)})}});
    TestFalse(TEXT("false and unknown is false"),MRCoreExpressions::Evaluate(And,Obj())->AsBool());
    const auto Sum=Obj({{TEXT("op"),Str(TEXT("sum"))},{TEXT("items"),Path(TEXT("targets"))},
        {TEXT("var"),Str(TEXT("entry"))},{TEXT("select"),Path(TEXT("$entry.priority"))}});
    const auto Total=Compare(TEXT("eq"),Json(Sum),Literal(Num(4)));
    TestTrue(TEXT("typed aggregate is valid"),MRCoreExpressions::Validate(Total));
    const auto Context=Obj({{TEXT("targets"),Arr({Json(Obj({{TEXT("priority"),Num(1)}})),Json(Obj({{TEXT("priority"),Num(3)}}))})}});
    const auto Result=MRCoreExpressions::Evaluate(Total,Context);
    TestTrue(TEXT("sum reads delivered targets"),Result&&Result->AsBool());
    Object Nested=Obj({{TEXT("value"),Bool(true)}});
    for(int32 I=0;I<18;I++)Nested=Obj({{TEXT("op"),Str(TEXT("not"))},{TEXT("arg"),Json(Nested)}});
    TestFalse(TEXT("depth budget"),MRCoreExpressions::Validate(Nested));
    return true;
}
#endif
