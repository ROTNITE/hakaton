#include "MRCoreRuntime.h"
#include "MRCoreJson.h"
#include "MRCoreValues.h"
#include "MRAgent.h"
#include "MRWorld.h"

using namespace MRCoreValues;

namespace
{
bool ReadNumber(const Object& Row,const FString& Key,double& Value,double Low,double High)
{
    if(!Row->HasField(Key))return Value>=Low&&Value<=High;
    if(!Is(Row,Key,EJson::Number))return false;
    Value=Row->GetNumberField(Key);
    return FMath::IsFinite(Value)&&Value>=Low&&Value<=High;
}
}

bool FMRCoreRuntime::LoadResources()
{
    ChargingStations.Reset();
    if(!World->bCityLayout)return true;
    const auto Settings=World->CityLayout->GetObjectField(TEXT("settings"));
    if(!ReadNumber(Settings,TEXT("ground_battery_wh"),GroundBatteryWh,1,10000)||
       !ReadNumber(Settings,TEXT("aerial_battery_wh"),AerialBatteryWh,1,10000)||
       !ReadNumber(Settings,TEXT("initial_battery_fraction"),InitialBatteryFraction,0,1)||
       !ReadNumber(Settings,TEXT("energy_reserve_fraction"),ReserveFraction,0,.75))
    {
        UE_LOG(LogTemp,Error,TEXT("MR_CORE invalid battery settings"));return false;
    }
    if(Unlimited)return true;
    for(const auto& Entry:World->CityLayout->GetArrayField(TEXT("infrastructure")))
    {
        const auto Row=Entry->AsObject();
        if(Text(Row,TEXT("kind"))!=TEXT("charging_station"))continue;
        const FString Id=Text(Row,TEXT("id"));
        FChargeStation Station;
        double Radius=4,Ports=1;
        Station.Kind=TEXT("ground");Station.PowerW=1200;Station.CapacityWh=10000;
        if(Is(Row,TEXT("charger"),EJson::Object))
        {
            const auto C=Row->GetObjectField(TEXT("charger"));
            Station.Kind=Text(C,TEXT("kind"));Station.AgentId=Text(C,TEXT("agent_id"));
            if(!ReadNumber(C,TEXT("docking_distance_m"),Radius,.2,8)||
               !ReadNumber(C,TEXT("ports"),Ports,1,16)||Ports!=FMath::FloorToDouble(Ports)||
               !ReadNumber(C,TEXT("power_w"),Station.PowerW,50,100000)||
               !ReadNumber(C,TEXT("capacity_wh"),Station.CapacityWh,0,1.e8))
            {
                UE_LOG(LogTemp,Error,TEXT("MR_CORE invalid charging station parameters: %s"),*Id);return false;
            }
        }
        if(Id.IsEmpty()||ChargingStations.Contains(Id)||
           (Station.Kind!=TEXT("ground")&&Station.Kind!=TEXT("aerial"))||
           !MRCoreJson::Point(Field(Row,TEXT("position")),Station.Position))
        {
            UE_LOG(LogTemp,Error,TEXT("MR_CORE invalid charging station identity or position: %s"),*Id);return false;
        }
        Station.Position*=100;Station.RadiusCm=Radius*100;Station.Ports=int32(Ports);
        ChargingStations.Add(Id,Station);
    }
    return true;
}

void FMRCoreRuntime::ResetResources()
{
    for(AMRAgent* Agent:World->Agents)
    {
        if(World->bCityLayout)Agent->BatteryCapacityWh=Agent->bAerial?AerialBatteryWh:GroundBatteryWh;
        Agent->EnergyReserveWh=Unlimited?0:ReserveFraction*Agent->BatteryCapacityWh;
        Agent->Energy=Agent->BatteryCapacityWh*(Unlimited?1:InitialBatteryFraction);
    }
    for(auto& Pair:ChargingStations)Pair.Value.EnergyWh=Pair.Value.CapacityWh;
}

bool FMRCoreRuntime::CanStartCharge(const FString& StationId,const AMRAgent* Agent) const
{
    const auto* Station=ChargingStations.Find(StationId);
    return Station&&!DisabledInfrastructure.Contains(StationId)&&!Agent->bFaulted&&Station->EnergyWh>0&&Agent->Energy<Agent->BatteryCapacityWh-1.e-6&&
        !Agent->IsCharging()&&Agent->RemainingServiceSeconds()==0&&(Agent->bExternalHold||Agent->RouteFinished())&&
        Station->Kind==Agent->Kind()&&
        (Station->AgentId.IsEmpty()||Station->AgentId==Agent->AgentKey())&&Agent->ChargeDocked(Station->Position,Station->RadiusCm);
}

