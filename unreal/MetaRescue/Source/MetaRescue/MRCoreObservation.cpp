#include "MRCoreRuntime.h"
#include "MRCoreReset.h"
#include "MRCoreJson.h"
#include "MRCoreValues.h"
#include "MRWorld.h"
#include "MRAgent.h"
#include "Components/BoxComponent.h"
#include "Engine/World.h"

using namespace MRCoreValues;

AMRAgent* FMRCoreRuntime::FindAgent(const FString& Id) const
{for(AMRAgent* A:World->Agents)if(A->AgentKey()==Id)return A;return nullptr;}

int32 FMRCoreRuntime::FindTarget(const FString& Id) const
{for(int32 I=0;I<World->Targets.Num();I++)if(Id==FString::Printf(TEXT("person-%d"),World->Targets[I].Id))return I;return -1;}

Object FMRCoreRuntime::AgentSnapshot(AMRAgent* A,double ObservedAt) const
{
    const auto* Signal=Signals.Find(A->AgentKey());
    const bool Reachable=Signal&&Signal->Success>0;
    const bool Service=A->State==TEXT("loading")||A->State==TEXT("unloading");
    const bool Charging=A->IsCharging();
    const bool Degraded=A->SpeedFactor<1||A->SensorFactor<1;
    const bool Operating=A->IsOperational()&&!DisabledInfrastructure.Contains(A->InfrastructureSite);
    TArray<Value> Actions;
    TArray<Value> Caps={Str(TEXT("communicate"))};
    if(A->CanMove())Caps.Add(Str(TEXT("move")));
    if(A->CanSense()){Caps.Add(Str(TEXT("sense")));Caps.Add(Str(TEXT("inspect")));Caps.Add(Str(TEXT("relay")));}
    if(A->CanCarry())Caps.Add(Str(TEXT("carry")));
    const auto* Kits=MedicalKits.Find(A->AgentKey());
    const auto* Credits=ComputeCredits.Find(A->AgentKey());
    if(Kits)Caps.Add(Str(TEXT("deliver")));
    if(Credits)Caps.Add(Str(TEXT("compute")));
    if(A->Kind()==TEXT("operator"))Caps.Add(Str(TEXT("issue_directive")));
    if(A->Category.IsEmpty()&&!ChargingStations.IsEmpty())Caps.Add(Str(TEXT("charge")));
    auto Add=[&](const FString& Name){Actions.Add(Json(Obj({{TEXT("action"),Str(Name)}})));};
    if(Operating)
    {
        Add(TEXT("send_message"));
        if(A->CanSense()){Add(TEXT("observe"));Add(TEXT("relay"));if(!Charging)Add(TEXT("inspect"));}
        if(A->CanMove())
        {
            Add(TEXT("hold"));
            if(!Service&&!Charging){Add(TEXT("move"));Add(TEXT("follow_route"));}
        }
        if(A->CanCarry()&&!Service&&!Charging){if(A->bCarrying)Add(TEXT("handover"));else Add(TEXT("pickup"));}
        if(Kits&&*Kits>0&&!A->bCarrying&&!Service&&!Charging)Add(TEXT("deliver"));
        if(Credits&&*Credits>0)Add(TEXT("compute"));
        if(A->Kind()==TEXT("operator"))Add(TEXT("issue_directive"));
    }
    else if(Charging)Add(TEXT("hold"));
    for(const auto& Pair:ChargingStations)if(CanStartCharge(Pair.Key,A)){Add(TEXT("charge"));break;}
    auto Communication=Obj({{TEXT("reachable"),Bool(Reachable)},{TEXT("quality"),Num(Reachable?Signal->Quality:0)},
        {TEXT("relay_enabled"),Bool(RelayingAgents.Contains(A->AgentKey()))},
        {TEXT("latency"),Num(Reachable?Latency*Hops.FindRef(A->AgentKey()):0)},
        {TEXT("hops"),Reachable?Num(Hops.FindRef(A->AgentKey())):Null()},
        {TEXT("upstream_id"),Reachable?Str(Signal->Upstream):Null()},
        {TEXT("path_success_probability"),Num(Reachable?Signal->Success:0)},
        {TEXT("last_link_quality"),Num(Reachable?Signal->LinkQuality:0)}});
    if(const auto* Inbox=Inboxes.Find(A->AgentKey());Inbox&&!Inbox->IsEmpty())
    {
        TArray<Value> Delivered;
        for(int32 I=FMath::Max(0,Inbox->Num()-32);I<Inbox->Num();++I)
            if((*Inbox)[I]->GetNumberField(TEXT("received_at"))<=ObservedAt+1.e-9)Delivered.Add(Json((*Inbox)[I]));
        Communication->SetArrayField(TEXT("inbox"),Delivered);
    }
    const auto* Configuration=ActualConfigurations.Find(A->AgentKey());
    auto Data=Obj({{TEXT("id"),Str(A->AgentKey())},{TEXT("kind"),Str(A->Kind())},
        {TEXT("position"),A->IsSpatial()?Point(A->GetActorLocation()/100.):Null()},
        {TEXT("status"),Str(Charging?TEXT("charging"):!Operating?TEXT("failed"):A->bCarrying||Service?TEXT("busy"):
            Degraded?TEXT("degraded"):TEXT("active"))},
        {TEXT("capabilities"),Arr(Caps)},
        {TEXT("resources"),Json(Obj({{TEXT("energy"),Resource(TEXT("energy"),A->Energy/FMath::Max(1.,A->BatteryCapacityWh))}}))},
        {TEXT("communication"),Json(Communication)},
        {TEXT("role"),Configuration&&!Configuration->Role.IsEmpty()?Str(Configuration->Role):Null()},
        {TEXT("scenario_ids"),Configuration?Arr(Configuration->Scenarios):Arr({})},
        {TEXT("configuration_revision"),Num(Configuration?Configuration->Revision:0)},
        {TEXT("available_actions"),Arr(Actions)},{TEXT("constraints"),Arr({})}});
    if(Kits)
    {
        Data->GetObjectField(TEXT("resources"))->SetField(TEXT("medical_kits"),Resource(TEXT("medical_kits"),double(*Kits)/3));
        Data->SetObjectField(TEXT("aid_stock"),Obj({{TEXT("medical_kits"),Num(*Kits)},{TEXT("capacity"),Num(3)}}));
    }
    if(A->MediumLimits.IsValid)Data->SetObjectField(TEXT("movement_volume"),Obj({{TEXT("kind"),Str(TEXT("box"))},
        {TEXT("min"),Point(A->MediumLimits.Min/100.)},{TEXT("max"),Point(A->MediumLimits.Max/100.)}}));
    if(Credits)
    {
        Data->GetObjectField(TEXT("resources"))->SetField(TEXT("compute_credits"),Resource(TEXT("compute_credits"),double(*Credits)/16));
        Data->SetNumberField(TEXT("compute_credits"),*Credits);
    }
    const auto Rotation=A->GetActorRotation();
    Data->SetObjectField(TEXT("physical"),Obj({{TEXT("remaining_wh"),Num(A->Energy)},{TEXT("consumed_wh"),Num(A->ConsumedWh)},
        {TEXT("capacity_wh"),Num(A->BatteryCapacityWh)},{TEXT("unlimited_energy"),Bool(Unlimited)},
        {TEXT("reserve_wh"),Num(A->EnergyReserveWh)},{TEXT("charged_wh"),Num(A->ChargedWh)},
        {TEXT("energy_breakdown_wh"),Json(Obj({{TEXT("movement"),Num(A->MotionWh)},{TEXT("standby"),Num(A->StandbyWh)},
            {TEXT("sensing"),Num(A->SensorWh)},{TEXT("service"),Num(A->ServiceWh)}}))},
        {TEXT("distance_m"),Num(A->DistanceTravelled/100.)},{TEXT("velocity_m_s"),Point(A->Body->GetPhysicsLinearVelocity()/100.)},
        {TEXT("intended_velocity_m_s"),Point(A->IntendedVelocity/100.)},
        {TEXT("rotation_degrees"),Point(FVector(Rotation.Roll,Rotation.Pitch,Rotation.Yaw))},
        {TEXT("state"),Str(A->State)},{TEXT("stop_reason"),Str(A->StopReason)},
        {TEXT("stop_obstacle"),Str(A->StopObstacle)},{TEXT("active_waypoint"),Point(A->ActiveWaypoint()/100.)},
        {TEXT("active_command_id"),Str(A->CommandId)},{TEXT("route_finished"),Bool(A->RouteFinished())},{TEXT("carrying"),Bool(A->bCarrying)},
        {TEXT("cargo_target_id"),A->bCarrying&&World->Targets.IsValidIndex(A->TargetIndex)?Str(FString::Printf(TEXT("person-%d"),World->Targets[A->TargetIndex].Id)):Null()},
        {TEXT("radius_m"),Num(A->SafetyRadius()/100.)},{TEXT("chassis_radius_m"),Num(A->bAerial?1.65:1.45)},
        {TEXT("speed_limit_m_s"),Num(A->MaxSpeed*A->SpeedFactor/100.)},
        {TEXT("mass_kg"),Num(A->Body->IsSimulatingPhysics()?A->Body->GetMass():0)},
        {TEXT("speed_factor"),Num(A->SpeedFactor)},{TEXT("sensor_factor"),Num(A->SensorFactor)},
        {TEXT("failure_reason"),A->FailureReason.IsEmpty()?Null():Str(A->FailureReason)},
        {TEXT("ramp_deployment"),Num(A->RampDeployment)},{TEXT("rotor_rpm"),Num(A->RotorRPM)},
        {TEXT("ground_contacts"),Num(A->GroundContacts)},{TEXT("vehicle_contacts"),Num(A->AgentContacts)},
        {TEXT("service_remaining_s"),Num(A->RemainingServiceSeconds())},
        {TEXT("dock_position_m"),Point(A->Dock/100.)},{TEXT("climb_rate_m_s"),Num(A->bAerial?5:0)},
        {TEXT("descent_rate_m_s"),Num(A->bAerial?2.5:0)},{TEXT("payload_speed_factor"),Num(A->bAerial?1:.8)}}));
    if(A->SensedBlocker.IsValid)
        Data->GetObjectField(TEXT("physical"))->SetObjectField(TEXT("route_blocker"),Obj({
            {TEXT("kind"),Str(TEXT("box"))},{TEXT("min"),Point(A->SensedBlocker.Min/100.)},
            {TEXT("max"),Point(A->SensedBlocker.Max/100.)}}));
    if(!World->CoreEventProfile.IsEmpty()&&A->Category.IsEmpty())
    {
        const FVector Pose=A->GetActorLocation();
        auto Surface=Obj({{TEXT("movement_cost"),Num(A->bAerial?1:World->MovementCost(Pose))},
            {TEXT("water_depth_m"),Num(A->bAerial?0:World->WaterDepth(Pose)/100.)},
            {TEXT("visibility"),Num(World->VisibilityQuality(Pose))}});
        Data->GetObjectField(TEXT("physical"))->SetObjectField(TEXT("sensed_surface"),Surface);
    }
    if(World->bCityLayout&&A->CanCarry())for(const auto& Entry:World->CityLayout->GetArrayField(TEXT("spawns")))
    {
        auto Spawn=Entry->AsObject();if(Text(Spawn,TEXT("id"))!=A->AgentKey()||!Is(Spawn,TEXT("exit"),EJson::Array))continue;
        TArray<Value> Exit;
        for(const auto& V:Spawn->GetArrayField(TEXT("exit")))
        {FVector P;MRCoreJson::Point(V,P);P.Z=A->Dock.Z/100.;Exit.Add(Point(P));}
        Data->GetObjectField(TEXT("physical"))->SetArrayField(TEXT("dock_exit_waypoints"),Exit);
        const bool Docked=!Spawn->HasTypedField<EJson::Null>(TEXT("dock"))&&FVector::Dist2D(A->GetActorLocation(),A->Dock)<150;
        Data->GetObjectField(TEXT("physical"))->SetBoolField(TEXT("at_dock"),Docked);
    }
    auto Stamp=Json(Obj({{TEXT("observed_at"),Num(ObservedAt)},{TEXT("received_at"),Num(ObservedAt)},
        {TEXT("source_id"),Str(A->AgentKey())},{TEXT("state"),Str(TEXT("current"))}}));
    Data->SetObjectField(TEXT("freshness"),Obj({{TEXT("position"),Stamp},{TEXT("resources"),Stamp},{TEXT("role"),Stamp},{TEXT("communication"),Stamp}}));
    return Data;
}

