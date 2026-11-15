"""Physical stop and detour around an imported tree in the 3D district."""
from copy import deepcopy
import argparse
import json
import math
from pathlib import Path
import time

from controller.navigation import NavigationMap
from controller.baselines import FixedWorkflow,Job
from controller.ai import Off
from controller.ai_policy import SupervisedPolicy
from environment.layout import preflight, public_map
from tools.native_archive import IndexedRecords


def prepare(source):
    world=deepcopy(source)
    world['settings']['horizon']=45.
    public=public_map(world)
    public['navigation']={'kind':'street_surface_graph.v2','road_surface_z_m':0,
                          'base_surface_z_m':.07,'ground_clearance_m':.43}
    trees=[f for f in public['features'] if f['asset_id']=='street_linden']
    for tree in trees:
        # Only the fixture's target collider is removed from this placement
        # check, to isolate it from other scenery intersecting the test lane.
        nav=NavigationMap({**public,'features':[f for f in public['features'] if f['id']!=tree['id']]})
        x,y,_=tree['position']
        for degrees in range(0,360,30):
            yaw=math.radians(degrees);dx,dy=math.cos(yaw),math.sin(yaw)
            start=(x-7*dx,y-7*dy,.45);goal=(x+7*dx,y+7*dy,.45)
            for side in (-1,1):
                shift=(-4.8*dy*side,4.8*dx*side)
                first=(start[0]+shift[0],start[1]+shift[1],.45)
                second=(goal[0]+shift[0],goal[1]+shift[1],.45)
                # Entire bypass corridor is outside other scenery.
                probes=((start,goal),(start,first),(first,second),(second,goal))
                if not all(nav.clear(a,b,1.65,1.1) for a,b in probes):
                    continue
                spawn=next(f for f in world['spawns'] if f['kind']=='ground')
                spawn.update(position=list(start),yaw=float(degrees),dock=None,exit=[])
                world['fixture']={'id':'core-city-tree-v1','tree':tree['id'],
                                  'agent_id':spawn['id'],'position':tree['position'],
                                  'start':list(start),'goal':list(goal),'bypass_shift_m':list(shift)}
                world['preflight']=preflight(world)
                return world
    raise ValueError('No isolated trunk with a clear bypass')


def drive(client,world,decision):
    fixture=world['fixture'];assert fixture['id']=='core-city-tree-v1'
    seed=world['settings']['seed'];aid=fixture['agent_id'];center=fixture['position'];goal=fixture['goal']
    result=client.reset(seed=seed)
    episode=result['observation']['episode_id']
    sent={}

    def send(action=None,parameters=None):
        nonlocal result
        obs=result['observation']
        commands=[{'agent_id':aid,'action':action,'parameters':parameters or {}}] if action else []
        request=decision(obs,commands=commands)
        if commands:sent[action]=request['decision_id']+':0'
        result=client.step(request)
        assert result['status']=='running',result['status']
        return next(row for row in result['observation']['agents'] if row['id']==aid)

    agent=send('follow_route',{'waypoints':[fixture['start'],goal]})
    for _ in range(16):
        if agent['physical']['stop_reason']=='obstacle_on_route':
            break
        agent=send()
    assert agent['physical']['stop_reason']=='obstacle_on_route',agent['physical']
    assert agent['physical']['active_command_id']==sent['follow_route']
    assert 'BoxComponent' in agent['physical']['stop_obstacle'],agent['physical']['stop_obstacle']
    stopped=agent['position'];stop_time=result['time']
    assert 1.3<math.dist(stopped[:2],center[:2])<6.5,stopped
    direct=sent['follow_route']
    agent=send('hold')
    for _ in range(5):
        if agent['physical']['active_command_id']==sent['hold']:
            break
        agent=send()
    assert agent['physical']['active_command_id']==sent['hold'],agent['physical']
    start=agent['position'];sx,sy=fixture['bypass_shift_m']
    points=[start,[start[0]+sx,start[1]+sy,.45],[goal[0]+sx,goal[1]+sy,.45],goal]
    nav=NavigationMap(result['observation']['metaevolution']['announced_map'])
    assert all(nav.clear(a,b,1.45,1.1) for a,b in zip(points,points[1:]))
    agent=send('follow_route',{'waypoints':points})
    distances=[]
    completed=None
    while result['time']<world['settings']['horizon']-1:
        distances.append(math.dist(agent['position'][:2],center[:2]))
        completed=next((row for row in result['command_results'] if
                        row['decision_id']+':'+str(row['command_index'])==sent['follow_route'] and
                        row['delivery_status']=='delivered' and row['execution_status']=='completed'),None)
        if completed:
            break
        agent=send()
    assert completed and math.dist(agent['position'][:2],goal[:2])<1.3,(completed,agent['position'])
    assert min(distances)>1.4,min(distances)
    client.close(episode)
    return {'passed':True,'scope':'physical stop at CityV2 tree collider, hold and alternate route',
            'episode_id':episode,'tree_id':fixture['tree'],'direct_command_id':direct,
            'braked_at_s':stop_time,'braked_at_m':stopped,'hold_command_id':sent['hold'],
            'detour_command_id':sent['follow_route'],'detour_completed_s':completed['updated_at'],
            'detour_waypoints_m':points,'minimum_sampled_detour_clearance_m':min(distances),
            'expected_archive_statuses':{episode:'failed'}}


