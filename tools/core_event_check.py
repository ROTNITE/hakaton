"""Acceptance checks for an authored native event and surface fixture."""
from __future__ import annotations

import math
import gzip
import json
from pathlib import Path
from statistics import median

from contracts.protocol import validate_episode_response
from tools.native_archive import IndexedRecords,file_sha256


def drive(client, world, decision):
    fixture=world['fixture']
    assert fixture['id']=='core-event-effects-v1'
    tape=world['event_model']
    capabilities=client.capabilities()
    assert capabilities['event_model']['profile']==tape['profile']
    assert capabilities['event_model']['probability_window_s']==tape['probability_window_s']
    seed=world['settings']['seed']
    late_id='person-'+str(tape['late_people'][0]['id'])
    late_at=tape['late_people'][0]['available_at']
    first_event_at=min(event['time'] for event in tape['events'])
    episodes={}
    initial_poses=None
    for repetition in range(2):
        response=client.reset(seed=seed)
        observation=response['observation']
        episode=observation['episode_id']
        rover=next(a for a in observation['agents'] if a['kind']=='ground')
        drone=next(a for a in observation['agents'] if a['kind']=='aerial')
        start_poses={a['id']:a['position'] for a in observation['agents']}
        assert not any('surface' in zone for zone in observation['zones']),'Reset exposed a measured surface'
        assert not observation['events'] and not observation['targets'],'Reset exposed a dynamic event or target'
        declared_count=len(observation['zones'])
        assert 'event_model' not in observation['metaevolution']['announced_map']
        if initial_poses is None:initial_poses=start_poses
        else:
            assert start_poses.keys()==initial_poses.keys()
            assert all(math.dist(start_poses[agent],pose)<=1.e-6 for agent,pose in initial_poses.items()),'Reset changed initial physical poses'
        roles={drone['id']:'scout',rover['id']:'rescuer'}
        selection={'scenario_ids':['coverage_search'],'parameters':{},'synthesized_scenario':None}
        kinds=set()
        late_seen_at=None
        clear_reports=[]
        deep_report=None
        max_known_depth=0
        first_hazard_at=None
        second_sent=False
        while response['status']=='running':
            now=observation['time']
            commands=[]
            if now==0:
                commands=[
                    {'agent_id':rover['id'],'action':'follow_route','parameters':{'waypoints':[fixture['ground_route'][0]]}},
                    {'agent_id':drone['id'],'action':'follow_route','parameters':{'waypoints':fixture['drone_route']}},
                ]
            if not second_sent and now>=fixture['ground_second_command_at']:
                commands.append({'agent_id':rover['id'],'action':'follow_route','parameters':{'waypoints':[fixture['ground_route'][1]]}})
                second_sent=True
            request=decision(observation,commands=commands,operation='select' if now==0 else 'keep',
                             selected=selection if now==0 else None,roles=roles if now==0 else None)
            response=validate_episode_response(client.step(request),step=True)
            observation=response['observation']
            now=observation['time']
            if any(t['id']==late_id for t in observation['targets']):
                target=next(t for t in observation['targets'] if t['id']==late_id)
                assert late_at<=target['observed_at']<=target['received_at']<=now
                if late_seen_at is None:late_seen_at=target['received_at']
            for zone in observation['zones']:
                if 'surface' not in zone:continue
                observed,received=zone.get('observed_at'),zone.get('received_at')
                assert (type(observed) in (int,float) and type(received) in (int,float) and
                        first_event_at<=observed<=received<=now),('Noncausal surface measurement',zone['id'],observed,received,now)
                surface=zone['surface']
                kinds.update(surface['kinds'])
                if first_hazard_at is None or received<first_hazard_at:first_hazard_at=received
                max_known_depth=max(max_known_depth,surface['depth_m'])
                if zone['id']=='surface-23-2' and surface['ground_blocked']:
                    deep_report=zone
            clear_reports.extend(e for e in observation['events'] if e['status']=='resolved')
        assert response['status']=='time_limit' and observation['time']==world['settings']['horizon']
        assert {'mud','road_damage','smoke','low_visibility','flood'}<=kinds,kinds
        assert late_seen_at is not None,'The late person was never sensed'
        assert deep_report is not None and deep_report['surface']['depth_m']>=.25,'No delivered deep water blockage'
        assert clear_reports,'No delivered expiry/clear observation'
        episodes[episode]={'repetition':repetition,'ground_id':rover['id'],'late_seen_at':late_seen_at,
            'declared_zones_at_reset':declared_count,
            'first_hazard_received_at':first_hazard_at,'delivered_kinds':sorted(kinds),'max_known_depth_m':max_known_depth,
            'resolved_count':len(clear_reports),'initial_poses':start_poses}
        print({'native_event_episode':episode,'repetition':repetition,'late_seen_at':late_seen_at,
               'kinds':sorted(kinds),'max_known_depth_m':max_known_depth},flush=True)
    client.close(episode)
    return {'passed':True,'scope':'native authored 8-kind tape and dry/mud/road/shallow/deep traversal',
            'expected_archive_statuses':dict.fromkeys(episodes,'time_limit'),'event_episodes':episodes}