Object FMRCoreRuntime::Capabilities() const
{
    const bool HasAnnex=World->bCityLayout&&Is(World->CityLayout,TEXT("competition"),EJson::Object);
    auto Number=Json(Obj({{TEXT("type"),Str(TEXT("number"))}}));
    auto Id=Json(Obj({{TEXT("type"),Str(TEXT("string"))},{TEXT("minLength"),Num(1)}}));
    auto P=Json(Obj({{TEXT("type"),Str(TEXT("array"))},{TEXT("minItems"),Num(3)},{TEXT("maxItems"),Num(3)},{TEXT("items"),Number}}));
    auto Actions=Obj();
    auto Add=[&](const FString& Action,const Value& Caps,const Object& Properties,const Value& Required)
    {Actions->SetObjectField(Action,Obj({{TEXT("required_capabilities"),Caps},{TEXT("parameters_schema"),Json(Obj({
        {TEXT("$schema"),Str(TEXT("https://json-schema.org/draft/2020-12/schema"))},{TEXT("type"),Str(TEXT("object"))},
        {TEXT("properties"),Json(Properties)},{TEXT("required"),Required},{TEXT("additionalProperties"),Bool(true)}}))}}));};
    Add(TEXT("move"),Strings({TEXT("move")}),Obj({{TEXT("target"),P}}),Strings({TEXT("target")}));
    Add(TEXT("hold"),Strings({TEXT("move")}),Obj(),Arr({}));
    Add(TEXT("observe"),Strings({TEXT("sense")}),Obj({{TEXT("radius"),Json(Obj({{TEXT("type"),Str(TEXT("number"))},{TEXT("exclusiveMinimum"),Num(0)},{TEXT("maximum"),Num(45)}}))}}),Strings({TEXT("radius")}));
    Add(TEXT("inspect"),Strings({TEXT("inspect")}),Obj({{TEXT("target_id"),Id}}),Strings({TEXT("target_id")}));
    Add(TEXT("follow_route"),Strings({TEXT("move")}),Obj({{TEXT("waypoints"),Json(Obj({{TEXT("type"),Str(TEXT("array"))},
        {TEXT("items"),P},{TEXT("minItems"),Num(1)},{TEXT("maxItems"),Num(4096)}}))},
        {TEXT("precise_stop"),Json(Obj({{TEXT("type"),Str(TEXT("boolean"))}}))}}),Strings({TEXT("waypoints")}));
    Add(TEXT("pickup"),Strings({TEXT("carry")}),Obj({{TEXT("target_id"),Id}}),Strings({TEXT("target_id")}));
    Add(TEXT("handover"),Strings({TEXT("carry")}),Obj({{TEXT("station_id"),Id}}),Strings({TEXT("station_id")}));
    Add(TEXT("deliver"),Strings({TEXT("deliver")}),Obj({{TEXT("target_id"),Id},{TEXT("resource_id"),Id},
        {TEXT("amount"),Json(Obj({{TEXT("type"),Str(TEXT("integer"))},{TEXT("minimum"),Num(1)},{TEXT("maximum"),Num(3)}}))}}),
        Strings({TEXT("target_id"),TEXT("resource_id"),TEXT("amount")}));
    Add(TEXT("relay"),Strings({TEXT("relay")}),Obj({{TEXT("enabled"),Json(Obj({{TEXT("type"),Str(TEXT("boolean"))}}))}}),Strings({TEXT("enabled")}));
    Add(TEXT("send_message"),Strings({TEXT("communicate")}),Obj({{TEXT("recipient_id"),Id},
        {TEXT("payload"),Json(Obj({{TEXT("type"),Str(TEXT("object"))}}))}}),Strings({TEXT("recipient_id"),TEXT("payload")}));
    if(HasAnnex)
    {
        Add(TEXT("compute"),Strings({TEXT("compute")}),Obj({
            {TEXT("operation"),Json(Obj({{TEXT("enum"),Strings({TEXT("sum"),TEXT("minimum")})}}))},
            {TEXT("values"),Json(Obj({{TEXT("type"),Str(TEXT("array"))},{TEXT("items"),Number},{TEXT("minItems"),Num(1)},
                {TEXT("maxItems"),Num(64)}}))}}),Strings({TEXT("operation"),TEXT("values")}));
        const auto InstructionProperties=Obj({{TEXT("target_id"),Id},{TEXT("reason"),Json(Obj({
                {TEXT("type"),Str(TEXT("string"))},{TEXT("minLength"),Num(1)},{TEXT("maxLength"),Num(128)}}))},
            {TEXT("action"),Json(Obj({{TEXT("enum"),Strings({TEXT("hold"),TEXT("set_priority"),TEXT("restrict_zone"),TEXT("message")})}}))},
            {TEXT("duration_s"),Json(Obj({{TEXT("type"),Str(TEXT("number"))},{TEXT("minimum"),Num(1)},{TEXT("maximum"),Num(60)}}))},
            {TEXT("priority"),Json(Obj({{TEXT("type"),Str(TEXT("integer"))},{TEXT("minimum"),Num(1)},{TEXT("maximum"),Num(3)}}))},
            {TEXT("confidence"),Json(Obj({{TEXT("type"),Str(TEXT("number"))},{TEXT("minimum"),Num(0)},{TEXT("maximum"),Num(1)}}))},
            {TEXT("requires_confirmation"),Json(Obj({{TEXT("type"),Str(TEXT("boolean"))}}))},
            {TEXT("text"),Json(Obj({{TEXT("type"),Str(TEXT("string"))},{TEXT("minLength"),Num(1)},{TEXT("maxLength"),Num(512)}}))},
            {TEXT("bounds"),Json(Obj({{TEXT("type"),Str(TEXT("object"))},{TEXT("properties"),Json(Obj({{TEXT("min"),P},{TEXT("max"),P}}))},
                {TEXT("required"),Strings({TEXT("min"),TEXT("max")})}}))},
            {TEXT("allowed_kinds"),Json(Obj({{TEXT("type"),Str(TEXT("array"))},{TEXT("maxItems"),Num(8)},{TEXT("uniqueItems"),Bool(true)},
                {TEXT("items"),Json(Obj({{TEXT("enum"),Strings({TEXT("ground"),TEXT("aerial"),TEXT("underground"),TEXT("surface_water"),
                    TEXT("underwater"),TEXT("infrastructure"),TEXT("digital"),TEXT("operator")})}}))}}))}});
        TArray<Value> Conditions;
        auto RequiredFor=[&](const FString& Action,const TArray<FString>& Fields)
        {
            TArray<Value> Required;for(const FString& Field:Fields)Required.Add(Str(Field));
            Conditions.Add(Json(Obj({{TEXT("if"),Json(Obj({{TEXT("properties"),Json(Obj({{TEXT("action"),Json(Obj({{TEXT("const"),Str(Action)}}))}}))}}))},
                {TEXT("then"),Json(Obj({{TEXT("required"),Arr(Required)}}))}})));
        };
        RequiredFor(TEXT("hold"),{TEXT("target_id"),TEXT("duration_s")});
        RequiredFor(TEXT("set_priority"),{TEXT("target_id"),TEXT("priority"),TEXT("duration_s")});
        RequiredFor(TEXT("restrict_zone"),{TEXT("bounds"),TEXT("allowed_kinds"),TEXT("duration_s")});
        RequiredFor(TEXT("message"),{TEXT("text"),TEXT("duration_s")});
        const auto InstructionSchema=Obj({{TEXT("type"),Str(TEXT("object"))},{TEXT("properties"),Json(InstructionProperties)},
            {TEXT("required"),Strings({TEXT("action"),TEXT("reason")})},{TEXT("allOf"),Arr(Conditions)}});
        const auto DirectiveProperties=MRCoreJson::Copy(InstructionProperties);
        DirectiveProperties->SetObjectField(TEXT("action"),Obj({{TEXT("enum"),Strings({TEXT("hold"),TEXT("set_priority"),TEXT("restrict_zone"),
            TEXT("message"),TEXT("cancel"),TEXT("clarify"),TEXT("confirm"),TEXT("request_confirmation")})}}));
        DirectiveProperties->SetField(TEXT("directive_id"),Id);
        DirectiveProperties->SetObjectField(TEXT("expected_revision"),Obj({{TEXT("type"),Str(TEXT("integer"))},{TEXT("minimum"),Num(1)},{TEXT("maximum"),Num(1.e6)}}));
        DirectiveProperties->SetObjectField(TEXT("instruction"),InstructionSchema);
        for(const FString& Change:{TEXT("cancel"),TEXT("clarify"),TEXT("confirm"),TEXT("request_confirmation")})
            RequiredFor(Change,{TEXT("directive_id"),TEXT("expected_revision")});
        RequiredFor(TEXT("clarify"),{TEXT("instruction")});
        Add(TEXT("issue_directive"),Strings({TEXT("issue_directive")}),DirectiveProperties,Strings({TEXT("action"),TEXT("reason")}));
        Actions->GetObjectField(TEXT("issue_directive"))->GetObjectField(TEXT("parameters_schema"))->SetArrayField(TEXT("allOf"),Conditions);
    }
    for(const FString& Concurrent:{TEXT("inspect"),TEXT("observe"),TEXT("relay"),TEXT("send_message")})
        Actions->GetObjectField(Concurrent)->SetBoolField(TEXT("may_run_while_moving"),true);
    if(!ChargingStations.IsEmpty())Add(TEXT("charge"),Strings({TEXT("charge")}),Obj({{TEXT("station_id"),Id}}),Strings({TEXT("station_id")}));
    const bool DynamicReset=!ResetPython.IsEmpty();
    auto Unsupported=DynamicReset?Arr({}):Strings({TEXT("dynamic_reset_generation")});
    auto ResetParameters=Obj({{TEXT("seed"),Num(World->Seed)},
        {TEXT("startup_configuration_only"),Bool(!DynamicReset)}});
    if(DynamicReset)
    {
        ResetParameters->SetNumberField(TEXT("minimum_seed"),0);
        ResetParameters->SetNumberField(TEXT("maximum_seed"),999999999);
        ResetParameters->SetArrayField(TEXT("mission_settings"),Strings({TEXT("map_size"),TEXT("preset"),
            TEXT("scouts"),TEXT("rescuers"),TEXT("people"),TEXT("horizon"),TEXT("layout"),TEXT("city_revision"),
            TEXT("event_profile"),TEXT("resource_profile"),TEXT("ground_battery_wh"),TEXT("aerial_battery_wh"),
            TEXT("initial_battery_fraction"),TEXT("energy_reserve_fraction"),TEXT("probabilities"),
            TEXT("sensor_reliability"),TEXT("communication_range_m"),TEXT("communication_latency_s"),
            TEXT("communication_loss"),TEXT("competition")})->AsArray());
    }
    Object Orbital=Obj({{TEXT("enabled"),Bool(HasAnnex)},{TEXT("extension"),Str(TEXT("metarescue.orbital_surface_pass.v1"))},
        {TEXT("normative_category"),Null()},{TEXT("kind"),Str(TEXT("space"))},{TEXT("sample_period_s"),Num(5)},
        {TEXT("downlink_delay_s"),Num(.45)},{TEXT("outputs"),Strings({TEXT("visible_water_depth"),TEXT("visible_atmospheric_transmission")})}});
    if(HasAnnex)Orbital->SetObjectField(TEXT("orbit"),World->CityLayout->GetObjectField(TEXT("competition"))->GetObjectField(TEXT("orbital_sensor")));
    TArray<FString> ScenarioIds;ScenarioCatalog.GetKeys(ScenarioIds);ScenarioIds.Sort();
    TArray<Value> Ids;auto ScenarioDeclarations=Obj();
    for(const FString& ScenarioId:ScenarioIds)
    {Ids.Add(Str(ScenarioId));ScenarioDeclarations->SetObjectField(ScenarioId,ScenarioCatalog.FindChecked(ScenarioId));}
    return Obj({{TEXT("protocol_version"),Str(TEXT("1.0"))},{TEXT("environment_id"),Str(TEXT("metarescue_unreal"))},
        {TEXT("profile"),Json(Obj({{TEXT("id"),Str(TEXT("metaevolution"))},{TEXT("version"),Str(TEXT("1.0"))},{TEXT("document_revision"),Str(TEXT("1.1"))}}))},
        {TEXT("implementation_stage"),Str(TEXT("physical_core_vertical_slice"))},
        {TEXT("orbital_sensor"),Json(Orbital)},
        {TEXT("agent_kinds"),HasAnnex?Strings({TEXT("aerial"),TEXT("ground"),TEXT("underground"),TEXT("surface_water"),
            TEXT("underwater"),TEXT("infrastructure"),TEXT("digital"),TEXT("operator")}):Strings({TEXT("aerial"),TEXT("ground")})},
        {TEXT("zone_types"),Strings({TEXT("land"),TEXT("water"),TEXT("air"),TEXT("underground"),TEXT("obstacle"),
            TEXT("hazard"),TEXT("restricted"),TEXT("low_connectivity"),TEXT("infrastructure")})},
        {TEXT("infrastructure_kinds"),Strings({TEXT("relay"),TEXT("charging_station"),TEXT("sensor_node"),TEXT("base_station"),TEXT("compute_node")})},
        {TEXT("predicate_operators"),Strings({TEXT("and"),TEXT("or"),TEXT("not"),TEXT("eq"),TEXT("ne"),TEXT("lt"),TEXT("le"),
            TEXT("gt"),TEXT("ge"),TEXT("exists"),TEXT("in"),TEXT("all"),TEXT("any"),TEXT("count"),TEXT("sum")})},
        {TEXT("scenario_ids"),Arr(Ids)},{TEXT("supported_scenarios"),Json(ScenarioDeclarations)},
        {TEXT("supported_operations"),Strings({TEXT("keep"),TEXT("select"),TEXT("switch"),TEXT("modify"),
            TEXT("compose"),TEXT("synthesize"),TEXT("safe_stop")})},
        {TEXT("supported_actions"),Json(Actions)},
        {TEXT("extensions"),Strings({TEXT("metaevolution.freshness.v1"),TEXT("metaevolution.step_deduplication.v1"),
            TEXT("metaevolution.reset_deduplication.v1"),TEXT("metaevolution.command_groups.v1"),TEXT("metaevolution.plan_confirmation.v1"),
            TEXT("metarescue.follow_route.v1"),TEXT("metarescue.casualty_transfer.v1"),TEXT("metarescue.announced_map.v1"),
            TEXT("metarescue.indexed_journals.v1"),TEXT("metarescue.command_result_deltas.v1"),TEXT("metarescue.observed_surfaces.v1"),
            TEXT("metarescue.radio_transport.v1"),TEXT("metarescue.disturbances.v1"),TEXT("metarescue.aid_and_peer_messages.v1"),
            TEXT("metarescue.competition_services.v1"),TEXT("metarescue.orbital_surface_pass.v1"),TEXT("metarescue.operator_directives.v1")})},
        {TEXT("observation_event_types"),Strings({TEXT("agent_failure"),TEXT("agent_degradation"),TEXT("infrastructure_failure"),
            TEXT("connectivity_loss"),TEXT("mission_priority_change"),TEXT("operator_directive"),TEXT("hazard_appeared"),
            TEXT("restricted_zone_appeared"),TEXT("resource_shortage"),TEXT("target_detected"),TEXT("target_state_changed"),
            TEXT("contradictory_information"),TEXT("stale_information"),TEXT("environment_change")})},
        {TEXT("radio_model"),Json(Obj({{TEXT("position_sample_s"),Num(.1)},{TEXT("range_m"),Num(RadioRange)},
            {TEXT("latency_per_hop_s"),Num(Latency)},{TEXT("base_loss_per_hop"),Num(RadioLoss)},
            {TEXT("report_ttl_s"),Num(30)},{TEXT("packets_per_source"),Num(128)},{TEXT("critical_report_attempts"),Num(3)}}))},
        {TEXT("event_model"),Json(Obj({{TEXT("profile"),Str(World->CoreEventProfile.IsEmpty()?TEXT("static"):World->CoreEventProfile)},
            {TEXT("format"),Str(World->bDisasterCity?TEXT("metarescue.events-3d.2.0"):TEXT("metarescue.events-3d.1.0"))},
            {TEXT("physics_profile"),World->bDisasterCity?Str(TEXT("metarescue.urban-disasters.v1")):Null()},
            {TEXT("visibility_model"),Str(World->bDisasterCity?TEXT("beer_lambert_wind_plumes"):TEXT("surface_quality_v1"))},
            {TEXT("physics_cell_m"),Num(5)},
            {TEXT("probability_window_s"),World->CoreEventProfile.IsEmpty()?Null():Num(World->CoreEventProfile==TEXT("v052")?80:30)}}))},
        {TEXT("time_model"),Json(Obj({{TEXT("external_step"),Num(1)},{TEXT("maximum_internal_step"),Num(1./60.)},
            {TEXT("maximum_physics_substep"),Num(1./120.)},{TEXT("epsilon_time"),Num(1.e-9)},
            {TEXT("boundary_splitting"),Str(TEXT("delivery_ack_events_sampling_and_step_end"))},
            {TEXT("wall_pacing"),Str(Realtime?TEXT("realtime"):TEXT("accelerated"))}}))},
        {TEXT("limits"),Json(Obj({{TEXT("request_bytes"),Num(2097152)},{TEXT("commands_per_step"),Num(256)},
            {TEXT("pending_commands_per_agent"),Num(32)},{TEXT("delivery_ttl"),Num(5)},{TEXT("decisions_per_episode"),Num(100000)},
            {TEXT("resets_per_process"),Num(4096)},{TEXT("journal_record_bytes"),Num(FMRCoreDiskRecords::MaxRecordBytes)},
            {TEXT("journal_stream_bytes"),Num(FMRCoreDiskRecords::MaxDataBytes)},
            {TEXT("log_page_records"),Num(1000)},{TEXT("log_page_soft_bytes"),Num(8*1024*1024)}}))},
        {TEXT("reset_parameters"),Json(ResetParameters)},
        {TEXT("physical_tolerances"),Json(Obj({{TEXT("ground_arrival_m"),Num(.95)},{TEXT("aerial_arrival_m"),Num(.75)},
            {TEXT("precise_ground_arrival_m"),Num(.10)},
            {TEXT("pickup_distance_m"),Num(3.7)},{TEXT("handover_distance_m"),Num(5)},{TEXT("service_speed_m_s"),Num(.3)}}))},
        {TEXT("resource_model"),Json(Obj({{TEXT("profile"),Str(Unlimited?TEXT("unlimited"):TEXT("contest"))},
            {TEXT("energy_unit"),Str(TEXT("Wh"))},{TEXT("charge_enabled"),Bool(!ChargingStations.IsEmpty())},
            {TEXT("reserve_fraction"),Num(Unlimited?0:ReserveFraction)}}))},
        {TEXT("not_yet_supported"),Unsupported}});
}

