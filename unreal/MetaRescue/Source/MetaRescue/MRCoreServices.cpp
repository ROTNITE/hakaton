#include "MRCoreRuntime.h"
#include "MRCoreValues.h"
#include "MRCoreJson.h"
#include "MRWorld.h"
#include "MRAgent.h"

using namespace MRCoreValues;

namespace
{
const FString DirectiveFormat=TEXT("metarescue.operator_directives.v1");
const TSet<FString> Instructions={TEXT("hold"),TEXT("set_priority"),TEXT("restrict_zone"),TEXT("message")};
const TSet<FString> Changes={TEXT("cancel"),TEXT("clarify"),TEXT("confirm"),TEXT("request_confirmation")};

bool ServiceNumber(const Object& Row,const FString& Key,double Low,double High)
{
    if(!Is(Row,Key,EJson::Number))return false;
    const double Value=Row->GetNumberField(Key);
    return FMath::IsFinite(Value)&&Value>=Low&&Value<=High;
}

bool ServiceText(const Object& Row,const FString& Key,int32 Limit)
{
    const FString Value=Text(Row,Key);
    if(Value.IsEmpty()||Value.Len()>Limit)return false;
    for(const TCHAR Char:Value)if(Char<32)return false;
    return true;
}

Object OrbitalSettings(const Object& Layout)
{
    if(!Is(Layout,TEXT("competition"),EJson::Object))return nullptr;
    const auto Annex=Layout->GetObjectField(TEXT("competition"));
    if(!Is(Annex,TEXT("orbital_sensor"),EJson::Object))return nullptr;
    const auto Sensor=Annex->GetObjectField(TEXT("orbital_sensor"));
    if(Text(Sensor,TEXT("id")).IsEmpty()||!Is(Sensor,TEXT("period_s"),EJson::Number)||
       !Is(Sensor,TEXT("altitude_km"),EJson::Number)||!Is(Sensor,TEXT("swath_m"),EJson::Number))return nullptr;
    if(Sensor->GetNumberField(TEXT("period_s"))<20||Sensor->GetNumberField(TEXT("swath_m"))<5||
       Sensor->GetNumberField(TEXT("swath_m"))>100||Sensor->GetNumberField(TEXT("altitude_km"))<100)return nullptr;
    return Sensor;
}
}

void FMRCoreRuntime::ResetServices()
{
    ComputeCredits.Reset();IssuedDirectives.Reset();PendingOrbital.Reset();KnownOrbital.Reset();OrbitalDeliveryAt=-1;
    for(const AMRAgent* Agent:World->Agents)if(Agent->Kind()==TEXT("digital"))ComputeCredits.Add(Agent->AgentKey(),16);
    NextOrbitalScan=OrbitalSettings(World->CityLayout)?1:-1;
}