def verify(result, world, output_root, *, capture=False):
    tape=world['event_model']
    reference=None
    for episode,evidence in result['event_episodes'].items():
        directory=output_root/'core-runs'/episode
        truth=IndexedRecords(directory/'truth')
        applied=[]
        ground=[]
        initial_bodies=None
        released_bodies=None
        visibility=[]
        ended=set()
        late=tape['late_people'][0]
        hidden_verified=visible_verified=False
        for row in truth.json_records():
            payload=row['payload']
            if row['record_type']=='environment_event_applied':
                assert abs(row['time']-payload['scheduled_at'])<1e-9
                applied.append(payload)
            elif row['record_type']=='agent_telemetry':
                rover=next(a for a in payload['agents'] if a['id']==evidence['ground_id'])
                ground.append((row['time'],rover))
                visibility.append(rover['physical']['sensed_surface']['visibility'])
            elif row['record_type']=='truth_snapshot':
                if payload['phase']=='initial':initial_bodies=payload['physics_pieces']
                if row['time']>=12 and released_bodies is None:released_bodies=payload['physics_pieces']
                person=next(t for t in payload['targets'] if t['id']=='person-'+str(late['id']))
                if row['time']<late['available_at']:
                    assert not person['visible'],'Late person visible before the scheduled event'
                    hidden_verified=True
                else:visible_verified|=person['visible']
            elif row['record_type']=='environment_effect_ended':
                ended.add(payload['event_id'])
        assert len(applied)==len(tape['events'])
        assert {r['kind'] for r in applied}=={r['kind'] for r in tape['events']}
        assert any(r['parent_id']=='fixture-fire' for r in applied),'Spread lost causal parent'
        assert initial_bodies is not None and released_bodies is not None
        assert len(released_bodies)-len(initial_bodies)==3,'No three additional physical collapse bodies'
        assert any(r['released_bodies']==3 for r in applied if r['kind']=='collapse')
        assert {'fixture-smoke','fixture-fog','fixture-fire'}<=ended
        assert hidden_verified and visible_verified,'Late-person visibility transition not observed'
        assert min(visibility)<.34,'Ground sensor never experienced overlapping smoke/fog'
        traversal={}
        for name,lo,hi in [('dry',76,79.6),('mud',80.2,84.8),('road_damage',90.2,94.8),
                            ('shallow',100.2,104.8)]:
            selected=[a for _,a in ground if lo<=a['position'][0]<=hi]
            assert selected and max(a['position'][0] for a in selected)-min(a['position'][0] for a in selected)>1.5,(name,'no physical traversal')
            speeds=[math.hypot(*a['physical']['velocity_m_s'][:2]) for a in selected]
            samples=[a['physical']['sensed_surface'] for a in selected]
            traversal[name]={'samples':len(samples),'speed_m_s_median':median(speeds),
                'max_cost':max(s['movement_cost'] for s in samples),'max_depth_m':max(s['water_depth_m'] for s in samples),
                'distance_m':selected[-1]['physical']['distance_m']-selected[0]['physical']['distance_m'],
                'energy_wh':selected[-1]['physical']['consumed_wh']-selected[0]['physical']['consumed_wh']}
        assert traversal['mud']['max_cost']>=2.25
        assert traversal['road_damage']['max_cost']>=1.89
        assert .04<traversal['shallow']['max_depth_m']<.25
        assert all(traversal[k]['speed_m_s_median']<traversal['dry']['speed_m_s_median'] for k in ('mud','road_damage','shallow'))
        brakes=[(t,a) for t,a in ground if t>=40 and a['physical']['stop_reason']=='hazard_on_route']
        assert brakes and max(a['position'][0] for t,a in ground if t>=40)<115,'Rover entered deep water'
        # Private event IDs and geometry must not occur in any public records
        # until the separately observed physical surface can be reported.
        private_types={'event_configuration','environment_event_applied','hazard_observation','truth_snapshot'}
        for row in IndexedRecords(directory/'public').json_records():
            assert row['record_type'] not in private_types
        signature=[(r['event_id'],r['scheduled_at'],r['cells']) for r in applied]
        if reference is None:reference=signature
        else:assert signature==reference,'Reset changed the external event tape'
        evidence.update(applied_events=len(applied),traversal=traversal,min_visibility=min(visibility),
            first_deep_brake_at=brakes[0][0],deep_brake_position_m=brakes[0][1]['position'],
            initial_physics_bodies=len(initial_bodies),physical_bodies_after_collapse=len(released_bodies),
            ended_effects=sorted(ended),late_visibility_transition_verified=True)
        if capture:
            frames={}
            for kind in sorted({row['kind'] for row in tape['events']}):
                path=directory/'frames'/(kind+'.png')
                assert path.is_file() and path.stat().st_size>4096,('Missing native screenshot',kind)
                frames[kind]={'path':str(path),'sha256':file_sha256(path),'bytes':path.stat().st_size}
            evidence['frames']=frames