def drive_maximum(client,world,decision):
    assert world['size_m']==1500 and len(world['people'])==600
    response=client.reset(seed=world['settings']['seed'])
    observation=response['observation'];episode=observation['episode_id']
    starts={agent['id']:agent for agent in observation['agents']}
    assert sum(agent['kind']=='ground' for agent in starts.values())==40
    assert sum(agent['kind']=='aerial' for agent in starts.values())==48
    commands=[]
    for agent in starts.values():
        x,y,z=agent['position']
        goal=[x,y-3.5,z] if agent['kind']=='ground' else [x,y,4.5]
        commands.append({'agent_id':agent['id'],'action':'follow_route',
                         'parameters':{'waypoints':[agent['position'],goal]}})
    request=decision(observation,commands=commands)
    response=client.step(request)
    accepted={row['agent_id'] for row in response['command_results']
              if row['decision_id']==request['decision_id'] and row['validation_status']=='accepted'}
    assert accepted==starts.keys(),sorted(starts.keys()-accepted)
    moved={};last_times=[]
    for _ in range(15):
        assert response['status']=='running',response['status']
        for agent in response['observation']['agents']:
            before=starts[agent['id']]
            x,y,z=agent['position'];ox,oy,oz=before['position']
            travel=math.dist((x,y),(ox,oy)) if agent['kind']=='ground' else z-oz
            if travel>.55 and agent['physical']['distance_m']>.4 and agent['id'] not in moved:
                moved[agent['id']]={'time_s':response['time'],'position_m':[x,y,z],
                                    'signed_motion_m':travel,'kind':agent['kind']}
        if len(moved)==88:break
        started=time.perf_counter()
        response=client.step(decision(response['observation']))
        last_times.append(time.perf_counter()-started)
    assert len(moved)==88,{'unmoved':sorted(starts.keys()-moved.keys()),'moved':len(moved)}
    client.close(episode)
    return {'passed':True,'scope':'real 1500m native world, all 88 agents physically moved; controlled fleet fixture',
            'episode_id':episode,'size_m':world['size_m'],'initial_people':len(world['people']),
            'buildings':len(world['buildings']),'accepted_commands':len(accepted),
            'motion_by_agent':moved,'last_movement_observed_s':max(row['time_s'] for row in moved.values()),
            'sampled_step_wall_s':last_times,'expected_archive_statuses':{episode:'failed'}}


def prepare_aerial(source):
    """Airborne launch-conflict reproduction; unrelated city inputs stay intact."""
    world=deepcopy(source);world['settings']['horizon']=24.
    aerial=[s for s in world['spawns'] if s['kind']=='aerial']
    if len(aerial)!=3:raise ValueError('Aerial clearance fixture requires three scouts')
    starts=([53.,20.,19.714],[58.5,20.,22.328],[45.,32.,.31])
    for spawn,start in zip(aerial,starts):spawn.update(position=list(start),yaw=0.,dock=None,exit=[])
    world['fixture']={'id':'core-air-clearance-v1','agents':[aerial[0]['id'],aerial[1]['id']],
        'routes':[[[75.,25.,20.]],[[58.5,20.,25.],[95.,25.,25.]]],
        'scope':'finite-height rotor clearance at a simultaneous climb and crossing'}
    world['preflight']=preflight(world)
    return world


def drive_aerial(client,world,decision):
    fixture=world['fixture'];assert fixture['id']=='core-air-clearance-v1'
    response=client.reset(seed=world['settings']['seed']);episode=response['episode_id']
    ids=fixture['agents'];commands=[{'agent_id':aid,'action':'follow_route','parameters':{'waypoints':route}}
        for aid,route in zip(ids,fixture['routes'])]
    request=decision(response['observation'],commands=commands);response=client.step(request)
    completed={};samples=[]
    while response['time']<world['settings']['horizon']-1:
        agents={a['id']:a for a in response['observation']['agents']}
        pair=[agents[aid] for aid in ids]
        samples.append({'time':response['time'],'positions':[a['position'] for a in pair],
                        'stop_reasons':[a['physical']['stop_reason'] for a in pair]})
        for row in response['command_results']:
            if row['decision_id']==request['decision_id'] and row['execution_status']=='completed':
                completed[row['agent_id']]=row['updated_at']
        if len(completed)==2:break
        assert response['status']=='running',response['status']
        response=client.step(decision(response['observation']))
    assert len(completed)==2,{'completed':completed,'last':samples[-1]}
    for aid,route in zip(ids,fixture['routes']):
        assert math.dist(agents[aid]['position'],route[-1])<1.3,(aid,agents[aid]['position'])
        assert agents[aid]['physical']['distance_m']>18
    client.close(episode)
    return {'passed':True,'scope':fixture['scope'],'episode_id':episode,'completed_s':completed,
            'samples':samples,'expected_archive_statuses':{episode:'failed'}}


