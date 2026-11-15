"""Core decisions built from delivered state and the last accepted plan."""
from copy import deepcopy
import uuid


def decision(observation,*,commands=(),operation='keep',selected=None,roles=None,previous=None):
    plan=observation.get('metaevolution',{}).get('plan')
    if plan is not None:
        accepted=deepcopy(plan['accepted_configuration'])
        assignments=deepcopy(plan['desired_role_assignments'])
    elif previous is not None:
        accepted=deepcopy(previous['selected_configuration'])
        assignments=deepcopy(previous['role_assignments'])
    else:
        accepted={'scenario_ids':[],'parameters':{},'synthesized_scenario':None}
        assignments={}
    return {'protocol_version':'1.0','episode_id':observation['episode_id'],
            'decision_id':uuid.uuid4().hex,'request_id':uuid.uuid4().hex,
            'time':observation['time'],'operation':operation,
            'previous_configuration':{'scenario_ids':accepted['scenario_ids'],'role_assignments':assignments},
            'selected_configuration':selected if selected is not None else accepted,
            'candidate_evaluations':[],'role_assignments':roles if roles is not None else assignments,
            'commands':list(commands),'constraint_checks':[],
            'explanation':{'observation_refs':[observation['request_id']],
                           'reason_codes':['fixed_rescue_workflow'],'expected_effects':[], 'confidence':1.}}