FString FMRCoreRuntime::ValidateDirectiveInstruction(const Object& P) const
{
    const FString Action=Text(P,TEXT("action"));
    if(!Instructions.Contains(Action)||!ServiceText(P,TEXT("reason"),128))return TEXT("invalid_operator_instruction");
    if(!ServiceNumber(P,TEXT("duration_s"),1,60))return TEXT("invalid_directive_duration");
    if(P->HasField(TEXT("confidence"))&&!ServiceNumber(P,TEXT("confidence"),0,1))return TEXT("invalid_directive_confidence");
    if(P->HasField(TEXT("requires_confirmation"))&&!Is(P,TEXT("requires_confirmation"),EJson::Boolean))
        return TEXT("invalid_directive_confirmation_flag");
    if(Action==TEXT("hold"))
    {
        const auto Target=KnownAgents.FindRef(Text(P,TEXT("target_id")));
        if(!Target)return TEXT("unknown_directive_recipient");
        const auto& Caps=Target->GetArrayField(TEXT("capabilities"));
        if(!Caps.ContainsByPredicate([](const Value& V){return V->AsString()==TEXT("move");}))
            return TEXT("directive_recipient_has_no_motion");
    }
    else if(Action==TEXT("set_priority"))
    {
        if(!KnownTargets.Contains(Text(P,TEXT("target_id"))))return TEXT("unknown_public_priority_target");
        if(!ServiceNumber(P,TEXT("priority"),1,3)||P->GetNumberField(TEXT("priority"))!=FMath::FloorToDouble(P->GetNumberField(TEXT("priority"))))
            return TEXT("invalid_operator_priority");
    }
    else if(Action==TEXT("message"))
    {
        if(!ServiceText(P,TEXT("text"),512))return TEXT("invalid_operator_message");
    }
    else
    {
        if(!Is(P,TEXT("bounds"),EJson::Object)||!Is(P,TEXT("allowed_kinds"),EJson::Array)||!World->bCityLayout)
            return TEXT("invalid_operator_restriction");
        const auto Bounds=P->GetObjectField(TEXT("bounds"));FVector Min,Max,MapMin,MapMax;
        const auto Map=World->CityLayout->GetObjectField(TEXT("bounds"));
        if(!MRCoreJson::Point(Field(Bounds,TEXT("min")),Min)||!MRCoreJson::Point(Field(Bounds,TEXT("max")),Max)||
           !MRCoreJson::Point(Field(Map,TEXT("min")),MapMin)||!MRCoreJson::Point(Field(Map,TEXT("max")),MapMax)||
           !FBox(MapMin,MapMax).IsInsideOrOn(Min)||!FBox(MapMin,MapMax).IsInsideOrOn(Max)||
           Min.X>=Max.X||Min.Y>=Max.Y||Min.Z>=Max.Z)return TEXT("invalid_operator_restriction_bounds");
        static const TSet<FString> Kinds={TEXT("ground"),TEXT("aerial"),TEXT("underground"),TEXT("surface_water"),
            TEXT("underwater"),TEXT("infrastructure"),TEXT("digital"),TEXT("operator")};
        TSet<FString> Seen;
        for(const auto& Kind:P->GetArrayField(TEXT("allowed_kinds")))
        {
            if(Kind->Type!=EJson::String||!Kinds.Contains(Kind->AsString())||Seen.Contains(Kind->AsString()))
                return TEXT("invalid_operator_restriction_kind");
            Seen.Add(Kind->AsString());
        }
    }
    return TEXT("");
}

FString FMRCoreRuntime::ValidateServiceCommand(const Object& Command) const
{
    const auto P=Command->GetObjectField(TEXT("parameters"));
    if(Text(Command,TEXT("action"))==TEXT("compute"))
    {
        const FString Mode=Text(P,TEXT("operation"));
        if(Mode!=TEXT("sum")&&Mode!=TEXT("minimum"))return TEXT("unknown_compute_operation");
        if(!Is(P,TEXT("values"),EJson::Array))return TEXT("invalid_compute_values");
        const auto& Values=P->GetArrayField(TEXT("values"));
        if(Values.IsEmpty()||Values.Num()>64)return TEXT("invalid_compute_size");
        for(const auto& V:Values)if(V->Type!=EJson::Number||!FMath::IsFinite(V->AsNumber())||FMath::Abs(V->AsNumber())>1.e9)
            return TEXT("invalid_compute_value");
    }
    else
    {
        const FString Action=Text(P,TEXT("action"));
        if(Instructions.Contains(Action))return ValidateDirectiveInstruction(P);
        if(!Changes.Contains(Action)||!ServiceText(P,TEXT("reason"),128)||!ServiceText(P,TEXT("directive_id"),100)||
           !ServiceNumber(P,TEXT("expected_revision"),1,1.e6)||
           P->GetNumberField(TEXT("expected_revision"))!=FMath::FloorToDouble(P->GetNumberField(TEXT("expected_revision"))))
            return TEXT("invalid_operator_change");
        const FString Id=Text(P,TEXT("directive_id"));
        const auto Existing=Directives.FindRef(Id);
        if(!IssuedDirectives.Contains(Id)||!Existing||Text(Existing,TEXT("source"))!=Text(Command,TEXT("agent_id")))
            return TEXT("unknown_or_foreign_operator_requirement");
        if(Existing->GetNumberField(TEXT("revision"))!=P->GetNumberField(TEXT("expected_revision"))||
           Existing->GetNumberField(TEXT("expires_at"))<=Time())return TEXT("stale_operator_requirement_revision");
        const FString RequirementStatus=Text(Existing,TEXT("status"));
        if(RequirementStatus==TEXT("cancelled")&&Action!=TEXT("request_confirmation"))return TEXT("operator_requirement_already_cancelled");
        if(Action==TEXT("confirm")&&RequirementStatus!=TEXT("pending_confirmation"))return TEXT("operator_requirement_not_confirmable");
        if(Action==TEXT("clarify"))
        {
            if(!Is(P,TEXT("instruction"),EJson::Object))return TEXT("missing_clarified_instruction");
            return ValidateDirectiveInstruction(P->GetObjectField(TEXT("instruction")));
        }
    }
    return TEXT("");
}