def prepare_parking(source):
    world=deepcopy(source);world['settings']['horizon']=110.
    ground=[a for a in world['spawns'] if a['kind']=='ground']
    if len(ground)<2:raise ValueError('Parking fixture requires neighbouring occupied docks')
    world['fixture']={'id':'core-dock-parking-v1','agent_id':ground[-1]['id'],
        'scope':'departure, shared handover approach, aligned dock return and stable parking'}
    return world


def drive_parking(client,world,decision):
    fixture=world['fixture'];assert fixture['id']=='core-dock-parking-v1'
    response=client.reset(seed=world['settings']['seed']);episode=response['episode_id'];aid=fixture['agent_id']
    def actor():return next(a for a in response['observation']['agents'] if a['id']==aid)
    home=actor()['physical']['dock_position_m'];exits=actor()['physical']['dock_exit_waypoints']
    policy=FixedWorkflow();policy.jobs[aid]=Job('park');phases=[]

    def execute(name,points):
        nonlocal response
        request=decision(response['observation'],commands=[{'agent_id':aid,'action':'follow_route','parameters':{'waypoints':points}}])
        response=client.step(request);finished=None
        while response['time']<world['settings']['horizon']-4:
            finished=next((r for r in response['command_results'] if r['decision_id']==request['decision_id'] and
                r['execution_status']=='completed'),None)
            if finished:break
            assert response['status']=='running',response['status']
            response=client.step(decision(response['observation']))
        assert finished,{'phase':name,'time':response['time'],'agent':actor()}
        phases.append({'phase':name,'completed_s':finished['updated_at'],'position_m':actor()['position'],
                       'waypoints_m':points,'command_id':request['decision_id']+':0'})

    execute('depart',exits)
    announced=response['observation']['metaevolution']['announced_map'];base=announced['base_position']
    goal=[base[0],base[1]-3.7,actor()['position'][2]]
    execute('approach_handover',policy._route(announced,actor(),response['observation']['agents'],goal))
    execute('park',policy._parking_route(announced,actor(),response['observation']['agents'],home))
    for _ in range(3):response=client.step(decision(response['observation']))
    parked=actor();physical=parked['physical']
    assert math.dist(parked['position'][:2],home[:2])<.35,parked['position']
    assert math.dist(physical['velocity_m_s'],[0,0,0])<.1,physical['velocity_m_s']
    assert physical['route_finished'] and physical['vehicle_contacts']==0,physical
    assert physical['distance_m']>70,physical['distance_m']
    client.close(episode)
    return {'passed':True,'scope':fixture['scope'],'episode_id':episode,'agent_id':aid,'phases':phases,
            'home_m':home,'parked_position_m':parked['position'],'distance_m':physical['distance_m'],
            'consumed_wh':physical['consumed_wh'],'vehicle_contacts':physical['vehicle_contacts'],
            'expected_archive_statuses':{episode:'failed'}}


