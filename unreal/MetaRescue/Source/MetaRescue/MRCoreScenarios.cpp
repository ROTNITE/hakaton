#include "MRCoreRuntime.h"
#include "MRCoreJson.h"
#include "MRCoreExpressions.h"
#include "MRCoreValues.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"

using namespace MRCoreValues;

namespace
{
bool ReadIds(const Object& Source,const FString& Key,TArray<FString>& Ids)
{
    if(!Is(Source,Key,EJson::Array))return false;
    for(const auto& Item:Source->GetArrayField(Key))
    {
        if(Item->Type!=EJson::String||Item->AsString().IsEmpty()||Ids.Contains(Item->AsString()))return false;
        Ids.Add(Item->AsString());
    }
    Ids.Sort();
    return true;
}

bool Contains(const Object& Source,const FString& Key,const FString& Item)
{
    if(!Is(Source,Key,EJson::Array))return false;
    return Source->GetArrayField(Key).ContainsByPredicate([&](const Value& V)
        {return V->Type==EJson::String&&V->AsString()==Item;});
}

Object Declaration(const TMap<FString,Object>& Catalog,const Object& Configuration,const FString& Id)
{
    if(auto Known=Catalog.FindRef(Id))return Known;
    auto Synth=Field(Configuration,TEXT("synthesized_scenario"));
    if(Synth&&Synth->Type==EJson::Object&&Text(Synth->AsObject(),TEXT("id"))==Id)return Synth->AsObject();
    return nullptr;
}

Object RoleDefinition(const Object& Scenario,const FString& Role)
{
    if(!Is(Scenario,TEXT("roles"),EJson::Array))return nullptr;
    for(const auto& V:Scenario->GetArrayField(TEXT("roles")))
        if(V->Type==EJson::Object&&Text(V->AsObject(),TEXT("id"))==Role)return V->AsObject();
    return nullptr;
}

bool Member(const Object& Selection,const Object& Declaration,const FString& Agent,const FString& Role)
{
    if(Role.IsEmpty()||!RoleDefinition(Declaration,Role))return false;
    if(!Is(Selection,TEXT("scenario_participants"),EJson::Object))return true;
    return Contains(Selection->GetObjectField(TEXT("scenario_participants")),Text(Declaration,TEXT("id")),Agent);
}

// Validate the parameter vocabulary declared by the bundled profiles. Foreign
// declarations use the same scalar/record subset and may add optional metadata.
bool ParametersMatch(const Object& Schema,const Value& Data,int32 Depth=0)
{
    if(!Schema||!Data||Depth>8)return false;
    const FString Type=Text(Schema,TEXT("type"));
    if(Type==TEXT("object"))
    {
        if(Data->Type!=EJson::Object)return false;
        const auto Fields=Data->AsObject();
        if(Is(Schema,TEXT("required"),EJson::Array))for(const auto& Key:Schema->GetArrayField(TEXT("required")))
            if(Key->Type!=EJson::String||!Fields->HasField(Key->AsString()))return false;
        const auto Properties=Field(Schema,TEXT("properties"));
        for(const auto& Item:Fields->Values)
        {
            auto ItemSchema=Properties&&Properties->Type==EJson::Object?Field(Properties->AsObject(),FString(*Item.Key)):nullptr;
            if(ItemSchema)
            {
                if(ItemSchema->Type!=EJson::Object||!ParametersMatch(ItemSchema->AsObject(),Item.Value,Depth+1))return false;
            }
            else if(Is(Schema,TEXT("additionalProperties"),EJson::Boolean)&&!Schema->GetBoolField(TEXT("additionalProperties")))return false;
        }
        return true;
    }
    if(Type==TEXT("array"))
    {
        if(Data->Type!=EJson::Array)return false;
        const auto& Items=Data->AsArray();
        if(Is(Schema,TEXT("minItems"),EJson::Number)&&Items.Num()<Schema->GetNumberField(TEXT("minItems")))return false;
        if(Is(Schema,TEXT("maxItems"),EJson::Number)&&Items.Num()>Schema->GetNumberField(TEXT("maxItems")))return false;
        if(Is(Schema,TEXT("items"),EJson::Object))for(const auto& V:Items)
            if(!ParametersMatch(Schema->GetObjectField(TEXT("items")),V,Depth+1))return false;
        return true;
    }
    if(Type==TEXT("string"))return Data->Type==EJson::String&&
        (!Is(Schema,TEXT("minLength"),EJson::Number)||Data->AsString().Len()>=Schema->GetNumberField(TEXT("minLength")));
    if(Type==TEXT("number")||Type==TEXT("integer"))
    {
        if(Data->Type!=EJson::Number)return false;
        const double N=Data->AsNumber();
        return FMath::IsFinite(N)&&(Type!=TEXT("integer")||N==FMath::FloorToDouble(N))&&
            (!Is(Schema,TEXT("minimum"),EJson::Number)||N>=Schema->GetNumberField(TEXT("minimum")))&&
            (!Is(Schema,TEXT("maximum"),EJson::Number)||N<=Schema->GetNumberField(TEXT("maximum")));
    }
    return (Type==TEXT("boolean")&&Data->Type==EJson::Boolean)||(Type==TEXT("null")&&Data->Type==EJson::Null);
}

bool DeclaredShape(const Object& Scenario)
{
    if(Text(Scenario,TEXT("id")).IsEmpty()||Text(Scenario,TEXT("version")).IsEmpty()||Text(Scenario,TEXT("title")).IsEmpty())return false;
    for(const FString& Key:{TEXT("game_model"),TEXT("applicability")})if(!Is(Scenario,Key,EJson::Object))return false;
    const auto Applicability=Scenario->GetObjectField(TEXT("applicability"));
    for(const FString& Key:{TEXT("entry"),TEXT("continuation"),TEXT("exit"),TEXT("emergency_exit")})
    {
        if(!Is(Applicability,Key,EJson::Array))return false;
        for(const auto& V:Applicability->GetArrayField(Key))
            if(V->Type!=EJson::Object||!MRCoreExpressions::Validate(V->AsObject()))return false;
    }
    for(const FString& Key:{TEXT("roles"),TEXT("objectives"),TEXT("constraints")})
    {
        if(!Is(Scenario,Key,EJson::Array))return false;
        TSet<FString> Ids;
        for(const auto& V:Scenario->GetArrayField(Key))
        {
            if(V->Type!=EJson::Object)return false;
            const auto Entry=V->AsObject();
            const FString Id=Text(Entry,TEXT("id"));
            if(Id.IsEmpty()||Ids.Contains(Id))return false;
            Ids.Add(Id);
            if(Key==TEXT("constraints")&&(!Is(Entry,TEXT("predicate"),EJson::Object)||
                !MRCoreExpressions::Validate(Entry->GetObjectField(TEXT("predicate")))))return false;
            if(Key==TEXT("roles"))
            {
                TArray<FString> Caps;
                if(!ReadIds(Entry,TEXT("required_capabilities"),Caps)||!Is(Entry,TEXT("minimum"),EJson::Number)||
                    !Is(Entry,TEXT("maximum"),EJson::Number))return false;
                const double Min=Entry->GetNumberField(TEXT("minimum")),Max=Entry->GetNumberField(TEXT("maximum"));
                if(Min<0||Max<Min||Max>256||Min!=FMath::FloorToDouble(Min)||Max!=FMath::FloorToDouble(Max))return false;
            }
        }
    }
    for(const FString& Key:{TEXT("allowed_actions"),TEXT("transition_targets"),TEXT("metrics")})
    {TArray<FString> Items;if(!ReadIds(Scenario,Key,Items))return false;}
    return true;
}

bool BoundedProgram(const Object& Scenario,const Object& Parameters)
{
    const auto Extension=Field(Scenario,TEXT("execution_rules"));
    if(!Extension||Extension->Type!=EJson::Object||Text(Extension->AsObject(),TEXT("grammar"))!=TEXT("metaevolution.fsm.v1"))return true;
    const auto Rules=Extension->AsObject();
    if(!Is(Rules,TEXT("states"),EJson::Array)||!Is(Rules,TEXT("deadline_seconds"),EJson::Number))return false;
    const auto& States=Rules->GetArrayField(TEXT("states"));
    const double Deadline=Rules->GetNumberField(TEXT("deadline_seconds"));
    if(States.IsEmpty()||States.Num()>16||Deadline<=0||Deadline>86400)return false;
    TSet<FString> Ids;
    TArray<FString> Edges={Text(Rules,TEXT("initial_state"))};
    bool HasSuccess=false,HasFallback=false,HasCommand=false;
    for(const auto& V:States)
    {
        if(V->Type!=EJson::Object)return false;
        const auto State=V->AsObject();
        const FString Id=Text(State,TEXT("id")),Outcome=Text(State,TEXT("outcome"));
        if(Id.IsEmpty()||Ids.Contains(Id))return false;
        Ids.Add(Id);
        if(Outcome==TEXT("success")||Outcome==TEXT("safe_degradation"))
        {
            HasSuccess|=Outcome==TEXT("success");HasFallback|=Outcome==TEXT("safe_degradation");
            if(State->HasField(TEXT("commands"))||State->HasField(TEXT("transition"))||State->HasField(TEXT("timeout")))return false;
            continue;
        }
        if(!Outcome.IsEmpty()||!Is(State,TEXT("commands"),EJson::Array)||!Is(State,TEXT("transition"),EJson::Object)||
            !Is(State,TEXT("timeout"),EJson::Object))return false;
        const auto Transition=State->GetObjectField(TEXT("transition")),Timeout=State->GetObjectField(TEXT("timeout"));
        if(!Is(Transition,TEXT("success_when"),EJson::Object)||
            !MRCoreExpressions::Validate(Transition->GetObjectField(TEXT("success_when")),true)||!Is(Timeout,TEXT("seconds"),EJson::Number)||
            Timeout->GetNumberField(TEXT("seconds"))<=0||Timeout->GetNumberField(TEXT("seconds"))>Deadline)return false;
        Edges.Add(Text(Transition,TEXT("on_success")));Edges.Add(Text(Transition,TEXT("on_failure")));Edges.Add(Text(Timeout,TEXT("on_timeout")));
        const auto& Commands=State->GetArrayField(TEXT("commands"));
        if(Commands.Num()>8)return false;
        HasCommand|=!Commands.IsEmpty();
        for(const auto& Row:Commands)
        {
            if(Row->Type!=EJson::Object)return false;
            const auto Command=Row->AsObject();
            if(!RoleDefinition(Scenario,Text(Command,TEXT("role")))||!Contains(Scenario,TEXT("allowed_actions"),Text(Command,TEXT("action")))||
                !Is(Command,TEXT("parameters"),EJson::Object))return false;
            for(const auto& Binding:Command->GetObjectField(TEXT("parameters"))->Values)
                if(Is(Binding.Value->Type==EJson::Object?Binding.Value->AsObject():nullptr,TEXT("parameter"),EJson::String)&&
                    !Parameters->HasField(Text(Binding.Value->AsObject(),TEXT("parameter"))))return false;
        }
    }
    return HasSuccess&&HasFallback&&HasCommand&&!Edges.ContainsByPredicate([&](const FString& Id){return !Ids.Contains(Id);});
}
}