TSharedPtr<FJsonObject> FMRCoreRuntime::ChargeState(const FString& StationId) const
{
    const auto* Station=ChargingStations.Find(StationId);
    if(!Station)return nullptr;
    int32 Active=0,Queued=0;
    for(const auto& C:Commands)if(C.Station==StationId&&C.Delivered&&C.FinalStatus.IsEmpty())
    {
        const auto* A=FindAgent(C.Agent);
        if(A&&A->CommandId==C.Key){Active+=A->State==TEXT("charging");Queued+=A->State==TEXT("charge_wait");}
    }
    return Obj({{TEXT("kind"),Str(Station->Kind)},{TEXT("agent_id"),Station->AgentId.IsEmpty()?Null():Str(Station->AgentId)},
        {TEXT("docking_distance_m"),Num(Station->RadiusCm/100.)},{TEXT("ports"),Num(Station->Ports)},
        {TEXT("active"),Num(Active)},{TEXT("waiting"),Num(Queued)},
        {TEXT("power_w"),Num(Station->PowerW)},{TEXT("capacity_wh"),Num(Station->CapacityWh)},
        {TEXT("remaining_wh"),Num(Station->EnergyWh)}});
}

void FMRCoreRuntime::UpdateResources(double Dt)
{
    for(AMRAgent* Agent:World->Agents)Agent->AccountPoweredTime(Dt);
    TMap<FString,int32> InUse;
    for(auto& C:Commands)
    {
        if(C.Station.IsEmpty()||!C.Delivered||!C.FinalStatus.IsEmpty())continue;
        auto* Station=ChargingStations.Find(C.Station);auto* Agent=FindAgent(C.Agent);
        if(!Agent||Agent->CommandId!=C.Key||!Agent->IsCharging())continue;
        auto Finish=[&](const FString& Status,const FString& Reason)
        {
            Agent->EndCharge();C.FinalStatus=Status;C.Reason=Reason;
            QueueAck(C,Latency*FMath::Max(1,Hops.FindRef(C.Agent)));
            Record(TEXT("charge_ended"),Obj({{TEXT("command_id"),Str(C.Key)},{TEXT("station_id"),Str(C.Station)},
                {TEXT("agent_id"),Str(C.Agent)},{TEXT("status"),Str(Status)},{TEXT("reason"),Str(Reason)},
                {TEXT("battery_wh"),Num(Agent->Energy)},{TEXT("station_wh"),Num(Station?Station->EnergyWh:0)}}),false);
        };
        if(DisabledInfrastructure.Contains(C.Station)){Finish(TEXT("failed"),TEXT("charging_station_unavailable"));continue;}
        if(!Station||!Agent->ChargeDocked(Station->Position,Station->RadiusCm))
        {Finish(TEXT("failed"),TEXT("charge_dock_lost"));continue;}
        if(Station->EnergyWh<=1.e-9){Finish(TEXT("failed"),TEXT("charging_station_depleted"));continue;}
        if(InUse.FindRef(C.Station)>=Station->Ports)continue;
        ++InUse.FindOrAdd(C.Station);
        if(Agent->State==TEXT("charge_wait"))
            Record(TEXT("charge_started"),Obj({{TEXT("command_id"),Str(C.Key)},{TEXT("agent_id"),Str(C.Agent)},
                {TEXT("station_id"),Str(C.Station)},{TEXT("battery_wh"),Num(Agent->Energy)},
                {TEXT("station_wh"),Num(Station->EnergyWh)}}),false);
        Station->EnergyWh-=Agent->ReceiveCharge(FMath::Min(Station->EnergyWh,Station->PowerW*Dt/3600.));
        if(Station->EnergyWh<=1.e-9)
            PublishEvent(C.Key+TEXT("-depleted"),TEXT("resource_shortage"),Time(),C.Station,{C.Station},
                Obj({{TEXT("resource"),Str(TEXT("energy"))},{TEXT("remaining_wh"),Num(Station->EnergyWh)}}),TEXT("active"));
        if(Agent->Energy>=Agent->BatteryCapacityWh-1.e-9)Finish(TEXT("completed"),TEXT(""));
    }
    for(AMRAgent* Agent:World->Agents)
    {
        if(Agent->Energy>0||Agent->IsCharging()||Agent->State==TEXT("power_lost"))continue;
        const int32 Released=Agent->StopAndRelease(TEXT("battery_depleted"));
        const auto* Target=World->Targets.IsValidIndex(Released)?&World->Targets[Released]:nullptr;
        Record(TEXT("power_lost"),Obj({{TEXT("agent_id"),Str(Agent->AgentKey())},{TEXT("position"),Point(Agent->GetActorLocation()/100.)},
            {TEXT("released_target"),Target?Str(FString::Printf(TEXT("person-%d"),Target->Id)):Null()},
            {TEXT("target_position"),Target?Point(Target->Position/100.):Null()}}),false);
    }
}
