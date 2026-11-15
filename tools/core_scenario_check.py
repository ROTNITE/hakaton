"""Independent wire checks for accepted and delivered plan revisions."""
from copy import deepcopy

from contracts.protocol import ProtocolError
from tools.native_archive import IndexedRecords


def drive(client,world,decision):
    caps=client.capabilities()
    assert set(caps['supported_operations'])=={'keep','select','switch','modify','compose','synthesize','safe_stop'}
    assert len(caps['supported_scenarios'])==5
    observation=client.reset(seed=world['settings']['seed'])['observation']
    ground=next(a['id'] for a in observation['agents'] if a['kind']=='ground')
    aerial=next(a['id'] for a in observation['agents'] if a['kind']=='aerial')
    checks=[]

    def state(agent):
        return next(a for a in observation['agents'] if a['id']==agent)

    def selected(ids,parameters=None,synth=None):
        return {'scenario_ids':ids,'parameters':{} if parameters is None else parameters,'synthesized_scenario':synth}

    def submit(**kwargs):
        nonlocal observation
        request=decision(observation,**kwargs)
        response=client.step(request)
        observation=response['observation']
        return request,response

    def reject(code,**kwargs):
        before=observation['time']
        try:submit(**kwargs)
        except ProtocolError as error:assert error.code==code,error
        else:raise AssertionError('Invalid plan was accepted')
        assert client.observation()['time']==before

    def advance(ticks):
        for _ in range(ticks):submit()

    assert world['settings']['communication_latency_s']==1.25
    start=state(aerial)['position']
    goal=[*start[:2],start[2]+8]
    move={'agent_id':aerial,'action':'move','parameters':{'target':goal}}
    roles={aerial:'scout',ground:'rescuer'}
    first,_=submit(operation='select',selected=selected(['coverage_search']),roles=roles,commands=[move])
    assert observation['metaevolution']['plan']['plan_revision']==1
    assert state(aerial)['role'] is None and state(aerial)['configuration_revision']==0
    invalid=selected(['coverage_search'],{'observation_interval':999})
    reject('INVALID_SCENARIO',operation='modify',selected=invalid,roles=roles)
    _,updated=submit(operation='modify',selected=selected(['coverage_search'],{'observation_interval':2}),roles=roles)
    old=next(row for row in updated['command_results'] if row['decision_id']==first['decision_id'])
    assert old['execution_status']=='cancelled' and old['reason_code']=='superseded_plan',old
    assert old['plan_revision']==1 and state(aerial)['configuration_revision']==0
    advance(2)
    assert state(aerial)['configuration_revision']==2 and state(aerial)['scenario_ids']==['coverage_search']
    assert abs(state(aerial)['position'][2]-start[2])<.05,state(aerial)
    assert client.step(first)['time']==1
    checks.append('obsolete queued route cancelled while a new revision waits for delivery')

    change=selected(['coordination_reconfiguration'])
    submit(operation='switch',selected=change,roles={ground:'rescuer'})
    assert state(aerial)['scenario_ids']==['coverage_search']
    assert observation['metaevolution']['plan']['desired_role_assignments']=={ground:'rescuer'}
    advance(3)
    assert state(aerial)['configuration_revision']==3 and state(aerial)['scenario_ids']==[] and state(aerial)['role'] is None
    checks.append('release retains old delivered role until a new release arrives')

    names=['coverage_search','coordination_reconfiguration']
    compose=selected(names,{'by_scenario':dict.fromkeys(names,{}),'disjoint_agent_assignments':True})
    reject('INVALID_SCENARIO',operation='compose',selected=compose,roles=roles)
    compose['scenario_participants']={names[0]:[aerial],names[1]:[ground]}
    submit(operation='compose',selected=compose,roles=roles)
    advance(3)
    assert state(aerial)['scenario_ids']==[names[0]] and state(ground)['scenario_ids']==[names[1]]
    request=decision(observation)
    request['previous_configuration']['scenario_ids']=names[::-1]
    request['selected_configuration']['scenario_ids']=names[::-1]
    response=client.step(request);observation=response['observation']
    assert observation['metaevolution']['plan']['plan_revision']==4
    checks.append('composition enforces disjoint membership and ignores scenario order')

    completed={'op':'eq','left':{'path':'execution.phase_commands_completed'},'right':{'value':True}}
    synth=deepcopy(caps['supported_scenarios']['coverage_search'])
    synth.update(id='fixture_survey_then_hold',title='Survey at the declared point, then hold',
        allowed_actions=['move','hold'],parameter_schema={'type':'object','properties':{}},
        execution_rules={'grammar':'metaevolution.fsm.v1','initial_state':'survey','deadline_seconds':30,'states':[
            {'id':'survey','commands':[{'role':'scout','action':'move','parameters':{'target':goal}}],
             'transition':{'success_when':completed,'on_success':'hold','on_failure':'fallback'},
             'timeout':{'seconds':15,'on_timeout':'fallback'}},
            {'id':'hold','commands':[{'role':'scout','action':'hold','parameters':{}}],
             'transition':{'success_when':completed,'on_success':'success','on_failure':'fallback'},
             'timeout':{'seconds':6,'on_timeout':'fallback'}},
            {'id':'success','outcome':'success'},{'id':'fallback','outcome':'safe_degradation'}]})
    broken=deepcopy(synth);broken['execution_rules']['states'][0]['transition']['on_success']='absent'
    reject('INVALID_SCENARIO',operation='synthesize',selected=selected([synth['id']],synth=broken),roles={aerial:'scout'})
    bad_predicate=deepcopy(synth)
    bad_predicate['execution_rules']['states'][0]['transition']['success_when']={
        'op':'ge','left':{'value':True},'right':{'value':1}}
    reject('INVALID_SCENARIO',operation='synthesize',selected=selected([synth['id']],synth=bad_predicate),roles={aerial:'scout'})
    unknown_constraint=deepcopy(synth)
    unknown_constraint['constraints'][0]['predicate']={'op':'ge','left':{'path':'metrics.undelivered_resource'},'right':{'value':1}}
    reject('CONSTRAINT_VIOLATION',operation='synthesize',selected=selected([synth['id']],synth=unknown_constraint),roles={aerial:'scout'})
    submit(operation='synthesize',selected=selected([synth['id']],synth=synth),roles={aerial:'scout'})
    assert state(aerial)['configuration_revision']==4
    advance(3)
    assert state(aerial)['configuration_revision']==5 and state(aerial)['scenario_ids']==[synth['id']]
    submit(commands=[move]);advance(7)
    assert state(aerial)['position'][2]>start[2]+6
    checks.append('synthesized declaration is checked and its mobile primitive changes actual pose')

    _,response=submit(operation='safe_stop',selected=selected(['safe_degradation']),
        roles={aerial:'safe_holder',ground:'safe_holder'})
    for _ in range(15):
        if response['status']!='running':break
        _,response=submit()
    assert response['status']=='safe_stopped',response['status']
    episode=observation['episode_id'];client.close(episode)
    checks.append('safe stop waits for physical stability')
    return {'passed':True,'episode_id':episode,'model_time':observation['time'],'checks':checks,
            'expected_archive_statuses':{episode:'safe_stopped'}}