void FMRCoreRuntime::DeclareZones()
{
    if(!World->bCityLayout)return;
    auto Add=[&](const FString& Id,const FString& Kind,const Object& Bounds,const TArray<Value>& Allowed)
    {
        if(!Bounds)return;
        DeclaredZones.Add(Json(Obj({{TEXT("id"),Str(Id)},{TEXT("type"),Str(Kind)},
            {TEXT("geometry"),Json(Obj({{TEXT("type"),Str(TEXT("box"))},{TEXT("min"),Field(Bounds,TEXT("min"))},
                {TEXT("max"),Field(Bounds,TEXT("max"))}}))},
            {TEXT("access"),Json(Obj({{TEXT("allowed_kinds"),Arr(Allowed)}}))},
            {TEXT("risk"),Num(Kind==TEXT("obstacle")?1:0)},{TEXT("cost"),Json(Obj())},
            {TEXT("communication"),Json(Obj())},{TEXT("constraints"),Arr({})}})));
    };
    const auto Layout=World->CityLayout;
    if(Is(Layout,TEXT("competition"),EJson::Object))
        DeclaredZones.Append(Layout->GetObjectField(TEXT("competition"))->GetArrayField(TEXT("zones")));
    else
    {
        const double Size=Layout->GetNumberField(TEXT("size_m"));
        auto Bounds=[&](double Low,double High){return Obj({{TEXT("min"),Point(FVector(0,0,Low))},
                                                           {TEXT("max"),Point(FVector(Size,Size,High))}});};
        Add(TEXT("map-surface"),TEXT("land"),Bounds(-.12,.08),{Str(TEXT("ground"))});
        Add(TEXT("map-airspace"),TEXT("air"),Bounds(0,90),{Str(TEXT("aerial"))});
    }
    int32 Index=0;
    auto AddObstacle=[&](const Object& Bounds)
    {Add(FString::Printf(TEXT("map-obstacle-%d"),++Index),TEXT("obstacle"),Bounds,{});};
    for(const FString& FieldName:{TEXT("buildings"),TEXT("facilities"),TEXT("fixed_obstacles")})
        if(Is(Layout,FieldName,EJson::Array))for(const auto& Entry:Layout->GetArrayField(FieldName))
            AddObstacle(Entry->AsObject()->GetObjectField(TEXT("bounds")));
    if(Is(Layout,TEXT("features"),EJson::Array))for(const auto& Entry:Layout->GetArrayField(TEXT("features")))
        if(Is(Entry->AsObject(),TEXT("obstacles"),EJson::Array))
            for(const auto& Bounds:Entry->AsObject()->GetArrayField(TEXT("obstacles")))AddObstacle(Bounds->AsObject());
}

