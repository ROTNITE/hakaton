"""Exercise charging with real stationary agents and a limited shared port."""
from __future__ import annotations

import math

from contracts.protocol import ProtocolError, validate_episode_response
from tools.native_archive import IndexedRecords


def drive(client,world,decision):
    if world['fixture']['id']=='core-loaded-power-loss-v1':return drive_power_loss(client,world,decision)
    assert world['fixture']['id']=='core-charge-v1'
    settings=world['settings']
    capabilities=client.capabilities()
    assert capabilities['resource_model']['profile']=='contest'
    assert 'charge' in capabilities['supported_actions']
    episodes={}
    for repetition in range(2):
        response=client.reset(seed=settings['seed'])
        initial=response['observation'];episode=initial['episode_id']
        ground=[a for a in initial['agents'] if a['kind']=='ground']
        drone,=(a for a in initial['agents'] if a['kind']=='aerial')
        agents=[*ground,drone]
        stations={n['id']:n for n in initial['infrastructure'] if 'charger' in n}
        assert stations['charge-base']['charger']['remaining_wh']==10000
        assert stations['charge-pad-0']['charger']['remaining_wh']==2
        for a in agents:
            ph=a['physical'];assert not ph['unlimited_energy']
            assert abs(ph['remaining_wh']-ph['capacity_wh']*.4)<1.e-9
            assert abs(ph['reserve_wh']-ph['capacity_wh']*.25)<1.e-9
            assert ph['consumed_wh']==ph['charged_wh']==0
        charge=[{'agent_id':a['id'],'action':'charge',
                 'parameters':{'station_id':'charge-pad-0' if a['kind']=='aerial' else 'charge-base'}} for a in agents]
        rejected=decision(initial,commands=[charge[0],{'agent_id':ground[0]['id'],'action':'hold','parameters':{}}])
        try:client.step(rejected)
        except ProtocolError as error:assert error.code=='INVALID_COMMAND'
        else:raise AssertionError('Concurrent charge and hold were accepted')
        request=decision(initial,commands=charge)
        first=validate_episode_response(client.step(request),step=True)
        assert client.step(request)==first,'Exact retry changed charging episode'
        response=first;acks={};queued_seen=False
        while True:
            obs=response['observation']
            for result in response['command_results']:
                if result['decision_id']==request['decision_id'] and result['execution_status'] in ('completed','failed'):
                    acks[result['agent_id']]=result
            shared=next(n['charger'] for n in obs['infrastructure'] if n['id']=='charge-base')
            assert shared['active']<=1
            queued_seen|=shared['active']==shared['waiting']==1
            if response['status']!='running':break
            response=validate_episode_response(client.step(decision(obs)),step=True)
        assert response['status']=='time_limit' and obs['time']==settings['horizon']
        assert queued_seen
        for a in ground:assert acks[a['id']]['execution_status']=='completed'
        assert acks[ground[0]['id']]['updated_at']<acks[ground[1]['id']]['updated_at']
        air_ack=acks[drone['id']]
        assert air_ack['execution_status']=='failed' and air_ack['reason_code']=='charging_station_depleted'
        final={a['id']:a for a in obs['agents']}
        for a in agents:
            ph=final[a['id']]['physical'];initial_wh=a['physical']['remaining_wh']
            assert abs(initial_wh+ph['charged_wh']-ph['consumed_wh']-ph['remaining_wh'])<1.e-8
            assert abs(sum(ph['energy_breakdown_wh'].values())-ph['consumed_wh'])<1.e-8
            assert 0<ph['remaining_wh']<=ph['capacity_wh'] and ph['charged_wh']>0
            assert math.dist(a['position'],final[a['id']]['position'])<.03
        assert abs(final[drone['id']]['physical']['charged_wh']-2.)<1.e-8
        episodes[episode]={'repetition':repetition,'ground_ids':[a['id'] for a in ground],'drone_id':drone['id'],
                           'ordered_ack_s':[acks[a['id']]['updated_at'] for a in agents],
                           'balance_error_wh_max':max(abs(a['physical']['remaining_wh']+final[a['id']]['physical']['charged_wh']-
                             final[a['id']]['physical']['consumed_wh']-final[a['id']]['physical']['remaining_wh']) for a in agents)}
    client.close(episode)
    return {'passed':True,'scope':'native charging queue, finite station depletion, reset and power conservation',
            'resource_episodes':episodes,'expected_archive_statuses':dict.fromkeys(episodes,'time_limit')}


def verify(result,output_root):
    if 'power_loss_episode' in result:
        verify_power_loss(result,output_root)
        return
    reference=None
    for episode,evidence in result['resource_episodes'].items():
        truth=IndexedRecords(output_root/'core-runs'/episode/'truth')
        starts=[];ends=[]
        for row in truth.json_records():
            if row['record_type']=='charge_started':starts.append((row['time'],row['payload']))
            if row['record_type']=='charge_ended':ends.append((row['time'],row['payload']))
        assert len(starts)==len(ends)==3
        ground_start=[(t,r) for t,r in starts if r['station_id']=='charge-base']
        ground_end=[(t,r) for t,r in ends if r['station_id']=='charge-base']
        assert [r['agent_id'] for _,r in ground_start]==evidence['ground_ids']
        assert ground_start[0][0]<ground_end[0][0]<ground_start[1][0]<ground_end[1][0]
        assert all(r['status']=='completed' and abs(r['battery_wh']-6.)<1.e-8 for _,r in ground_end)
        assert next(r for _,r in ends if r['station_id']=='charge-pad-0')['station_wh']<1.e-9
        evidence['ground_start_s']=[t for t,_ in ground_start]
        evidence['ground_end_s']=[t for t,_ in ground_end]
        evidence['ground_station_wh_spent']=10000-ground_end[-1][1]['station_wh']
        signature=evidence['ordered_ack_s']
        if reference is None:reference=signature
        else:assert all(abs(a-b)<1.e-7 for a,b in zip(signature,reference)),(signature,reference)


