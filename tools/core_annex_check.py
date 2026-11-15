"""Native movement checks for the public competition annex."""
from contracts.protocol import AGENT_KINDS, ProtocolError, validate_observation
from controller.baselines import FixedWorkflow
from controller.navigation import observed_surfaces


def drive(client,world,decision):
    capabilities=client.capabilities()
    assert set(capabilities['agent_kinds'])==set(AGENT_KINDS)
    observation=validate_observation(client.reset(seed=world['settings']['seed'])['observation'])
    initial={a['kind']:a for a in observation['agents']}
    assert set(initial)==set(AGENT_KINDS)
    for kind in ('digital','operator'):
        assert initial[kind]['position'] is None
        assert 'move' not in initial[kind]['capabilities']
    assert initial['infrastructure']['position'] is not None
    moves={'underground':[24,44,initial['underground']['position'][2]],
           'surface_water':[-78,33,initial['surface_water']['position'][2]],
           'underwater':[-76,49,-4.5]}

    def move(kind,target):
        return {'agent_id':initial[kind]['id'],'action':'move','parameters':{'target':target}}

    for invalid in (move('underwater',[-85,38,1.3]),move('underground',[44,44,-7.2]),
                    move('surface_water',[-78,33,-2]),move('ground',[40,16,-5]),move('digital',[35,20,0])):
        try:client.step(decision(observation,commands=[invalid]))
        except ProtocolError as error:assert error.code=='INVALID_COMMAND',error
        else:raise AssertionError('Invalid medium access accepted')
        assert client.observation()['time']==0
    first=decision(observation,commands=[move(kind,target) for kind,target in moves.items()])
    response=client.step(first);results={}
    for _ in range(23):
        for row in response['command_results']:
            if row['decision_id']==first['decision_id']:results[row['agent_id']]=row
        observation=validate_observation(response['observation'])
        if len(results)==len(moves) and all(row['execution_status']=='completed' for row in results.values()):break
        response=client.step(decision(observation))
    final={a['kind']:a for a in observation['agents']}
    assert len(results)==len(moves),results
    observations={}
    for kind,goal in moves.items():
        actor=final[kind];start=initial[kind]['position'];end=actor['position']
        assert results[actor['id']]['execution_status']=='completed',(kind,end,results[actor['id']])
        assert actor['physical']['distance_m']>5 and actor['physical']['consumed_wh']>0
        assert abs(end[2]-goal[2])<.5,(kind,start,end,goal)
        if kind in ('surface_water','underwater'):
            assert actor['communication']['quality']>initial[kind]['communication']['quality']+.15
        observations[kind]={'id':actor['id'],'start':start,'end':end,'distance_m':actor['physical']['distance_m'],
                            'energy_wh':actor['physical']['consumed_wh'],'command_id':results[actor['id']]['command_id'],
                            'initial_link_quality':initial[kind]['communication']['quality'],
                            'final_link_quality':actor['communication']['quality']}
    episode=observation['episode_id'];client.close(episode)
    return {'passed':True,'scope':'eight public categories and three physical medium routes',
            'episode_id':episode,'time':observation['time'],'medium_routes':observations,
            'expected_archive_statuses':{episode:'failed'}}


def drive_services(client,world,decision):
    actions=client.capabilities()['supported_actions']
    assert {'compute','issue_directive'}<=set(actions)
    observation=validate_observation(client.reset(seed=world['settings']['seed'])['observation'])
    initial={a['kind']:a for a in observation['agents']}
    assert not observation['targets'] and 'orbital_observation' not in observation['metaevolution']
    results={};directives=[];passes=[]

    def apply(request):
        nonlocal observation
        response=client.step(request);observation=validate_observation(response['observation'])
        for row in response['command_results']:results[row['command_id']]=row
        directives.extend(event for event in observation['events'] if event['type']=='operator_directive')
        orbital=observation['metaevolution'].get('orbital_observation')
        if orbital and (not passes or passes[-1]!=orbital):passes.append(orbital)
        return response

    def send(commands=()):
        request=decision(observation,commands=commands);return request,apply(request)

    drone=initial['aerial'];operator=initial['operator'];compute=initial['digital'];sensor=initial['infrastructure']
    initial_z=drone['position'][2]
    compute_command={'agent_id':compute['id'],'action':'compute','parameters':{'operation':'sum','values':[17.5,3.25,-4]}}
    climb={'agent_id':drone['id'],'action':'move','parameters':{'target':[*drone['position'][:2],initial_z+30]}}
    first,response=send([compute_command,climb]);compute_id=first['decision_id']+':0'
    assert client.step(first)==response
    assert not passes
    assert results[compute_id]['execution_status']=='completed'
    calculation=results[compute_id]['service_result']
    assert calculation['value']==16.75 and calculation['credits_remaining']==15
    assert calculation['service_completed_at']>calculation['started_at']
    order={'agent_id':operator['id'],'action':'issue_directive','parameters':{
        'target_id':drone['id'],'action':'hold','duration_s':6.25,'reason':'operator_fixture_safety'}}
    issued,_=send([order]);directive_id=issued['decision_id']+':0'
    assert any(d['id']==directive_id and d['source']==operator['id'] for d in observation['mission']['directives'])
    assert passes and passes[0]['observed_at']==1 and passes[0]['received_at']>1
    assert any(sample['visibility']<1 for sample in passes[0]['visible_surface_samples'])
    assert any(surface.visibility<1 for surface in observed_surfaces(observation))
    policy=FixedWorkflow();hold=policy.decide(observation)
    action=next(i for i,c in enumerate(hold['commands']) if c['agent_id']==drone['id'])
    assert hold['commands'][action]['action']=='hold'
    assert any(row['directive_id']==directive_id and row['outcome']=='proposed_hold'
               for row in hold['metaevolution']['directive_checks'])
    apply(hold);hold_id=hold['decision_id']+':'+str(action)
    for _ in range(12):
        if any(e['id']==directive_id and e['status']=='expired' for e in directives):break
        send()
    assert results[hold_id]['execution_status']=='completed'
    assert not any(d['id']==directive_id for d in observation['mission']['directives'])
    assert any(e['id']==directive_id and e['status']=='expired' for e in directives)
    current=next(a for a in observation['agents'] if a['id']==drone['id'])
    assert initial_z+.5<current['position'][2]<initial_z+10
    sensed=next(t for t in observation['targets'] if t['source_id']==sensor['id'])
    assert sensed['received_at']>sensed['observed_at']
    episode=observation['episode_id'];client.close(episode)
    return {'passed':True,'episode_id':episode,'model_time':observation['time'],'compute':calculation,
            'compute_command_id':compute_id,'directive':directive_id,'hold_command_id':hold_id,'sensed':sensed,
            'orbital_observations':passes,'expected_archive_statuses':{episode:'failed'}}