bool FMRCoreRuntime::StartCompute(FCommand& Command)
{
    auto* Credits=ComputeCredits.Find(Command.Agent);
    if(!Credits||*Credits<=0||Commands.ContainsByPredicate([&](const FCommand& Other)
       {return Other.Key!=Command.Key&&Other.Agent==Command.Agent&&Other.ServiceDue>=0&&Other.FinalStatus.IsEmpty();}))return false;
    const auto& Values=Command.Parameters->GetArrayField(TEXT("values"));
    const bool Minimum=Text(Command.Parameters,TEXT("operation"))==TEXT("minimum");
    double Result=Minimum?Values[0]->AsNumber():0.;
    for(const auto& Value:Values)Result=Minimum?FMath::Min(Result,Value->AsNumber()):Result+Value->AsNumber();
    --*Credits;
    Command.ServiceDue=Time()+.1+.015*Values.Num();
    Command.ServiceResult=Obj({{TEXT("operation"),Field(Command.Parameters,TEXT("operation"))},
        {TEXT("value"),Num(Result)},{TEXT("count"),Num(Values.Num())},{TEXT("credits_remaining"),Num(*Credits)},
        {TEXT("started_at"),Num(Time())},{TEXT("service_completed_at"),Num(Command.ServiceDue)}});
    Record(TEXT("compute_started"),Obj({{TEXT("command_id"),Str(Command.Key)},{TEXT("agent_id"),Str(Command.Agent)},
        {TEXT("inputs"),Json(Command.Parameters)},{TEXT("service_due"),Num(Command.ServiceDue)}}),false);
    return true;
}