def verify_flood_mission(directory):
    """Join the autonomous mission's public decisions with actual motion."""
    mission=json.loads((directory/'manifest.json').read_bytes())
    control=directory/'controller'
    summary=json.loads((control/'manifest.json').read_bytes())
    native=Path(mission['native_archive'])
    archive=json.loads((directory/'native-archive-verification.json').read_bytes())
    world=json.loads((directory/'world.private.json').read_bytes())
    assert world['fixture']['id']=='core-loaded-flood-v1'
    flood,=world['event_model']['events']
    assert mission['state']=='complete' and mission['episode_status']=='success'
    assert mission['frozen_inputs_preserved'] and mission['native_exit_code']==mission['controller_exit_code']==0
    assert archive['passed'] and summary['episode_id']==archive['episode_id']
    assert mission['source_layout']['sha256']==file_sha256(directory/'world.private.json')
    journal=control/summary['journal']
    assert file_sha256(journal)==summary['journal_sha256']
    by_time={};changes={};traces={};results={};count=0
    with gzip.open(journal,'rt',encoding='utf-8') as source:
        for line in source:
            row=json.loads(line);count+=1;data=row['payload']
            if row['record_type']=='decision':changes[data['decision']['time']]=data['decision']
            elif row['record_type']=='step_response':
                obs=data['observation'];by_time[obs['time']]=obs
                assert 'event_model' not in obs['metaevolution']['announced_map']
                for result in data['command_results']:
                    results[(result['decision_id'],result['command_index'])]=result
            elif row['record_type']=='planning_trace':traces.setdefault(data['type'],[]).append(data)
    assert count==summary['records'] and summary['metrics']['confirmed_evacuations']==3
    brake,=traces['local_immediate_brake']
    detour,=(row for row in traces['local_action_applied'] if row['action']=='DETOUR')
    aid=brake['agent_id'];target=brake['cargo_target_id']
    assert detour['agent_id']==aid and target and brake['reason']=='hazard_on_route'
    assert flood['time']<brake['time']<detour['time']<flood['expires_at']
    blocked=[z for z in by_time[brake['time']]['zones'] if z.get('surface',{}).get('ground_blocked')]
    assert blocked and all(flood['time']<=z['observed_at']<=z['received_at']<=brake['time'] for z in blocked)
    def matched_command(time,action):
        decision=changes[time]
        command,=((index,command) for index,command in enumerate(decision['commands'])
                  if command['agent_id']==aid and command['action']==action)
        index,body=command
        result=results[(decision['decision_id'],index)]
        assert result['execution_status']=='completed' and result['delivery_status']=='delivered'
        return f"{decision['decision_id']}:{index}",body['parameters'],result['updated_at']
    hold,_,hold_ack=matched_command(brake['time'],'hold')
    route_id,parameters,route_ack=matched_command(detour['time'],'follow_route')
    assert parameters['waypoints']==detour['route']
    reply,=(r for r in traces['ai_response'] if r['request_id']==detour['request_id'])
    assert reply['validated'] and reply['result']['mode']=='MOCK' and reply['result']['proposal']['action']=='DETOUR'
    physical=[];event_at=None
    for row in IndexedRecords(native/'truth').json_records():
        if row['record_type']=='environment_event_applied' and row['payload']['event_id']==flood['id']:
            event_at=row['time']
        if row['record_type']!='agent_telemetry':continue
        agent=next(a for a in row['payload']['agents'] if a['id']==aid)
        if agent['physical']['cargo_target_id']==target:physical.append((row['time'],agent))
    assert event_at is not None and abs(event_at-flood['time'])<1e-9
    stopped_at,stopped=next((t,a) for t,a in physical if a['physical']['stop_reason']=='hazard_on_route')
    assert stopped['position'][0]>max(cell[0]+1 for cell in flood['cells'])*5
    assert any(a['physical']['active_command_id']==hold for _,a in physical)
    driven=[a for _,a in physical if a['physical']['active_command_id']==route_id]
    assert driven and max(a['position'][1] for a in driven)>45
    assert all(a['physical']['sensed_surface']['water_depth_m']<=.25 for a in driven)
    received=None
    for row in IndexedRecords(native/'public').json_records():
        assert row['record_type'] not in {'event_configuration','environment_event_applied','truth_snapshot','hazard_observation'}
        if row['record_type']=='target_state_changed' and row['payload']['id']==target and row['payload']['evacuation_state']=='evacuated':
            assert received is None,'Repeated delivery'
            received=row
    assert received and route_ack<received['time']<archive['time']
    assert traces['navigation_knowledge_updated'] and traces['planning_replan_requested']
    return {'passed':True,'scope':'authored flood, autonomous NSGA-II x2 and MOCK Local',
            'episode_id':summary['episode_id'],'applied_at':event_at,'blocked_zone_ids':[z['id'] for z in blocked],
            'agent_id':aid,'target_id':target,'native_first_brake_s':stopped_at,
            'native_first_brake_position_m':stopped['position'],'hold_command_id':hold,'hold_ack_s':hold_ack,
            'local_request_id':detour['request_id'],'route_command_id':route_id,'route_ack_s':route_ack,
            'detour_waypoints_m':detour['route'],'max_detour_y_m':max(a['position'][1] for a in driven),
            'delivery_time_s':received['time'],'delivery_trace_id':received['trace_id'],
            'mission_time_s':archive['time'],'controller_records':count,'controller_journal_sha256':summary['journal_sha256'],
            'known_targets':summary['metrics']['known_targets'],'confirmed_evacuations':3}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Verify a completed autonomous flooded-road mission')
    parser.add_argument('mission',type=Path)
    args=parser.parse_args()
    result=verify_flood_mission(args.mission)
    with (args.mission/'flood-verification.json').open('x',encoding='utf-8') as output:
        json.dump(result,output,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=False))
