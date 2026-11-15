"""Verify the public contest catalog against a private timed native fixture."""
from __future__ import annotations

import math

from contracts.protocol import validate_episode_response
from controller.baselines import FixedWorkflow
from tools.native_archive import IndexedRecords


def drive(client,world,decision):
    assert world['fixture']['id']=='core-contest-disturbances-v1'
    settings=world['settings'];fixture=world['fixture'];rover=fixture['ground_id'];station_agent=fixture['charger_id'];drone=fixture['drone_id']
    expected=set(client.capabilities()['observation_event_types']);assert len(expected)==14
    response=client.reset(seed=settings['seed']);obs=response['observation'];episode=obs['episode_id']
    assert not obs['targets'] and not obs['events'] and 'disturbances' not in obs['metaevolution']['announced_map']
    commands_by_label={};acks={};events=[];disputed=False;failed=False;loaded=False;inspected=False
    audit=None;prior_position=None;confirmed_priority=None;outage_seen=False
    while response['status']=='running':
        now=obs['time'];commands=[];labels=[]
        def send(label,owner,action,parameters):
            if label in commands_by_label:return
            labels.append(label);commands.append({'agent_id':owner,'action':action,'parameters':parameters})
        ground=next(a for a in obs['agents'] if a['id']==rover);ph=ground['physical']
        air=next(a for a in obs['agents'] if a['id']==drone)
        station=next(n for n in obs['infrastructure'] if n['id']=='charge-base')
        target=next((t for t in obs['targets'] if t['id']=='person-1'),None)
        outage_seen|=air['status']=='offline'
        if now==0:
            send('approach_restriction',rover,'follow_route',{'waypoints':[[107.,10.4,.47]]})
            send('charge_interrupted',station_agent,'charge',{'station_id':'charge-base'})
            send('flight',drone,'follow_route',{'waypoints':[[47,20,18],[95,10,18]]})
        if obs['mission']['directives'] and 'directive_hold' not in commands_by_label:
            advice=FixedWorkflow().decide(obs)
            hold,=(c for c in advice['commands'] if c['agent_id']==rover)
            assert hold['action']=='hold'
            audit=advice['metaevolution']['directive_checks'];assert audit[0]['outcome']=='proposed_hold'
            send('directive_hold',rover,hold['action'],hold['parameters'])
        if target and target['status']=='suspected' and prior_position is None:prior_position=target['position']
        conflicts=obs['metaevolution']['contradictions']
        if conflicts:
            assert target and target['position']==prior_position and conflicts[0]['position']!=prior_position
            assert obs['observation_quality']['contradiction_count']==len(conflicts)
            disputed=True
        if now>=9 and target and target['status']=='suspected' and not obs['mission']['directives']:
            send('confirm_target',rover,'inspect',{'target_id':'person-1'})
        if target and target['status']=='confirmed' and not conflicts:
            if not loaded:
                inspected=True;confirmed_priority=target['priority']
            send('load_target',rover,'pickup',{'target_id':'person-1'})
        if ph['cargo_target_id']=='person-1' and ph['carrying']:
            loaded=True;send('loaded_return',rover,'follow_route',{'waypoints':[[56,10,.54],[20,18.3,.54]]})
        if now>=10 and 0<station['charger']['remaining_wh']<=.1:
            send('charge_depleted',station_agent,'charge',{'station_id':'charge-base'})
        if ground['status']=='failed':
            failed=True;assert ph['failure_reason']=='traction_actuator_fault' and not ph['carrying']
        request=decision(obs,commands=commands)
        for index,label in enumerate(labels):commands_by_label[label]=(request['decision_id'],index)
        response=validate_episode_response(client.step(request),step=True);obs=response['observation'];events.extend(obs['events'])
        for r in response['command_results']:acks[(r['decision_id'],r['command_index'])]=r
    assert response['status']=='time_limit' and obs['metrics']['confirmed_evacuations']==0
    assert loaded and failed and inspected and disputed and outage_seen and confirmed_priority==1/3
    assert {e['type'] for e in events}==expected,sorted(expected-{e['type'] for e in events})
    assert acks[commands_by_label['directive_hold']]['execution_status']=='completed'
    assert acks[commands_by_label['charge_interrupted']]['reason_code']=='charging_station_unavailable'
    assert acks[commands_by_label['charge_depleted']]['reason_code']=='charging_station_depleted'
    assert acks[commands_by_label['loaded_return']]['reason_code']=='agent_failed_during_execution'
    conflict=[e for e in events if e['id']=='unreliable-beacon'];assert [e['status'] for e in conflict]==['active','resolved']
    client.close(episode)
    return {'passed':True,'scope':'fourteen public contest types and physical consequences',
            'contest_episode':episode,'fixture':fixture,'events':events,'directive_checks':audit,
            'expected_archive_statuses':{episode:'time_limit'}}


def verify(result,world,output_root):
    directory=output_root/'core-runs'/result['contest_episode'];rover=result['fixture']['ground_id']
    starts={};ends={};brake=None;released=None;loaded_before_fault=False;speeds=[];report_mute=[]
    release_snapshots=[]
    for row in IndexedRecords(directory/'truth').json_records():
        kind=row['record_type'];data=row['payload'];now=row['time']
        if kind=='contest_event_started':starts[data['id']]=now
        elif kind=='contest_event_ended':ends[data['id']]=now
        elif kind=='agent_fault_effect':released=data
        elif kind=='truth_snapshot' and released:
            release_snapshots.append(next(t for t in data['targets'] if t['id']=='person-1'))
        elif kind=='agent_telemetry':
            agent=next(a for a in data['agents'] if a['id']==rover);ph=agent['physical']
            if ph['stop_obstacle']=='restricted_volume' and brake is None:brake=(now,agent['position'])
            if 1.5<now<6.6 and ph['speed_factor']<1:speeds.append(math.hypot(*ph['velocity_m_s'][:2]))
            loaded_before_fault|=ph['cargo_target_id']=='person-1' and now<33.125
            drone=next(a for a in data['agents'] if a['id']==result['fixture']['drone_id'])
            if 2.4<now<11.1:report_mute.append(drone['communication']['reachable'])
    for e in world['disturbances']['events']:
        assert abs(starts[e['id']]-e['time'])<1.e-9
        if e['until'] is not None:assert abs(ends[e['id']]-e['until'])<1.e-9
    assert brake and brake[1][0]<85 and speeds and max(speeds)<2
    assert report_mute and not any(report_mute)
    assert loaded_before_fault and released and released['released_target']=='person-1'
    assert release_snapshots and all(not t['assigned'] and not t['rescued'] and math.dist(t['position'],released['target_position'])<1.e-6
                                     for t in release_snapshots)
    result.update(applied_times=starts,ended_times=ends,first_restriction_brake_s=brake[0],restriction_brake_position_m=brake[1],
                  max_degraded_speed_m_s=max(speeds),released_position_m=released['target_position'],release_snapshots=len(release_snapshots))