bool FMRCoreRuntime::IssueDirective(FCommand& Command)
{
    // Validate again at delivery: another queued change may already have
    // advanced the referenced revision since this Step was accepted.
    const auto Wire=Obj({{TEXT("action"),Str(TEXT("issue_directive"))},{TEXT("agent_id"),Str(Command.Agent)},
        {TEXT("parameters"),Json(Command.Parameters)}});
    Command.Reason=ValidateServiceCommand(Wire);
    if(!Command.Reason.IsEmpty())return false;
    const FString Change=Text(Command.Parameters,TEXT("action"));
    const bool New=Instructions.Contains(Change);
    const FString Id=New?Command.Key:Text(Command.Parameters,TEXT("directive_id"));
    if(New&&IssuedDirectives.Num()>=64){Command.Reason=TEXT("operator_requirement_capacity");return false;}
    const auto Before=New?Object():Directives.FindChecked(Id);
    Object Order;
    if(New||Change==TEXT("clarify"))
    {
        const auto Instruction=New?Command.Parameters:Command.Parameters->GetObjectField(TEXT("instruction"));
        const FString Action=Text(Instruction,TEXT("action"));
        Order=Obj();
        for(const FString& Key:{TEXT("action"),TEXT("reason"),TEXT("duration_s"),TEXT("confidence"),TEXT("requires_confirmation")})
            if(const auto Value=Field(Instruction,Key))Order->SetField(Key,Value);
        if(Action==TEXT("hold")||Action==TEXT("set_priority"))Order->SetField(TEXT("target_id"),Field(Instruction,TEXT("target_id")));
        if(Action==TEXT("set_priority"))Order->SetField(TEXT("priority"),Field(Instruction,TEXT("priority")));
        if(Action==TEXT("message"))Order->SetField(TEXT("text"),Field(Instruction,TEXT("text")));
        if(Action==TEXT("restrict_zone"))
        {
            const auto Bounds=Instruction->GetObjectField(TEXT("bounds"));
            Order->SetObjectField(TEXT("bounds"),Obj({{TEXT("min"),Field(Bounds,TEXT("min"))},{TEXT("max"),Field(Bounds,TEXT("max"))}}));
            Order->SetField(TEXT("allowed_kinds"),Field(Instruction,TEXT("allowed_kinds")));
        }
        const bool Pending=(Is(Instruction,TEXT("requires_confirmation"),EJson::Boolean)&&Instruction->GetBoolField(TEXT("requires_confirmation")))||
            (Is(Instruction,TEXT("confidence"),EJson::Number)&&Instruction->GetNumberField(TEXT("confidence"))<.75);
        Order->SetStringField(TEXT("format"),DirectiveFormat);Order->SetStringField(TEXT("id"),Id);
        Order->SetStringField(TEXT("source"),Command.Agent);
        Order->SetNumberField(TEXT("issued_at"),Before?Before->GetNumberField(TEXT("issued_at")):Time());
        Order->SetNumberField(TEXT("expires_at"),Time()+Instruction->GetNumberField(TEXT("duration_s")));
        Order->SetStringField(TEXT("status"),Action==TEXT("message")?TEXT("needs_clarification"):Pending?TEXT("pending_confirmation"):TEXT("active"));
        if(Action==TEXT("hold"))Order->SetStringField(TEXT("agent_id"),Text(Instruction,TEXT("target_id")));
        if(Action==TEXT("restrict_zone"))Order->SetStringField(TEXT("zone_id"),TEXT("operator-restriction-")+Id);
    }
    else
    {
        Order=MRCoreJson::Copy(Before);
        if(Change==TEXT("cancel"))Order->SetStringField(TEXT("status"),TEXT("cancelled"));
        else if(Change==TEXT("confirm"))Order->SetStringField(TEXT("status"),TEXT("active"));
        else if(Change==TEXT("request_confirmation"))Order->SetBoolField(TEXT("confirmation_requested"),true);
    }
    Order->SetNumberField(TEXT("revision"),Before?Before->GetNumberField(TEXT("revision"))+1:1);
    Order->SetNumberField(TEXT("updated_at"),Time());Order->SetStringField(TEXT("change_reason"),Text(Command.Parameters,TEXT("reason")));
    Order->SetStringField(TEXT("last_change_command_id"),Command.Key);
    Directives.Add(Id,Order);IssuedDirectives.Add(Id);UpdateDirectiveRestriction(Id,Order);
    TArray<FString> Targets;
    const FString Target=Text(Order,TEXT("target_id"));if(!Target.IsEmpty())Targets.Add(Target);
    PublishEvent(Command.Key,TEXT("operator_directive"),Time(),Command.Agent,Targets,Order,
        Text(Order,TEXT("status"))==TEXT("cancelled")?TEXT("resolved"):TEXT("active"));
    Command.ServiceResult=Obj({{TEXT("directive_id"),Str(Id)},{TEXT("revision"),Field(Order,TEXT("revision"))},
        {TEXT("status"),Field(Order,TEXT("status"))},{TEXT("expires_at"),Field(Order,TEXT("expires_at"))}});
    Command.FinalStatus=TEXT("completed");
    return true;
}

void FMRCoreRuntime::UpdateDirectiveRestriction(const FString& Id,const Object& Order)
{
    const FString Zone=TEXT("operator-restriction-")+Id;
    World->CoreRestrictions.Remove(Zone);KnownZones.Remove(Zone);
    if(!Order||Text(Order,TEXT("status"))!=TEXT("active")||Text(Order,TEXT("action"))!=TEXT("restrict_zone"))return;
    const auto Bounds=Order->GetObjectField(TEXT("bounds"));FVector Min,Max;
    MRCoreJson::Point(Field(Bounds,TEXT("min")),Min);MRCoreJson::Point(Field(Bounds,TEXT("max")),Max);
    FMRRestriction Region;Region.Bounds=FBox(Min*100,Max*100);
    for(const auto& Kind:Order->GetArrayField(TEXT("allowed_kinds")))Region.AllowedKinds.Add(Kind->AsString());
    World->CoreRestrictions.Add(Zone,Region);
    KnownZones.Add(Zone,Obj({{TEXT("id"),Str(Zone)},{TEXT("type"),Str(TEXT("restricted"))},{TEXT("risk"),Num(1)},
        {TEXT("geometry"),Json(Obj({{TEXT("type"),Str(TEXT("box"))},{TEXT("min"),Field(Bounds,TEXT("min"))},{TEXT("max"),Field(Bounds,TEXT("max"))}}))},
        {TEXT("access"),Json(Obj({{TEXT("allowed_kinds"),Field(Order,TEXT("allowed_kinds"))}}))},
        {TEXT("cost"),Json(Obj())},{TEXT("communication"),Json(Obj())},{TEXT("constraints"),Arr({})}}));
}