def drive_power_loss(client,world,decision):
    response=client.reset(seed=world['settings']['seed']);obs=response['observation']
    episode=obs['episode_id']
    rover,=(a['id'] for a in obs['agents'] if a['kind']=='ground')
    drone,=(a['id'] for a in obs['agents'] if a['kind']=='aerial')
    tid='person-1';sent=set();lost=False;confirmed_again=False;failure_result=None
    while response['status']=='running':
        now=obs['time'];commands=[]
        agent=next(a for a in obs['agents'] if a['id']==rover);ph=agent['physical']
        known=next((t for t in obs['targets'] if t['id']==tid),None)
        def send(key,owner,action,parameters):
            if key in sent:return
            sent.add(key);commands.append({'agent_id':owner,'action':action,'parameters':parameters})
        if now==0:send('air_route',drone,'follow_route',{'waypoints':[[43.5,20,14],[77,16,14]]})
        if known and 'pickup' not in sent:
            if known['status']=='suspected':send('first_inspect',rover,'inspect',{'target_id':tid})
            elif known['status']=='confirmed':send('pickup',rover,'pickup',{'target_id':tid})
        if ph['cargo_target_id']==tid and ph['carrying']:
            assert ph['mass_kg']>319
            send('loaded_route',rover,'follow_route',{'waypoints':[[60,10,.54],[20,18.3,.54]]})
        if agent['status']=='failed' and 'loaded_route' in sent:
            lost=True;assert ph['remaining_wh']==0 and not ph['carrying'] and abs(ph['mass_kg']-240)<.1
            if known and known['status']=='suspected':
                assert known['source_id']==drone
                send('second_inspect',drone,'inspect',{'target_id':tid})
            if known and known['status']=='confirmed' and known['evacuation_state']=='waiting' and 'second_inspect' in sent:
                confirmed_again=True
        response=validate_episode_response(client.step(decision(obs,commands=commands)),step=True)
        obs=response['observation']
        failure_result=next((r for r in response['command_results'] if r['agent_id']==rover and
            r['action']=='follow_route' and r['execution_status']=='failed'),failure_result)
    assert 'loaded_route' in sent and lost and confirmed_again and failure_result,(sent,lost,confirmed_again,failure_result)
    assert failure_result['reason_code']=='agent_failed_during_execution'
    assert response['status']=='time_limit' and obs['metrics']['confirmed_evacuations']==0
    client.close(episode)
    return {'passed':True,'scope':'native finite battery failure during a loaded route and independent reconfirmation',
            'power_loss_episode':episode,'carrier_id':rover,'observer_id':drone,'target_id':tid,
            'failed_command':failure_result,'expected_archive_statuses':{episode:'time_limit'}}


def verify_power_loss(result,output_root):
    directory=output_root/'core-runs'/result['power_loss_episode']
    carrier=result['carrier_id'];target=result['target_id']
    release=None;after=[];was_loaded=False
    for row in IndexedRecords(directory/'truth').json_records():
        data=row['payload'];kind=row['record_type']
        if kind=='agent_telemetry':
            a=next(a for a in data['agents'] if a['id']==carrier)
            was_loaded|=a['physical']['cargo_target_id']==target
        elif kind=='power_lost' and data['agent_id']==carrier:
            assert release is None and data['released_target']==target
            release=row
        elif kind=='truth_snapshot' and release:
            after.append(next(t for t in data['targets'] if t['id']==target))
    assert was_loaded and release and after
    pose=release['payload']['target_position']
    assert math.dist(release['payload']['position'],pose)<.2
    assert all(not t['assigned'] and not t['rescued'] and t['visible'] and math.dist(t['position'],pose)<1.e-6 for t in after)
    confirmed=[];failure=None
    for row in IndexedRecords(directory/'public').json_records():
        data=row['payload'];kind=row['record_type']
        assert kind!='power_lost'
        if kind=='event' and data['type']=='agent_failure' and carrier in data['targets']:
            assert data['parameters']['basis']=='delivered_agent_state'
            assert failure is None and data['time']>=release['time']
            failure=data
        if kind in ('target_detected','target_state_changed') and data.get('id')==target and row['time']>=release['time']:
            assert data['source_id']==result['observer_id'] and data['evacuation_state']=='waiting'
            assert data['observed_at']>=release['time'] and math.dist(data['position'],pose)<1.e-6
            confirmed.append((kind,row['time']))
    assert [kind for kind,_ in confirmed]==['target_detected','target_state_changed']
    assert failure and failure['received_at']>=failure['time']
    result.update(failure_time_s=release['time'],released_position_m=pose,suspected_again_s=confirmed[0][1],
                  confirmed_again_s=confirmed[1][1],stable_target_snapshots=len(after),public_failure_event=failure)