void FMRCoreRuntime::Snapshot(const FString& RequestId)
{
    TArray<Value> Agents,Targets,Infrastructure,Zones,Events,Links,Orders,Contradictions;
    auto Acknowledgements=Obj();
    int32 Reachable=0,Rescued=0,ExpectedGroups=0,KnownGroups=0,TimedGroups=0,StaleGroups=0;
    double MaximumDelay=0,MaximumAge=0,QualitySum=0;bool Mesh=false;
    for(const auto& Pair:KnownAgents)
    {
        auto Agent=MRCoreJson::Copy(Pair.Value);
        const auto Freshness=Agent->GetObjectField(TEXT("freshness"));
        const auto Position=Freshness->GetObjectField(TEXT("position"));
        const double Age=Time()-Position->GetNumberField(TEXT("observed_at"));
        ExpectedGroups+=4;
        for(auto& PairOfFacts:Freshness->Values)
        {
            const auto Stamp=PairOfFacts.Value->AsObject();
            if(Text(Stamp,TEXT("state"))==TEXT("unknown"))continue;
            ++KnownGroups;
            if(!Is(Stamp,TEXT("observed_at"),EJson::Number)||!Is(Stamp,TEXT("received_at"),EJson::Number))continue;
            ++TimedGroups;
            const double Observed=Stamp->GetNumberField(TEXT("observed_at"));
            const double FactAge=Time()-Observed;
            MaximumAge=FMath::Max(MaximumAge,FactAge);
            MaximumDelay=FMath::Max(MaximumDelay,Stamp->GetNumberField(TEXT("received_at"))-Observed);
            if(FactAge>5){++StaleGroups;Stamp->SetStringField(TEXT("state"),TEXT("last_known"));}
        }
        const auto Radio=Agent->GetObjectField(TEXT("communication"));
        Acknowledgements->SetObjectField(Pair.Key,Obj({
            {TEXT("plan_revision"),Field(Agent,TEXT("configuration_revision"))},
            {TEXT("role"),Field(Agent,TEXT("role"))},{TEXT("scenario_ids"),Field(Agent,TEXT("scenario_ids"))},
            {TEXT("freshness"),Field(Freshness,TEXT("role"))}}));
        if(Age>5)
        {
            Agent->SetStringField(TEXT("status"),TEXT("offline"));Agent->SetArrayField(TEXT("available_actions"),{});
            Radio->SetBoolField(TEXT("reachable"),false);
        }
        else if(Radio->GetBoolField(TEXT("reachable")))
        {
            ++Reachable;QualitySum+=Radio->GetNumberField(TEXT("quality"));
            Mesh|=Radio->GetNumberField(TEXT("hops"))>1;
            Links.Add(Json(Obj({{TEXT("from"),Field(Radio,TEXT("upstream_id"))},{TEXT("to"),Str(Pair.Key)},
                {TEXT("quality"),Field(Radio,TEXT("last_link_quality"))},{TEXT("latency"),Num(Latency)},
                {TEXT("observed_at"),Field(Position,TEXT("observed_at"))},{TEXT("received_at"),Field(Position,TEXT("received_at"))}})));
        }
        Agents.Add(Json(Agent));
    }
    Agents.Sort([](const Value& A,const Value& B){return Text(A->AsObject(),TEXT("id"))<Text(B->AsObject(),TEXT("id"));});
    Links.Sort([](const Value& A,const Value& B){return Text(A->AsObject(),TEXT("to"))<Text(B->AsObject(),TEXT("to"));});
    for(const auto& Pair:KnownTargets){Targets.Add(Json(Pair.Value));Rescued+=Text(Pair.Value,TEXT("evacuation_state"))==TEXT("evacuated");}
    Targets.Sort([](const Value& A,const Value& B){return Text(A->AsObject(),TEXT("id"))<Text(B->AsObject(),TEXT("id"));});
    for(const auto& Pair:KnownZones)Zones.Add(Json(Pair.Value));
    Zones.Append(DeclaredZones);
    Zones.Sort([](const Value& A,const Value& B){return Text(A->AsObject(),TEXT("id"))<Text(B->AsObject(),TEXT("id"));});
    for(const auto& Pair:StepEvents)Events.Add(Json(Pair.Value));
    Events.Sort([](const Value& A,const Value& B){return Text(A->AsObject(),TEXT("id"))<Text(B->AsObject(),TEXT("id"));});
    for(const auto& Pair:Directives)Orders.Add(Json(Pair.Value));
    Orders.Sort([](const Value& A,const Value& B){return Text(A->AsObject(),TEXT("id"))<Text(B->AsObject(),TEXT("id"));});
    TMap<FString,Object> PriorityOrders;
    for(const auto& Entry:Orders)
    {
        const auto Order=Entry->AsObject();
        if(Text(Order,TEXT("action"))!=TEXT("set_priority")||Text(Order,TEXT("status"))!=TEXT("active"))continue;
        const FString Target=Text(Order,TEXT("target_id"));
        const auto Previous=PriorityOrders.FindRef(Target);
        if(!Previous||Order->GetNumberField(TEXT("updated_at"))>Previous->GetNumberField(TEXT("updated_at"))||
           (Order->GetNumberField(TEXT("updated_at"))==Previous->GetNumberField(TEXT("updated_at"))&&
            Order->GetNumberField(TEXT("revision"))>=Previous->GetNumberField(TEXT("revision"))))PriorityOrders.Add(Target,Order);
    }
    TArray<Value> Priorities;
    for(const auto& Pair:PriorityOrders)Priorities.Add(Json(Obj({{TEXT("target_id"),Str(Pair.Key)},
        {TEXT("priority"),Field(Pair.Value,TEXT("priority"))},{TEXT("directive_id"),Field(Pair.Value,TEXT("id"))},
        {TEXT("updated_at"),Field(Pair.Value,TEXT("updated_at"))}})));
    Priorities.Sort([](const Value& A,const Value& B){return Text(A->AsObject(),TEXT("target_id"))<Text(B->AsObject(),TEXT("target_id"));});
    for(const auto& Pair:Conflicts)Contradictions.Add(Json(Pair.Value));
    Contradictions.Sort([](const Value& A,const Value& B){return Text(A->AsObject(),TEXT("id"))<Text(B->AsObject(),TEXT("id"));});
    if(World->bCityLayout)for(const auto& Row:World->CityLayout->GetArrayField(TEXT("infrastructure")))
    {
        const auto Node=Row->AsObject();
        auto Entry=Obj({{TEXT("id"),Field(Node,TEXT("id"))},{TEXT("kind"),Field(Node,TEXT("kind"))},
            {TEXT("position"),Field(Node,TEXT("position"))},{TEXT("status"),Str(TEXT("active"))},
            {TEXT("capabilities"),Strings({Text(Node,TEXT("kind"))})},{TEXT("resources"),Json(Obj())},
            {TEXT("communication"),Json(Obj())},{TEXT("constraints"),Arr({})}});
        if(auto Charge=ChargeState(Text(Node,TEXT("id"))))
        {
            const double Capacity=Charge->GetNumberField(TEXT("capacity_wh")),Energy=Charge->GetNumberField(TEXT("remaining_wh"));
            Entry->SetObjectField(TEXT("charger"),Charge);
            Entry->SetArrayField(TEXT("capabilities"),{Str(TEXT("charge"))});
            Entry->SetObjectField(TEXT("resources"),Obj({{TEXT("energy"),Resource(TEXT("energy"),Capacity>0?Energy/Capacity:0)}}));
            if(Energy<=1.e-9)Entry->SetStringField(TEXT("status"),TEXT("depleted"));
        }
        if(DisabledInfrastructure.Contains(Text(Node,TEXT("id"))))Entry->SetStringField(TEXT("status"),TEXT("failed"));
        Infrastructure.Add(Json(Entry));
    }
    auto Mission=Obj({{TEXT("id"),Str(TEXT("search_and_rescue"))},{TEXT("objectives"),Arr({Json(Obj({{TEXT("id"),Str(TEXT("rescue"))},
        {TEXT("type"),Str(TEXT("search_and_evacuate"))}}))})},{TEXT("priorities"),Arr(Priorities)},{TEXT("directives"),Arr(Orders)},
        {TEXT("constraints"),Arr({})},{TEXT("status"),Str(Status==TEXT("success")?TEXT("completed"):Status==TEXT("running")?TEXT("active"):Status==TEXT("safe_stopped")?TEXT("safe_stopped"):TEXT("failed"))},
        {TEXT("termination"),Json(Obj({{TEXT("horizon"),Num(Horizon)},{TEXT("reason"),OutcomeReason.IsEmpty()?Null():Str(OutcomeReason)}}))}});
    auto Metrics=Obj({{TEXT("known_targets"),Num(KnownTargets.Num())},{TEXT("confirmed_evacuations"),Num(Rescued)}});
    const double ReachableRatio=Agents.IsEmpty()?0:double(Reachable)/Agents.Num();
    auto Plan=Obj({{TEXT("revision"),Num(PlanRevision)},{TEXT("plan_revision"),Num(PlanRevision)},
        {TEXT("accepted_configuration"),Json(Accepted)},{TEXT("desired_role_assignments"),Json(DesiredRoles)},
        {TEXT("agent_acknowledgements"),Json(Acknowledgements)}});
    CachedObservation=Obj({{TEXT("protocol_version"),Str(TEXT("1.0"))},{TEXT("episode_id"),Str(Episode)},
        {TEXT("request_id"),Str(RequestId)},{TEXT("time"),Num(Time())},{TEXT("mission"),Json(Mission)},
        {TEXT("agents"),Arr(Agents)},{TEXT("targets"),Arr(Targets)},{TEXT("infrastructure"),Arr(Infrastructure)},
        {TEXT("zones"),Arr(Zones)},{TEXT("events"),Arr(Events)},{TEXT("constraints"),Arr({})},{TEXT("metrics"),Json(Metrics)},
        {TEXT("network"),Json(Obj({{TEXT("connectivity_score"),Num(ReachableRatio)},
            {TEXT("partition_count"),Num(Reachable<Agents.Num()?2:1)},{TEXT("partition_count_basis"),Str(TEXT("observed_lower_bound"))},
            {TEXT("reachable_agent_ratio"),Num(ReachableRatio)},{TEXT("average_link_quality"),Num(Reachable?QualitySum/Reachable:0)},
            {TEXT("mesh_available"),Bool(Mesh)},{TEXT("known_links"),Arr(Links)}}))},
        {TEXT("observation_quality"),Json(Obj({{TEXT("global_completeness"),Num(ExpectedGroups?double(KnownGroups)/ExpectedGroups:1)},
            {TEXT("maximum_delay"),Num(MaximumDelay)},{TEXT("maximum_age"),Num(MaximumAge)},
            {TEXT("stale_data_ratio"),Num(TimedGroups?double(StaleGroups)/TimedGroups:0)},
            {TEXT("contradiction_count"),Num(Contradictions.Num())},{TEXT("unknown_state_ratio"),Num(ExpectedGroups?1.-double(KnownGroups)/ExpectedGroups:0)},
            {TEXT("quality_basis"),Json(Obj({{TEXT("expected_groups"),Num(ExpectedGroups)},{TEXT("known_groups"),Num(KnownGroups)},
                {TEXT("unknown_timestamp_groups"),Num(KnownGroups-TimedGroups)}}))}}))},
        {TEXT("metaevolution"),Json(Obj({{TEXT("plan"),Json(Plan)},{TEXT("contradictions"),Arr(Contradictions)}}))}});
    if(KnownOrbital)CachedObservation->GetObjectField(TEXT("metaevolution"))->SetObjectField(TEXT("orbital_observation"),KnownOrbital);
    if(World->bCityLayout)
    {
        auto Map=Obj();for(const FString& Key:{TEXT("format"),TEXT("base_layout_revision"),TEXT("cell_m"),TEXT("size_m"),TEXT("bounds"),TEXT("base"),TEXT("base_position"),
            TEXT("road_axes_m"),TEXT("road_width_m"),TEXT("road_graph"),TEXT("buildings"),TEXT("features"),TEXT("facilities"),
            TEXT("fixed_obstacles"),TEXT("surfaces"),TEXT("infrastructure")})
            if(const auto Value=Field(World->CityLayout,Key))Map->SetField(Key,Value);
        const bool Irregular=World->bIrregularCity;
        Map->SetObjectField(TEXT("navigation"),Obj({{TEXT("kind"),Str(Irregular?TEXT("street_surface_graph.v2"):TEXT("road_surface_graph.v1"))},
            {TEXT("road_surface_z_m"),Num(Irregular?0:.04)},{TEXT("base_surface_z_m"),Num(Irregular?.07:.11)},
            {TEXT("sidewalk_surface_z_m"),Num(Irregular?0:.23)},{TEXT("ground_clearance_m"),Num(.43)},
            {TEXT("max_step_m"),Num(.10)}}));
        CachedObservation->GetObjectField(TEXT("metaevolution"))->SetObjectField(TEXT("announced_map"),Map);
    }
}