def drive_actions(client,world,decision):
    actions=client.capabilities()['supported_actions']
    assert {'deliver','send_message','relay'}<=set(actions)
    observation=client.reset(seed=world['settings']['seed'])['observation']
    rover=next(a['id'] for a in observation['agents'] if a['kind']=='ground')
    drone=next(a['id'] for a in observation['agents'] if a['kind']=='aerial')
    results={}

    def agent(identifier):
        return next(a for a in observation['agents'] if a['id']==identifier)

    def step(command=None):
        nonlocal observation
        request=decision(observation,commands=[] if command is None else [command])
        response=client.step(request);observation=response['observation']
        for row in response['command_results']:results[row['command_id']]=row
        return request,response

    def command(action,**parameters):
        request,response=step({'agent_id':rover,'action':action,'parameters':parameters})
        return request['decision_id']+':0',request,response

    def wait_for(condition,steps=12):
        for _ in range(steps):
            if condition():return
            step()
        assert condition(),('Expected delivered state was not reached',observation['time'],results)

    assert not agent(drone)['communication']['reachable']
    enabled,*_=command('relay',enabled=True)
    wait_for(lambda:agent(drone)['communication']['reachable'])
    assert agent(drone)['communication']['upstream_id']==rover
    assert agent(drone)['communication']['hops']==2
    message,*_=command('send_message',recipient_id=drone,payload={'kind':'route_note','key':'peer-a'})
    wait_for(lambda:results.get(message,{}).get('execution_status')=='completed')
    assert results[message]['message_id']==message and results[message]['recipient_id']==drone
    assert 'payload' not in results[message]

    target=next(t for t in observation['targets'] if t['source_id']==rover)['id']
    inspect,*_=command('inspect',target_id=target)
    wait_for(lambda:results.get(inspect,{}).get('execution_status')=='completed')
    aid,request,response=command('deliver',target_id=target,resource_id='medical_kits',amount=2)
    wait_for(lambda:results.get(aid,{}).get('execution_status')=='completed')
    assert client.step(request)==response
    assert agent(rover)['aid_stock']['medical_kits']==1
    assert next(t for t in observation['targets'] if t['id']==target)['aid_received']==2
    depleted,*_=command('deliver',target_id=target,resource_id='medical_kits',amount=2)
    wait_for(lambda:results.get(depleted,{}).get('execution_status')=='failed')
    assert agent(rover)['aid_stock']['medical_kits']==1

    disabled,*_=command('relay',enabled=False)
    wait_for(lambda:agent(drone)['status']=='offline')
    waiting,*_=command('send_message',recipient_id=drone,payload={'kind':'route_note','key':'peer-b'})
    step()
    assert results[waiting]['execution_status']=='in_progress' and 'message_id' not in results[waiting]
    restored,*_=command('relay',enabled=True)
    wait_for(lambda:results.get(waiting,{}).get('execution_status')=='completed')
    wait_for(lambda:agent(drone)['communication']['reachable'])
    assert all(results[key]['execution_status']=='completed' for key in (enabled,disabled,restored))
    episode=observation['episode_id'];client.close(episode)
    return {'passed':True,'episode_id':episode,'time':observation['time'],'rover_id':rover,'drone_id':drone,
            'aid_command_id':aid,'failed_aid_command_id':depleted,'message_ids':[message,waiting],
            'relay_command_ids':[enabled,disabled,restored],'expected_archive_statuses':{episode:'failed'}}


