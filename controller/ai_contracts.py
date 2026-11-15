"""Bounded AI proposals. Only the deterministic controller can authorize effects."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import uuid

from jsonschema import Draft202012Validator

from contracts.protocol import encode,strict_json


class AIError(ValueError):
    """An unavailable or invalid proposal; callers must use their safe fallback."""
    def __init__(self,message,*,details=None):
        super().__init__(message);self.details=details or {}


COMMON={
    'request_id':{'type':'string','minLength':1},
    'episode_id':{'type':'string','minLength':1},
    'plan_version':{'type':'integer','minimum':0},
    'based_on_time':{'type':'number','minimum':0},
    'valid_until':{'type':'number','minimum':0},
    'candidate_id':{'type':['string','null']},
    'reason_codes':{'type':'array','minItems':1,'maxItems':8,
                    'items':{'type':'string','minLength':1,'maxLength':100}},
    'explanation':{'type':'string','minLength':1,'maxLength':600},
}
SCHEMAS={
    'global':{'type':'object','additionalProperties':False,
              'properties':{**COMMON,'action':{'enum':['KEEP','SELECT']}},
              'required':[*COMMON,'action']},
    'local':{'type':'object','additionalProperties':False,
             'properties':{**COMMON,'agent_id':{'type':'string','minLength':1},
                           'action':{'enum':['KEEP','DETOUR','HOLD','ESCALATE']}},
             'required':[*COMMON,'agent_id','action']},
}
VALIDATORS={role:Draft202012Validator(schema) for role,schema in SCHEMAS.items()}


def pick(value,keys):
    return {key:deepcopy(value[key]) for key in keys if key in value}


def public_agent(agent):
    result=pick(agent,('id','kind','status','position','resources','freshness','communication'))
    physical=agent.get('physical',{})
    result['physical']=pick(physical,('remaining_wh','consumed_wh','unlimited_energy',
        'velocity_m_s','state','stop_reason','active_command_id','active_waypoint','carrying',
        'cargo_target_id','service_remaining_s','radius_m','speed_limit_m_s'))
    if physical.get('unlimited_energy') is False and 'reserve_wh' in physical:
        result['physical']['reserve_wh']=physical['reserve_wh']
    return result


def public_knowledge(observation):
    zones=observation.get('zones',())
    def zone_rank(zone):
        received=zone.get('received_at')
        if type(received) not in (int,float):received=0
        dynamic=zone.get('type') in ('hazard','restricted','low_connectivity') or bool(received)
        return not dynamic,-zone.get('risk',0),-received,zone.get('id','')
    selected_zones=sorted(zones,key=zone_rank)[:48]
    result={
        'agents':[public_agent(a) for a in observation['agents']],
        'targets':[pick(t,('id','status','position','priority','deadline','evacuation_state','freshness'))
                   for t in observation['targets']],
        'events':[pick(e,('id','kind','type','time','severity','agent_id','target_id'))
                  for e in observation.get('events',())],
        'zones':[pick(z,('id','kind','type','geometry','access','risk','cost','restrictions','freshness',
                         'surface','observed_at','received_at'))
                 for z in selected_zones],
    }
    if len(zones)>len(selected_zones):
        result['zone_count']={'delivered':len(zones),'included':len(selected_zones)}
    return result


@dataclass(frozen=True)
class AIRequest:
    """Immutable bytes prevent an asynchronous caller from changing the prompt."""
    role:str
    wire:bytes

    @property
    def data(self):return strict_json(self.wire,maximum_bytes=256*1024)

    @property
    def fingerprint(self):return hashlib.sha256(self.wire).hexdigest()


def make_request(role,observation,plan_version,candidates,*,agent_id=None,trigger='planning',
                 memory=(),lifetime_s=25,request_id=None,task=None):
    if role not in SCHEMAS:raise ValueError('Unknown AI role')
    if type(plan_version) is not int or plan_version<0:raise ValueError('Invalid AI plan version')
    if not 0<lifetime_s<=60:raise ValueError('AI lifetime must be in (0,60] seconds')
    data={'request_id':request_id or uuid.uuid4().hex,'episode_id':observation['episode_id'],
          'plan_version':plan_version,'based_on_time':observation['time'],
          'valid_until':observation['time']+lifetime_s,'role':role,'trigger':trigger,
          'memory':deepcopy(list(memory)[-8:])}
    if role=='global':
        data['knowledge']=public_knowledge(observation)
        data['candidates']=[pick(c,('id','eligible','gate_reason','routes','forecast','continuations',
            'scout_mode','scout_tasks','policy_weights','utility')) for c in candidates]
    else:
        agent=next((a for a in observation['agents'] if a['id']==agent_id),None)
        if agent is None:raise ValueError('Unknown local agent')
        data['agent_id']=agent_id;data['agent']=public_agent(agent)
        if task is not None:data['task']=pick(task,('goal','target_id','cargo_target_id'))
        # An agent's private advisor is not given the team's other fresh reports.
        data['candidates']=deepcopy(list(candidates))
    wire=encode(data)
    if len(wire)>256*1024:raise AIError('AI_INPUT_TOO_LARGE')
    return AIRequest(role,wire)


def example_response(request,action='KEEP',candidate_id=None):
    data=request.data
    result={key:data[key] for key in ('request_id','episode_id','plan_version','based_on_time','valid_until')}
    result.update(action=action,candidate_id=candidate_id,reason_codes=['no_verified_improvement'],
                  explanation='Keep the current plan unless a supplied alternative has a verified benefit.')
    if request.role=='local':result['agent_id']=data['agent_id']
    return result


def validate_proposal(request,proposal,*,episode_id,plan_version,now):
    errors=list(VALIDATORS[request.role].iter_errors(proposal))
    if errors:raise AIError('AI_SCHEMA_INVALID: '+errors[0].message[:180])
    data=request.data
    if episode_id!=data['episode_id'] or proposal['episode_id']!=episode_id:raise AIError('AI_WRONG_EPISODE')
    if plan_version!=data['plan_version'] or proposal['plan_version']!=plan_version:raise AIError('AI_STALE_PLAN')
    for key in ('request_id','based_on_time','valid_until'):
        if proposal[key]!=data[key]:raise AIError('AI_ENVELOPE_MISMATCH: '+key)
    if now<data['based_on_time'] or now>data['valid_until']:raise AIError('AI_EXPIRED')
    if request.role=='local' and proposal['agent_id']!=data['agent_id']:raise AIError('AI_WRONG_AGENT')
    candidate=next((c for c in data['candidates'] if c['id']==proposal['candidate_id']),None)
    if proposal['action']=='KEEP':
        if proposal['candidate_id'] is not None:raise AIError('AI_KEEP_HAS_EFFECT')
    else:
        if candidate is None:raise AIError('AI_UNKNOWN_CANDIDATE')
        if request.role=='global' and not candidate.get('eligible'):raise AIError('AI_INELIGIBLE_STRATEGY')
        if request.role=='local' and candidate['action']!=proposal['action']:raise AIError('AI_ACTION_MISMATCH')
    return candidate
