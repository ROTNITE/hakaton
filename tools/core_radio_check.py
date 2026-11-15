"""Native radio acceptance with two reproducible trips through relay coverage."""
from __future__ import annotations

from contracts.protocol import validate_episode_response
from tools.native_archive import IndexedRecords


def drive(client,world,decision):
    settings=world['settings'];fixture=world['fixture']['id'];blackout=fixture=='core-radio-blackout-v1'
    lost_ack=fixture=='core-radio-lost-ack-v1'
    assert client.capabilities()['radio_model']['base_loss_per_hop']==settings['communication_loss']
    episodes={}
    for repetition in range(1 if blackout or lost_ack else 2):
        response=client.reset(seed=settings['seed']);obs=response['observation'];episode=obs['episode_id']
        assert not obs['targets']
        drone,=(a['id'] for a in obs['agents'] if a['kind']=='aerial')
        waypoints=[[43.5,20,14],[188,10,14]]
        if not lost_ack:waypoints.append([90,10,14])
        command={'agent_id':drone,'action':'hold','parameters':{}} if blackout else {
            'agent_id':drone,'action':'follow_route','parameters':{'waypoints':waypoints}}
        initial=decision(obs,commands=[command]);seen_mesh=False;offline=[];detected=None;ack=None
        events=[]
        while response['status']=='running':
            response=validate_episode_response(client.step(initial if obs['time']==0 else decision(obs)),step=True)
            obs=response['observation']
            events.extend(obs['events'])
            agent=next(a for a in obs['agents'] if a['id']==drone)
            seen_mesh|=obs['network']['mesh_available'] and any(
                l['from']=='field-relay' and l['to']==drone for l in obs['network']['known_links'])
            if agent['status']=='offline':
                assert not agent['available_actions'] and not agent['communication']['reachable']
                offline.append(obs['time'])
            if detected is None:detected=next((t for t in obs['targets'] if t['id']=='person-1'),None)
            for r in response['command_results']:
                if r['decision_id']==initial['decision_id']:ack=r
        assert response['status']=='time_limit' and response['time']==settings['horizon']
        assert offline,'No public stale/offline transition'
        stale=[e for e in events if e['type']=='stale_information' and drone in e['targets']]
        connectivity=[e for e in events if e['type']=='connectivity_loss' and drone in e['targets']]
        assert stale and connectivity and stale[0]['status']==connectivity[0]['status']=='active'
        assert stale[0]['time']==offline[0]
        if blackout:
            assert not seen_mesh and not detected
            assert ack and ack['delivery_status']=='expired' and ack['execution_status']=='not_started'
            assert obs['observation_quality']['maximum_delay']==0 and obs['observation_quality']['stale_data_ratio']==1
        elif lost_ack:
            assert seen_mesh and not detected
            assert ack and ack['execution_status']=='unknown' and ack['reason_code']=='acknowledgement_expired',ack
        else:
            assert seen_mesh and detected and detected['source_id']==drone
            assert detected['received_at']>detected['observed_at']
            assert ack and ack['execution_status']=='completed',ack
            assert obs['observation_quality']['maximum_age']>=obs['observation_quality']['maximum_delay']-.5
            assert stale[-1]['status']==connectivity[-1]['status']=='resolved'
            assert stale[0]['id']==stale[-1]['id'] and connectivity[0]['id']==connectivity[-1]['id']
            assert any(e['type']=='target_detected' and e['id']==detected['message_id'] for e in events)
        episodes[episode]={'repetition':repetition,'drone_id':drone,'command_id':initial['decision_id']+':0',
                           'public_offline_samples_s':offline,'target':detected,'final_command_result':ack}
    client.close(episode)
    return {'passed':True,'scope':world['fixture']['scope'],'blackout':blackout,'lost_ack':lost_ack,
            'radio_episodes':episodes,'expected_archive_statuses':dict.fromkeys(episodes,'time_limit')}


def verify(result,output_root):
    signature=None
    for episode,info in result['radio_episodes'].items():
        directory=output_root/'core-runs'/episode
        samples=[];queued={};drops=[];command_received=[];command_drops=0;finished_outside=None
        for row in IndexedRecords(directory/'truth').json_records():
            kind=row['record_type'];data=row['payload']
            if kind=='message_dropped':drops.append((round(row['time'],8),data['source_id'],data.get('attempt'),data['reason']))
            elif kind=='message_queued' and data['source_id']==info['drone_id']:queued[data['message_id']]=row
            elif kind=='command_packet_dropped':command_drops+=1
            elif kind=='local_command_received':command_received.append(data)
            elif kind=='agent_telemetry':
                drone=next(a for a in data['agents'] if a['id']==info['drone_id'])
                samples.append((row['time'],drone['position'],drone['communication']['reachable']))
                if (not drone['communication']['reachable'] and drone['physical']['active_command_id']==info['command_id'] and
                        drone['physical']['route_finished'] and finished_outside is None):finished_outside=row['time']
        assert drops,'No actual packet loss recorded'
        first_offline=next(t for t,_,linked in samples if not linked)
        if result['blackout']:
            assert all(not linked for _,_,linked in samples)
            assert not command_received and command_drops>0
            info.update(first_offline_s=first_offline,packet_drops=len(drops),command_attempts=command_drops)
            continue
        if result['lost_ack']:
            assert finished_outside is not None and first_offline<finished_outside<info['final_command_result']['updated_at']
            assert max(p[0] for _,p,_ in samples)>186
            for row in IndexedRecords(directory/'public').json_records():
                if row['record_type']=='command_result':assert row['payload']['execution_status']!='completed'
            info.update(partition_start_s=first_offline,route_physically_finished_s=finished_outside,packet_drops=len(drops))
            continue
        first_online=next(t for t,_,linked in samples if linked and t>first_offline)
        target=info['target'];packet=queued[target['message_id']]
        assert packet['payload']['initial_delivery'] is None
        assert first_offline<=target['observed_at']<first_online<target['received_at']
        assert target['observed_at']==packet['time']
        assert max(p[0] for _,p,_ in samples)>186
        assert sum(r['command_id']==info['command_id'] and r['successful_start'] for r in command_received)==1
        info.update(partition_start_s=first_offline,rejoined_s=first_online,packet_drops=len(drops),command_drops=command_drops)
        current=(round(first_offline,8),round(first_online,8),round(target['received_at'],8),drops)
        if signature is None:signature=current
        else:assert current==signature,'Same seed and route changed radio outcomes'
