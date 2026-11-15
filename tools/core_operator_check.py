"""Exercise operator lifecycle through the advertised public Core service."""
from __future__ import annotations

from copy import deepcopy
import math

from contracts.protocol import ProtocolError, validate_episode_response
from controller.baselines import FixedWorkflow
from controller.operator_directives import FORMAT, OperatorDirectives
from tools.native_archive import IndexedRecords


def drive(client, world, decision):
    capabilities = client.capabilities()
    assert FORMAT in capabilities['extensions']
    response = client.reset(seed=world['settings']['seed'])
    observation = response['observation']
    operator = next(a['id'] for a in observation['agents'] if a['kind']=='operator')
    ground = next(a['id'] for a in observation['agents'] if a['kind']=='ground')
    drone = next(a['id'] for a in observation['agents'] if a['kind']=='aerial')
    handler = OperatorDirectives(capabilities)
    policy = FixedWorkflow()
    submitted, results, interpretations, received, public_orders = {}, {}, [], [], []
    restriction_id = None
    load_hold_id = None
    requested_stale = False
    cancelled_restriction = False
    loaded_hold = []
    observed_loading_conflict = False
    shadow = None

    for _ in range(220):
        if response['status']!='running':
            break
        now = observation['time']
        projected = handler.prepare(observation)
        request = policy.decide(projected)
        handler.apply(projected, request)
        checks = request.get('metaevolution', {}).get('operator_interpretation', {}).get('requirements', ())
        interpretations.extend({'time':now, **row} for row in checks)
        orders = {row['id']:row for row in observation['mission']['directives']}
        public_orders.extend({'time':now, **deepcopy(row)} for row in orders.values())
        body = next(a for a in observation['agents'] if a['id']==ground)
        physical = body['physical']
        if physical.get('carrying') and physical.get('stop_reason')=='external_hold':
            loaded_hold.append({'time':now,'position':body['position'],'cargo':physical['cargo_target_id']})
        observed_loading_conflict |= any(row['outcome']=='waiting_for_safe_service_boundary' for row in checks)

        def issue(label, **parameters):
            if label in submitted:
                return
            index = len(request['commands'])
            request['commands'].append({'agent_id':operator,'action':'issue_directive','parameters':parameters})
            submitted[label] = {'command_id':request['decision_id']+':'+str(index),'time':now,'parameters':parameters}

        def change(label, action, ident, **parameters):
            order = orders.get(ident)
            if order:
                issue(label, action=action, directive_id=ident, expected_revision=order['revision'],
                      reason='operator_fixture_'+label, **parameters)

        if now>=1:
            issue('ambiguous', action='message', text='Maybe survey near the old building; recipient unclear',
                  duration_s=60, confidence=.35, reason='operator_incomplete_report')
        ambiguous = submitted.get('ambiguous', {}).get('command_id')
        if now>=4 and ambiguous in orders:
            change('clarify_pending', 'clarify', ambiguous, instruction={'action':'hold','target_id':drone,
                'duration_s':30,'confidence':.4,'reason':'await_explicit_confirmation'})
        if 'clarify_pending' in submitted and orders.get(ambiguous, {}).get('status')=='pending_confirmation' and now>=7:
            change('confirm', 'confirm', ambiguous)
        if now>=10 and orders.get(ambiguous, {}).get('status')=='active':
            change('ask_confirmation','request_confirmation',ambiguous)
        if now>=14 and 'ask_confirmation' in submitted:
            change('cancel_hold','cancel',ambiguous)
        known = next((t for t in observation['targets'] if t.get('status')=='confirmed'),None)
        if known and now>=12:
            issue('priority', action='set_priority', target_id=known['id'], priority=1,
                  duration_s=60, reason='operator_lower_priority')
        priority_id = submitted.get('priority', {}).get('command_id')
        if priority_id in orders and now>=16:
            change('clarify_priority','clarify',priority_id,instruction={'action':'set_priority',
                'target_id':orders[priority_id]['target_id'],'priority':3,'duration_s':60,'reason':'operator_urgent_priority'})
        if 'clarify_priority' in submitted and orders.get(priority_id,{}).get('priority')==3 and not requested_stale:
            invalid = decision(observation,commands=[{'agent_id':operator,'action':'issue_directive','parameters':{
                'action':'cancel','directive_id':priority_id,'expected_revision':1,'reason':'stale_operator_change'}}])
            try:
                client.step(invalid)
            except ProtocolError as error:
                assert error.code=='INVALID_COMMAND',error
                assert client.observation()['time']==now
                requested_stale=True
            else:
                raise AssertionError('Stale operator requirement revision accepted')
        if now>=20:
            issue('restriction', action='restrict_zone', bounds={'min':[75,5,0],'max':[88,16,5]},
                  allowed_kinds=['aerial'],duration_s=60,reason='operator_forbid_damaged_road')
            restriction_id=submitted['restriction']['command_id']
        if restriction_id in orders and now>=35:
            change('cancel_restriction','cancel',restriction_id)
            cancelled_restriction=True
        if now>=38 and priority_id in orders:
            change('cancel_priority','cancel',priority_id)
        if physical.get('state')=='loading' and 'load_hold' not in submitted:
            issue('load_hold', action='hold',target_id=ground,duration_s=14,reason='operator_hold_during_loading')
            load_hold_id=submitted['load_hold']['command_id']
        if load_hold_id in orders and len(loaded_hold)>=4:
            change('cancel_loaded_hold','cancel',load_hold_id)
        # A second operator cannot edit another operator's requirement.
        if ambiguous in orders and shadow is None and now>=4:
            shadow={'action':'cancel','directive_id':ambiguous,'expected_revision':orders[ambiguous]['revision'],
                    'reason':'foreign_operator_requirement'}
            outsider=next(a['id'] for a in observation['agents'] if a['kind']=='digital')
            invalid=decision(observation,commands=[{'agent_id':outsider,'action':'issue_directive','parameters':shadow}])
            try:client.step(invalid)
            except ProtocolError as error:
                assert error.code=='INVALID_COMMAND'
                assert client.observation()['time']==now
            else:raise AssertionError('Non-operator issued a directive')
        response=validate_episode_response(client.step(request),step=True)
        policy.observe_response(response)
        handler.observe(response)
        observation=response['observation']
        for row in response['command_results']:
            results[row['command_id']]=row
        inbox=next(a for a in observation['agents'] if a['id']==operator)['communication'].get('inbox',())
        received.extend(deepcopy(row) for row in inbox if row not in received)
        if (cancelled_restriction and requested_stale and observed_loading_conflict and len(loaded_hold)>=4 and
                'cancel_loaded_hold' in submitted and now>submitted['cancel_loaded_hold']['time']+10):
            break
    required={'ambiguous','clarify_pending','confirm','ask_confirmation','cancel_hold','priority',
              'clarify_priority','cancel_priority','restriction','cancel_restriction','load_hold','cancel_loaded_hold'}
    assert required<=submitted.keys(),required-submitted.keys()
    assert requested_stale and shadow
    for label in required:
        assert results[submitted[label]['command_id']]['execution_status']=='completed',(label,results.get(submitted[label]['command_id']))
    outcomes={row['outcome'] for row in interpretations}
    assert {'request_clarification','request_confirmation','applied_priority','applied_restriction','cancelled',
            'waiting_for_safe_service_boundary','proposed_hold','retained_hold'}<=outcomes,outcomes
    assert received,'No reply delivered to the operator inbox'
    feedback=[row for row in received if row['payload'].get('format')==FORMAT]
    assert feedback and any(row['payload']['confirmation_reply'] for row in feedback)
    assert all(row['received_at']>row['payload']['observed_at'] for row in feedback)
    assert len(loaded_hold)>=4 and len({row['cargo'] for row in loaded_hold})==1
    assert max(math.dist(loaded_hold[0]['position'],row['position']) for row in loaded_hold)<.02
    zones={row['id'] for row in observation['zones']}
    assert 'operator-restriction-'+restriction_id not in zones
    assert not observation['mission']['priorities']
    episode=observation['episode_id']
    client.close(episode)
    return {'passed':True,'scope':'Core public operator lifecycle, controller interpretation and delivered feedback',
            'episode_id':episode,'time':observation['time'],'commands':submitted,'results':results,
            'interpretations':interpretations,'feedback_messages':feedback,'orders':public_orders,
            'loaded_hold_samples':loaded_hold,'stale_revision_rejected':requested_stale,
            'non_operator_rejected':True,'expected_archive_statuses':{episode:'failed'}}