def drive_loaded_bypass(client, world, decision):
    fixture = world['fixture']
    response = client.reset(seed=world['settings']['seed'])
    episode = response['episode_id']
    carrier_id = fixture['agent_id']
    parked_id = fixture['parked_id']
    horizon = world['settings']['horizon']

    def actor(identifier):
        return next(a for a in response['observation']['agents'] if a['id'] == identifier)

    def step(action=None, parameters=None):
        nonlocal response
        commands = [{'agent_id': carrier_id, 'action': action, 'parameters': parameters or {}}] if action else []
        request = decision(response['observation'], commands=commands)
        response = client.step(request)
        return request['decision_id']

    def wait_for_command(identifier, until):
        while True:
            result = next((r for r in response['command_results'] if r['decision_id'] == identifier), None)
            if result and result['execution_status'] in ('completed', 'failed', 'cancelled'):
                return result
            if response['status'] != 'running' or response['time'] >= until:
                return None
            step()

    while not response['observation']['targets'] and response['time'] < 6:
        step()
    target, = response['observation']['targets']
    target_id = target['id']
    if target['status'] == 'suspected':
        inspected = wait_for_command(step('inspect', {'target_id': target_id}), 10)
        assert inspected and inspected['execution_status'] == 'completed', inspected
    pickup = wait_for_command(step('pickup', {'target_id': target_id}), 30)
    assert pickup and pickup['execution_status'] == 'completed', pickup
    loaded = actor(carrier_id)
    assert loaded['physical']['cargo_target_id'] == target_id and loaded['physical']['mass_kg'] > 319

    observation = response['observation']
    announced = observation['metaevolution']['announced_map']
    base_x, base_y, _ = announced['base_position']
    policy = SupervisedPolicy(Off())
    try:
        policy.jobs[carrier_id] = Job('return', target_id)
        goal = [base_x, base_y - 3.7, loaded['position'][2]]
        waypoints, _, _ = policy._fresh_route(observation, loaded, goal)
    finally:
        policy.close()
    route_id = step('follow_route', {'waypoints': waypoints})
    stopped = None
    closest = math.inf
    arrived = None
    while response['status'] == 'running' and response['time'] < horizon - 10:
        carrier, parked = actor(carrier_id), actor(parked_id)
        physical = carrier['physical']
        assert physical['carrying'] and physical['cargo_target_id'] == target_id, physical
        closest = min(closest, math.dist(carrier['position'][:2], parked['position'][:2]))
        if stopped is None and physical['stop_reason'] == 'yield_to_vehicle':
            stopped = {'time': response['time'], 'pose': carrier['position'], 'neighbour': physical['stop_obstacle']}
        arrived = next((r for r in response['command_results'] if r['decision_id'] == route_id and
                        r['execution_status'] == 'completed'), None)
        if arrived:
            break
        step()
    if arrived:
        while math.dist(actor(carrier_id)['physical']['velocity_m_s'], [0, 0, 0]) > .3 and response['time'] < horizon - 8:
            step()
        station = next(n['id'] for n in observation['infrastructure'] if n['kind'] == 'base_station')
        handover = wait_for_command(step('handover', {'station_id': station}), horizon)
    else:
        handover = None
    carrier, parked = actor(carrier_id), actor(parked_id)
    contacts = sum(a['physical']['vehicle_contacts'] for a in (carrier, parked))
    delivered = response['observation']['metrics']['confirmed_evacuations']
    client.close(episode)
    return {'passed': delivered == 1 and contacts == 0 and handover is not None and
                       handover['execution_status'] == 'completed',
            'scope': fixture['scope'], 'episode_id': episode, 'carrier_id': carrier_id, 'parked_id': parked_id,
            'pickup': pickup, 'route_id': route_id, 'waypoints_m': waypoints, 'first_yield': stopped,
            'minimum_public_clearance_m': closest, 'arrived': arrived, 'handover': handover,
            'final_carrier_pose': carrier['position'], 'final_stop_reason': carrier['physical']['stop_reason'],
            'final_cargo': carrier['physical']['cargo_target_id'], 'contacts': contacts, 'delivered': delivered,
            'expected_archive_statuses': {episode: 'success' if delivered == 1 else 'failed'}}


def verify_loaded_bypass(result, output_root):
    truth = IndexedRecords(output_root / 'core-runs' / result['episode_id'] / 'truth')
    minimum_gap = math.inf
    start, finish = None, None
    samples = 0
    for row in truth.json_records():
        if row['record_type'] != 'agent_telemetry':
            continue
        agents = {agent['id']: agent for agent in row['payload']['agents']}
        carrier, parked = agents[result['carrier_id']], agents[result['parked_id']]
        physical = carrier['physical']
        if physical['active_command_id'] != result['route_id'] + ':0':
            continue
        assert physical['carrying'] and physical['vehicle_contacts'] == parked['physical']['vehicle_contacts'] == 0
        minimum_gap = min(minimum_gap, math.dist(carrier['position'][:2], parked['position'][:2]))
        finish = (physical['distance_m'], physical['rotation_degrees'][2])
        if start is None:
            start = finish
        samples += 1
    assert start is not None and finish is not None
    result.update(native_motion_samples=samples, minimum_native_clearance_m=minimum_gap,
                  loaded_travel_m=finish[0] - start[0], initial_and_final_yaw_deg=[start[1], finish[1]])
    if result['passed']:
        assert minimum_gap >= 3.55 and finish[0] - start[0] > 20., result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('layout',type=Path)
    parser.add_argument('output',type=Path)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--aerial',action='store_true')
    modes.add_argument('--parking',action='store_true')
    args=parser.parse_args()
    fixture=(prepare_aerial if args.aerial else prepare_parking if args.parking else prepare)(json.loads(args.layout.read_bytes()))
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(fixture,stream,indent=2)
    print(json.dumps(fixture['fixture']))
