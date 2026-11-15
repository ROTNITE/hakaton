"""Author a small reproducible private native rescue acceptance fixture."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from environment.config import EVENT_DEFAULTS,Settings
from environment.disturbances import FORMAT as CONTEST_FORMAT,validate_tape as validate_disturbances
from environment.events import VERSION as EVENT_VERSION,validate_tape
from environment.layout import generate,preflight,public_map


def event_fixture(world):
    # The acceptance driver has a scripted route. Sensors and the public
    # controller interface still receive the ordinary observations.
    rover=next(agent for agent in world['spawns'] if agent['kind']=='ground')
    rover.update(position=[75.,10.4,.95],yaw=0.,exit=[],dock=None)
    facade=next(h for h in world['buildings'] if h['bounds']['min']==[108.25,40.25,0])
    unstable=next(h for h in world['buildings'] if h['bounds']['min']==[120.25,62.25,0])
    def event(identifier,kind,at,source,cells,*,parent=None,expiry=None,visibility=None,building=None):
        return {'id':identifier,'kind':kind,'time':at,'source':source,'cells':cells,
                'source_object_id':building,'parent_id':parent,'spread':parent is not None,
                'expires_at':expiry,'visibility_expires_at':visibility,'rejection':None}
    late={'id':4,'position':[110.,13.1,.06],'priority':3,'available_at':12.375,'appearance_event_id':'fixture-appearance'}
    rows=[
        event('fixture-deep','flood',.123,[117.5,12.5,.05],[[23,2],[23,1]]),
        event('fixture-mud','mud',.246,[82.5,12.5,.05],[[16,2],[16,1]]),
        event('fixture-road','road_damage',.625,[92.5,12.5,.05],[[18,2],[18,1]]),
        event('fixture-fire','fire',3.125,[112.5,50.45,.05],[[22,10]],visibility=27.125,building=facade['id']),
        event('fixture-smoke','smoke',5.125,[102.5,12.5,.05],[[20,2],[20,1],[21,2]],expiry=25.125,visibility=25.125),
        event('fixture-fog','low_visibility',6.25,[102.5,12.5,.05],[[20,2],[20,1],[21,2]],expiry=30.25,visibility=30.25),
        event('fixture-shallow','flood',8.125,[102.5,12.5,.05],[[20,2],[20,1]]),
        event('fixture-collapse','collapse',11.375,[124.5,61.55,.05],[[24,11],[25,11]],visibility=35.375,building=unstable['id']),
        {**event('fixture-appearance','new_target',late['available_at'],late['position'],[]),'target_id':late['id']},
        event('fixture-fire-spread','fire',15.375,[107.5,52.5,.05],[[21,10]],
              parent='fixture-fire',visibility=39.375,building=facade['id']),
    ]
    tape={'format':EVENT_VERSION,'profile':'v3','probability_window_s':30,'physics_cell_m':5,
          'placement_model':'authored_physical_acceptance_fixture.v1','events':rows,'late_people':[late]}
    world['event_model']=validate_tape(tape,world)
    world['fixture']={'id':'core-event-effects-v1','scope':'authored eight kinds and physical surface crossing',
                      'ground_route':[[108.,10.4,.47],[135.,10.4,.47]],'ground_second_command_at':40.,
                      'drone_route':[[43.5,20.,34.],[103.,28.,34.]]}


def flooded_route_fixture(world):
    # Rising water behind the outward route leaves the northern road available.
    # The controller sees only its ordinary delivered observations.
    tape={'format':EVENT_VERSION,'profile':'v052','probability_window_s':80,'physics_cell_m':5,
          'placement_model':'authored_loaded_flood_fixture.v1','late_people':[],'events':[
              {'id':'fixture-road-flood','kind':'flood','time':126.25,'source':[92.5,10.,.05],
               'cells':[[18,1],[18,2]],'source_object_id':None,'parent_id':None,'spread':False,
               'expires_at':350.,'visibility_expires_at':None,'rejection':None}]}
    world['event_model']=validate_tape(tape,world)
    world['fixture']={'id':'core-loaded-flood-v1','scope':'autonomous delivery with a rising and receding road flood'}


def resource_fixture(world):
    ground=[agent for agent in world['spawns'] if agent['kind']=='ground']
    for agent,x in zip(ground,(18.,22.)):
        agent.update(position=[x,13.,.95],yaw=0.,exit=[],dock=None)
    next(node for node in world['infrastructure'] if node['id']=='charge-pad-0')['charger']['capacity_wh']=2.
    world['fixture']={'id':'core-charge-v1','scope':'two ground vehicles share one port; aerial pad energy is exhausted'}


def power_loss_fixture(world):
    rover=next(agent for agent in world['spawns'] if agent['kind']=='ground')
    rover.update(position=[81.,12.4,.95],yaw=0.,exit=[],dock=None)
    world['fixture']={'id':'core-loaded-power-loss-v1','scope':'powered route loses battery after pickup'}


def radio_fixture(world,mode):
    if mode!='blackout':
        world['infrastructure']=[n for n in world['infrastructure'] if n['kind']!='relay']
        world['infrastructure'].append({'id':'field-relay','kind':'relay','position':[70.,10.,3.],'range_m':60.})
        for person,x in zip(world['people'],(176.,182.,190.)):person['position']=[x,10.,.06]
    scopes={'blackout':'100 percent packet loss','recovery':'physical relay coverage, partition and queued observation',
            'lost-ack':'execution finishes outside radio range, last ACK is unavailable'}
    world['fixture']={'id':f'core-radio-{mode}-v1','scope':scopes[mode]}


def contest_fixture(world):
    ground=[a for a in world['spawns'] if a['kind']=='ground']
    for a,pose in zip(ground,([75.,10.4,.95],[20.,13.,.95])):
        a.update(position=pose,yaw=0.,exit=[],dock=None)
    rover,charger=(a['id'] for a in ground)
    drone=next(a['id'] for a in world['spawns'] if a['kind']=='aerial')
    world['people'][0]['priority']=3
    def event(identifier,kind,time,targets,parameters,*,until=None,source='scenario-supervisor'):
        return {'id':identifier,'type':kind,'time':time,'until':until,'source':source,'targets':targets,'parameters':parameters}
    rows=[
        event('road-restriction','restricted_zone_appeared',.125,[],
              {'bounds':{'min':[85,5,-.15],'max':[90,15,2]},'allowed_kinds':['aerial']},until=7.375),
        event('actuator-degraded','agent_degradation',1.125,[rover],{'speed_factor':.45,'sensor_factor':.5},until=6.625),
        event('charger-offline','infrastructure_failure',1.875,['charge-base'],{'reason':'breaker_trip'},until=4.625),
        event('scout-radio-offline','connectivity_loss',2.375,[drone],{'reason':'interference'},until=11.125),
        event('casualty-triage','mission_priority_change',3.375,['person-1'],{'priority':1}),
        event('operator-brake','operator_directive',4.125,[rover],{'action':'hold','reason':'inspect_lane'},until=8.625,source='operator'),
        event('unreliable-beacon','contradictory_information',5.125,['person-1'],{'position':[90,20,.06],'confidence':.5},source='sensor-base'),
        event('reserve-drawdown','resource_shortage',9.375,['charge-base'],{'remaining_wh':.1}),
        event('carrier-actuator-fault','agent_failure',33.125,[rover],{'reason':'traction_actuator_fault'}),
    ]
    flood={'id':'fixture-flood','kind':'flood','time':.125,'source':[112.5,12.5,.05],'cells':[[22,1],[22,2]],
           'source_object_id':None,'parent_id':None,'spread':False,'expires_at':None,'visibility_expires_at':None,'rejection':None}
    tape={'format':EVENT_VERSION,'profile':'v3','probability_window_s':30,'physics_cell_m':5,
          'placement_model':'authored_contest_acceptance.v1','events':[flood],'late_people':[]}
    world['event_model']=validate_tape(tape,world)
    world['disturbances']=validate_disturbances({'format':CONTEST_FORMAT,'events':rows},world)
    world['fixture']={'id':'core-contest-disturbances-v1','ground_id':rover,'charger_id':charger,'drone_id':drone}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--route-recovery',action='store_true',help='A real narrow trunk on a road; exercise loaded route recovery')
    mode.add_argument('--events',action='store_true',help='Eight native event kinds and physical surface probes')
    mode.add_argument('--flooded-route',action='store_true',help='Rising water across a loaded return route')
    mode.add_argument('--resources',action='store_true',help='Finite batteries, shared charging queue and station exhaustion')
    mode.add_argument('--power-loss',action='store_true',help='A carrier exhausts its battery with a person on board')
    mode.add_argument('--radio',action='store_true',help='Fly out of relay range and deliver observations after returning')
    mode.add_argument('--radio-blackout',action='store_true',help='Complete packet loss and bounded expiration')
    mode.add_argument('--radio-lost-ack',action='store_true',help='Finish the route while disconnected')
    mode.add_argument('--contest-events',action='store_true',help='All fourteen normalized observation event types')
    args=parser.parse_args()
    private=args.output
    public=private.with_name(private.stem+'.public.json')
    if private.exists() or public.exists():raise FileExistsError('Acceptance fixture already exists')
    settings={'scouts':1,'rescuers':1,'people':3,'preset':'open','horizon':1000 if args.route_recovery else 480}
    if args.events:
        settings.update(horizon=52.375,event_profile='v3',probabilities=dict.fromkeys(EVENT_DEFAULTS['v3'],0))
    if args.flooded_route:
        settings.update(horizon=720,event_profile='v052',probabilities=dict.fromkeys(EVENT_DEFAULTS['v052'],0))
    if args.resources:
        settings.update(horizon=28.5,rescuers=2,resource_profile='contest',ground_battery_wh=6.,aerial_battery_wh=8.,
                        initial_battery_fraction=.4,energy_reserve_fraction=.25)
    if args.power_loss:settings.update(horizon=45,resource_profile='contest',ground_battery_wh=1.8)
    if args.radio or args.radio_blackout or args.radio_lost_ack:
        settings.update(horizon=9 if args.radio_blackout else 48,communication_range_m=60,
                        communication_latency_s=.17,communication_loss=1 if args.radio_blackout else .22)
    if args.contest_events:
        settings.update(horizon=52,rescuers=2,resource_profile='contest',initial_battery_fraction=.65,event_profile='v3')
    world=generate(Settings.parse(settings))
    # An explicit laboratory input, not a controller prior. The independent
    # controller receives no people array, fixture name, or private file path.
    world['fixture']={'id':'core-static-rescue-v1','scope':'three road-side casualties, no dynamic events'}
    for person,x in zip(world['people'],(80.,100.,120.)):
        person['position']=[x,10.,.06]
    if args.events:event_fixture(world)
    if args.flooded_route:flooded_route_fixture(world)
    if args.resources:resource_fixture(world)
    if args.power_loss:power_loss_fixture(world)
    if args.radio or args.radio_blackout or args.radio_lost_ack:
        radio_fixture(world,'blackout' if args.radio_blackout else 'lost-ack' if args.radio_lost_ack else 'recovery')
    if args.contest_events:contest_fixture(world)
    if args.route_recovery:
        # Uses the existing historical cylindrical trunk renderer, dimensions in
        # metres. Its complete collision is public; the probe deliberately tests
        # recovery from a command that did not follow the announced road plan.
        world['features'].append({'id':'fixture-trunk','position':[70.,10.,0.],'yaw':0.,'height_m':4.,
            'obstacles':[{'kind':'box','min':[69.76,9.76,0.],'max':[70.24,10.24,4.]}]})
        world['fixture']={'id':'core-loaded-recovery-v1','scope':'one announced physical trunk; injected faulty route; 1000 s horizon'}
    world['preflight']=preflight(world)
    private.parent.mkdir(parents=True,exist_ok=True)
    private.write_text(json.dumps(world,ensure_ascii=False,indent=2),encoding='utf-8')
    public.write_text(json.dumps(public_map(world),indent=2),encoding='utf-8')
    print(json.dumps({'private':str(private),'public':str(public),'preflight':world['preflight']}))


if __name__=='__main__':main()