def verify_actions(result,output_root):
    path=output_root/'core-runs'/result['episode_id']
    actions={}
    for row in IndexedRecords(path/'truth').json_records():
        kind=row['record_type']
        if kind in ('peer_message_delivered','relay_changed','aid_transferred'):
            actions.setdefault(kind,[]).append(row)
    transfers=actions['aid_transferred']
    assert len(transfers)==1 and transfers[0]['payload']['command_id']==result['aid_command_id']
    assert transfers[0]['payload']['amount']==2 and transfers[0]['payload']['remaining']==1
    relays=actions['relay_changed']
    assert [row['payload']['command_id'] for row in relays]==result['relay_command_ids']
    assert [row['payload']['enabled'] for row in relays]==[True,False,True]
    messages=actions['peer_message_delivered']
    assert [row['payload']['message_id'] for row in messages]==result['message_ids']
    assert all(row['payload']['hops']==3 for row in messages)
    assert messages[1]['time']>relays[-1]['time']
    assert not any(row['record_type']=='peer_message_delivered' for row in IndexedRecords(path/'public').json_records())
    result.update(aid_transfer_at=transfers[0]['time'],relay_changed_at=[row['time'] for row in relays],
                  message_delivered_at=[row['time'] for row in messages],private_inbox_preserved=True)