bool FMRCoreRuntime::LoadScenarios()
{
    FString Source;
    Object Library;
    if(!FFileHelper::LoadFileToString(Source,*(FPaths::ProjectContentDir()/TEXT("Scenario/core-scenarios-v1.json")))||
        !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Source),Library)||
        Text(Library,TEXT("format"))!=TEXT("metarescue.scenarios.v1")||!Is(Library,TEXT("scenarios"),EJson::Array))
    {UE_LOG(LogTemp,Error,TEXT("MR_CORE scenario catalogue is missing or invalid"));return false;}
    for(const auto& V:Library->GetArrayField(TEXT("scenarios")))
    {
        const auto Scenario=V->Type==EJson::Object?V->AsObject():nullptr;
        if(!DeclaredShape(Scenario)||ScenarioCatalog.Contains(Text(Scenario,TEXT("id"))))
        {UE_LOG(LogTemp,Error,TEXT("MR_CORE invalid scenario declaration"));return false;}
        ScenarioCatalog.Add(Text(Scenario,TEXT("id")),Scenario);
    }
    return ScenarioCatalog.Contains(TEXT("coverage_search"))&&ScenarioCatalog.Contains(TEXT("safe_degradation"));
}

FString FMRCoreRuntime::ValidatePlan(const Object& Request,FString& Code) const
{
    const auto Previous=Request->GetObjectField(TEXT("previous_configuration"));
    const auto Selected=Request->GetObjectField(TEXT("selected_configuration"));
    const auto Roles=Request->GetObjectField(TEXT("role_assignments"));
    TArray<FString> OldIds,PreviousIds,NewIds;
    ReadIds(Accepted,TEXT("scenario_ids"),OldIds);
    if(!ReadIds(Previous,TEXT("scenario_ids"),PreviousIds)||PreviousIds!=OldIds||
        !MRCoreJson::Equal(Field(Previous,TEXT("role_assignments")),Json(DesiredRoles)))
        return TEXT("Previous configuration differs from last accepted plan");
    if(Previous->HasField(TEXT("parameters"))&&!MRCoreJson::Equal(Field(Previous,TEXT("parameters")),Field(Accepted,TEXT("parameters"))))
        return TEXT("Previous parameters differ");
    if(!ReadIds(Selected,TEXT("scenario_ids"),NewIds)||!Is(Selected,TEXT("parameters"),EJson::Object)||
        !(Is(Selected,TEXT("synthesized_scenario"),EJson::Null)||Is(Selected,TEXT("synthesized_scenario"),EJson::Object)))
        return TEXT("Invalid selected configuration");
    const auto Parameters=Selected->GetObjectField(TEXT("parameters"));
    const auto Synth=Field(Selected,TEXT("synthesized_scenario"));
    const bool SameIds=OldIds==NewIds,SameRoles=MRCoreJson::Equal(Json(Roles),Json(DesiredRoles));
    const bool SameParameters=MRCoreJson::Equal(Json(Parameters),Field(Accepted,TEXT("parameters")));
    const bool SameDefinition=MRCoreJson::Equal(Synth,Field(Accepted,TEXT("synthesized_scenario")));
    const bool SameMembership=(!Selected->HasField(TEXT("scenario_participants"))&&!Accepted->HasField(TEXT("scenario_participants")))||
        MRCoreJson::Equal(Field(Selected,TEXT("scenario_participants")),Field(Accepted,TEXT("scenario_participants")));
    const bool SamePlan=SameIds&&SameRoles&&SameParameters&&SameDefinition&&SameMembership;
    const FString Operation=Text(Request,TEXT("operation"));
    if(Operation==TEXT("keep"))return SamePlan?TEXT(""):TEXT("Keep changes accepted configuration or roles");
    Code=TEXT("INVALID_SCENARIO");
    if(SafeStopRequested)return TEXT("A safe stop is already in progress");
    const bool HasSynth=Synth->Type==EJson::Object;
    if(Operation==TEXT("select"))
    {
        if(!OldIds.IsEmpty()||NewIds.Num()!=1||HasSynth)return TEXT("Select requires one known scenario and no active plan");
    }
    else if(Operation==TEXT("switch"))
    {
        if(OldIds.IsEmpty()||NewIds.Num()!=1||HasSynth||
            (SameIds&&(NewIds[0]!=TEXT("coordination_reconfiguration")||SameRoles)))
            return TEXT("Switch requires an actual scenario or coordination replacement");
    }
    else if(Operation==TEXT("modify"))
    {
        if(OldIds.IsEmpty()||!SameIds||!SameRoles||!SameDefinition||!SameMembership||SameParameters)
            return TEXT("Modify requires a change to declared parameters only");
    }
    else if(Operation==TEXT("compose"))
    {
        if(NewIds.Num()<2||HasSynth||SameIds)return TEXT("Compose requires a new combination of known scenarios");
    }
    else if(Operation==TEXT("synthesize"))
    {
        if(!HasSynth||NewIds.Num()!=1||ScenarioCatalog.Contains(NewIds[0])||Text(Synth->AsObject(),TEXT("id"))!=NewIds[0]||
            !DeclaredShape(Synth->AsObject())||SameDefinition||!BoundedProgram(Synth->AsObject(),Parameters))
            return TEXT("Synthesize requires a new, valid scenario declaration");
    }
    else if(Operation==TEXT("safe_stop"))
    {
        if(SamePlan)return TEXT("");
        if(HasSynth||NewIds!=TArray<FString>{TEXT("safe_degradation")})return TEXT("Safe stop requires a safe degradation plan");
    }
    else return TEXT("Unknown operation");
    const bool Composite=NewIds.Num()>1;
    const auto Groups=Is(Parameters,TEXT("by_scenario"),EJson::Object)?Parameters->GetObjectField(TEXT("by_scenario")):nullptr;
    const bool Disjoint=Is(Parameters,TEXT("disjoint_agent_assignments"),EJson::Boolean)&&Parameters->GetBoolField(TEXT("disjoint_agent_assignments"));
    if(Composite&&(!Groups||Groups->Values.Num()!=NewIds.Num()))return TEXT("Each composed scenario needs its own parameters");
    if(Selected->HasField(TEXT("scenario_participants")))
    {
        if(!Is(Selected,TEXT("scenario_participants"),EJson::Object))return TEXT("Invalid scenario participants");
        for(const auto& Group:Selected->GetObjectField(TEXT("scenario_participants"))->Values)
        {
            TArray<FString> Participants;const FString Id(*Group.Key);
            if(!NewIds.Contains(Id)||!ReadIds(Selected->GetObjectField(TEXT("scenario_participants")),Id,Participants))
                return TEXT("Invalid participant group");
            const auto Scenario=Declaration(ScenarioCatalog,Selected,Id);
            for(const FString& Agent:Participants)if(!RoleDefinition(Scenario,Text(Roles,Agent)))return TEXT("Invalid participant role");
        }
    }
    TMap<FString,int32> Memberships;
    for(const FString& Id:NewIds)
    {
        const auto Scenario=Declaration(ScenarioCatalog,Selected,Id);
        if(!Scenario)return TEXT("Unknown scenario");
        for(const FString& Other:NewIds)if(Other!=Id&&!Contains(Scenario,TEXT("compatible_with"),Other))return TEXT("Incompatible scenario composition");
        const auto Data=Composite?Field(Groups,Id):Json(Parameters);
        const auto Schema=Field(Scenario,TEXT("parameter_schema"));
        if(!Data||Data->Type!=EJson::Object||(Schema&&(Schema->Type!=EJson::Object||!ParametersMatch(Schema->AsObject(),Data))))
            return TEXT("Invalid scenario parameters");
        if(Is(Data->AsObject(),TEXT("target_id"),EJson::String)&&!KnownTargets.Contains(Text(Data->AsObject(),TEXT("target_id"))))
            return TEXT("Scenario target is unknown in delivered knowledge");
        TMap<FString,int32> Counts;
        for(const auto& Pair:Roles->Values)
        {
            const FString Agent(*Pair.Key),Role=Pair.Value->Type==EJson::String?Pair.Value->AsString():FString();
            if(!Member(Selected,Scenario,Agent,Role))continue;
            const auto Known=KnownAgents.FindRef(Agent);
            if(!Known)return TEXT("Unknown role participant");
            const auto Rule=RoleDefinition(Scenario,Role);
            for(const auto& Capability:Rule->GetArrayField(TEXT("required_capabilities")))
                if(!Contains(Known,TEXT("capabilities"),Capability->AsString()))return TEXT("Role lacks a required capability");
            ++Counts.FindOrAdd(Role);++Memberships.FindOrAdd(Agent);
        }
        for(const auto& Entry:Scenario->GetArrayField(TEXT("roles")))
        {
            const auto Rule=Entry->AsObject();const int32 Count=Counts.FindRef(Text(Rule,TEXT("id")));
            if(Count<Rule->GetNumberField(TEXT("minimum"))||Count>Rule->GetNumberField(TEXT("maximum")))
                return TEXT("Scenario role cardinality is invalid");
        }
        for(const auto& Entry:Scenario->GetArrayField(TEXT("constraints")))
        {
            const auto Constraint=Entry->AsObject();
            if(Text(Constraint,TEXT("severity"))!=TEXT("hard"))continue;
            Object Context=CachedObservation;
            const auto Scope=Field(Constraint,TEXT("scope"));
            if(Scope&&Scope->Type==EJson::Object&&Text(Scope->AsObject(),TEXT("kind"))==TEXT("agent"))
                Context=KnownAgents.FindRef(Text(Scope->AsObject(),TEXT("agent_id")));
            const auto Outcome=MRCoreExpressions::Evaluate(Constraint->GetObjectField(TEXT("predicate")),Context);
            if(!Outcome||Outcome->Type!=EJson::Boolean||!Outcome->AsBool())
            {Code=TEXT("CONSTRAINT_VIOLATION");return TEXT("Hard scenario constraint failed or lacks delivered evidence: ")+Text(Constraint,TEXT("id"));}
        }
    }
    for(const auto& Pair:Roles->Values)
    {
        const int32 Count=Memberships.FindRef(FString(*Pair.Key));
        if(Count==0||(Disjoint&&Count>1))return TEXT("Role is undeclared or assigned incompatibly");
    }
    return TEXT("");
}

TArray<Value> FMRCoreRuntime::AgentScenarios(const FString& AgentId,const FString& Role) const
{
    TArray<FString> Ids;
    ReadIds(Accepted,TEXT("scenario_ids"),Ids);
    TArray<Value> Result;
    for(const FString& Id:Ids)if(Member(Accepted,Declaration(ScenarioCatalog,Accepted,Id),AgentId,Role))Result.Add(Str(Id));
    return Result;
}