Object FMRCoreRuntime::EpisodeResponse(const FString& RequestId,bool StepResponse) const
{
    auto Observation=MRCoreJson::Copy(CachedObservation);Observation->SetStringField(TEXT("request_id"),RequestId);
    auto Response=Obj({{TEXT("protocol_version"),Str(TEXT("1.0"))},{TEXT("episode_id"),Str(Episode)},
        {TEXT("request_id"),Str(RequestId)},{TEXT("time"),Num(Time())},{TEXT("status"),Str(Status)},{TEXT("observation"),Json(Observation)}});
    if(StepResponse)
    {
        TArray<Value> Results;for(const auto& C:Commands)if(C.Index>=0&&C.PublicDirty)Results.Add(Json(C.PublicResult));
        Response->SetArrayField(TEXT("command_results"),Results);
        Response->SetArrayField(TEXT("events"),Observation->GetArrayField(TEXT("events")));
        Response->SetObjectField(TEXT("metrics"),Observation->GetObjectField(TEXT("metrics")));
    }
    return Response;
}

TArray<Value> FMRCoreRuntime::PublicRoutesForInterface() const
{
    TArray<Value> RoutesForView;
    for(const auto& Command:Commands)
    {
        if((Command.Action!=TEXT("follow_route")&&Command.Action!=TEXT("move"))||
            !Command.PublicResult||Text(Command.PublicResult,TEXT("validation_status"))!=TEXT("accepted"))continue;
        const FString Execution=Text(Command.PublicResult,TEXT("execution_status"));
        if(Execution==TEXT("completed")||Execution==TEXT("failed")||Execution==TEXT("cancelled"))continue;
        auto Route=Obj({{TEXT("agent_id"),Str(Command.Agent)},{TEXT("command_id"),Str(Command.Key)},
            {TEXT("delivery_status"),Field(Command.PublicResult,TEXT("delivery_status"))}});
        if(Command.Action==TEXT("follow_route"))Route->SetField(TEXT("waypoints"),Field(Command.Parameters,TEXT("waypoints")));
        else Route->SetArrayField(TEXT("waypoints"),{Field(Command.Parameters,TEXT("target"))});
        RoutesForView.Add(Json(Route));
    }
    return RoutesForView;
}