def verify(result, output_root):
    episode=result['episode_id']
    directory=output_root/'core-runs'/episode
    delivered=[]
    telemetry=[]
    restricted_positions=[]
    restriction=result['commands']['restriction']['command_id']
    starts=[row for row in result['orders'] if row['id']==restriction and row['status']=='active']
    cancelled=[row for row in result['orders'] if row['id']==restriction and row['status']=='cancelled']
    assert starts and cancelled
    begin=starts[0]['issued_at']
    end=cancelled[0]['updated_at']
    for row in IndexedRecords(directory/'truth').json_records():
        if row['record_type']=='peer_message_delivered' and row['payload']['payload'].get('format')==FORMAT:
            delivered.append(row['payload']['message_id'])
        elif row['record_type']=='agent_telemetry':
            telemetry.extend(row['payload']['agents'])
            if begin<=row['time']<end:
                ground=next(a for a in row['payload']['agents'] if a['kind']=='ground')
                restricted_positions.append(ground['position'])
    assert {row['message_id'] for row in result['feedback_messages']}<=set(delivered)
    assert max(a['physical'].get('vehicle_contacts',0) for a in telemetry)==0
    assert restricted_positions and not any(75<=p[0]<=88 and 5<=p[1]<=16 and 0<=p[2]<=5 for p in restricted_positions)
    result['native_feedback_verified']=len(delivered)
    result['vehicle_contacts']=0
    result['restricted_ground_samples']=len(restricted_positions)