void FMRCoreRuntime::AdvanceServices()
{
    for(auto It=IssuedDirectives.CreateIterator();It;++It)
    {
        const auto Directive=Directives.FindRef(*It);
        if(!Directive){It.RemoveCurrent();continue;}
        if(Directive->GetNumberField(TEXT("expires_at"))>Time()+1.e-9)continue;
        TArray<FString> Targets;
        for(const FString& Key:{TEXT("target_id"),TEXT("zone_id")})
            if(const FString Target=Text(Directive,Key);!Target.IsEmpty())Targets.AddUnique(Target);
        PublishEvent(*It,TEXT("operator_directive"),Directive->GetNumberField(TEXT("issued_at")),
            Text(Directive,TEXT("source")),Targets,Directive,TEXT("expired"));
        UpdateDirectiveRestriction(*It,nullptr);Directives.Remove(*It);It.RemoveCurrent();
    }
    if(PendingOrbital&&Time()+1.e-9>=OrbitalDeliveryAt)
    {
        if(!DisabledInfrastructure.Contains(TEXT("rescue-base")))
        {
            PendingOrbital->SetNumberField(TEXT("received_at"),Time());KnownOrbital=PendingOrbital;
            Record(TEXT("orbital_observation_delivered"),KnownOrbital);
        }
        else Record(TEXT("orbital_downlink_missed"),PendingOrbital,false);
        PendingOrbital.Reset();OrbitalDeliveryAt=-1;
    }
    if(NextOrbitalScan<0||Time()+1.e-9<NextOrbitalScan)return;
    const auto Sensor=OrbitalSettings(World->CityLayout);
    if(!Sensor){NextOrbitalScan=-1;return;}
    const double Size=World->CityLayout->GetNumberField(TEXT("size_m"));
    const double Phase=FMath::Fmod(Time(),Sensor->GetNumberField(TEXT("period_s")))/Sensor->GetNumberField(TEXT("period_s"));
    const FVector Center(Size*Phase,Size*.45+Size*.16*FMath::Sin(Phase*2*PI),0);
    const double Radius=Sensor->GetNumberField(TEXT("swath_m"))*.5;
    TArray<Value> Samples;
    for(double X=FMath::FloorToDouble((Center.X-Radius)/5)*5+2.5;X<Center.X+Radius;X+=5)
        for(double Y=FMath::FloorToDouble((Center.Y-Radius)/5)*5+2.5;Y<Center.Y+Radius;Y+=5)
        {
            if(X<0||Y<0||X>=Size||Y>=Size||FVector::DistSquared2D(Center,FVector(X,Y,0))>FMath::Square(Radius))continue;
            const auto Surface=World->QuerySurfaceMeters(FVector(X,Y,.1));
            if(Surface.VisibilityQuality>=.99f&&Surface.WaterDepthMeters<=.02f)continue;
            Samples.Add(Json(Obj({{TEXT("position_m"),Point(FVector(X,Y,0))},{TEXT("water_depth_m"),Num(Surface.WaterDepthMeters)},
                {TEXT("visibility"),Num(Surface.VisibilityQuality)}})));
        }
    PendingOrbital=Obj({{TEXT("source_id"),Field(Sensor,TEXT("id"))},{TEXT("observed_at"),Num(Time())},
        {TEXT("ground_track_m"),Point(Center)},{TEXT("altitude_km"),Field(Sensor,TEXT("altitude_km"))},
        {TEXT("swath_radius_m"),Num(Radius)},{TEXT("visible_surface_samples"),Arr(Samples)}});
    Record(TEXT("orbital_observation_captured"),PendingOrbital,false);
    OrbitalDeliveryAt=Time()+.45;NextOrbitalScan=Time()+5;
}
