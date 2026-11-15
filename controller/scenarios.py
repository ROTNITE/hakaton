"""Contest scenario choices and traceable games from public Core state."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math

from contracts.expressions import Expression, UNKNOWN
from contracts.protocol import ProtocolError
from controller.navigation import Box, RouteFailure
from controller.baselines import FixedWorkflow
from controller.problem_builder import usable_energy
from controller.scenario_program import ProgramError, ScenarioProgram, coalition_rules


COVERAGE='coverage_search'
PRIORITY='priority_response'
COALITION='temporary_coalition'
SAFETY='safe_degradation'
COORDINATION='coordination_reconfiguration'
SYNTHESIS='relay_briefing_and_aid_v1'
QUIET={'failed','offline','unknown','safe_mode'}


def configuration(scenarios,parameters=None,declaration=None):
    return {'scenario_ids':list(scenarios),'parameters':parameters or {},'synthesized_scenario':declaration}


def roles_for(agents):
    return {agent['id']:'scout' if agent['kind']=='aerial' else 'rescuer' for agent in agents
            if agent['kind'] in ('aerial','ground') and agent['status'] not in QUIET}


def on_channel(agent):
    return agent.get('communication',{}).get('reachable') is True and agent['status'] not in QUIET


def risk_of(observation):
    quality=observation.get('observation_quality',{})
    return min(1,.4*quality.get('stale_data_ratio',0)+.3*quality.get('unknown_state_ratio',0)+
               .3*min(1,quality.get('maximum_delay',0)/5))


@dataclass
class Candidate:
    identifier: str
    applicable: bool
    utility: float
    risk: float
    roles: dict
    evidence: dict
    reasons: list
    parameters: dict | None = None

    def report(self,selected):
        return {'scenario_id':self.identifier,'applicable':self.applicable,
                'utility':self.utility,'risk':self.risk,'selected':selected,
                'rejected_reason_codes':[] if selected else self.reasons or ['lower_rank_or_retained_plan'],
                'game':self.evidence}


class ScenarioGames:
    def __init__(self,capabilities):
        self.catalog=capabilities['supported_scenarios']
        self.radio_range=capabilities.get('radio_model',{}).get('range_m',0)
        self.predicates={key:{phase:[Expression(node) for node in nodes]
            for phase,nodes in declaration['applicability'].items()} for key,declaration in self.catalog.items()}

    def _candidate(self,identifier,observation,roles,feasible,utility,values,parameters=None):
        results=[expression.evaluate(observation) for expression in self.predicates[identifier]['entry']]
        applicable=feasible and bool(roles) and all(result is True for result in results)
        reasons=[]
        if not feasible or not roles:reasons.append('hard_constraints_or_roles')
        if any(result is UNKNOWN for result in results):reasons.append('unknown_entry_fact')
        elif not all(result is True for result in results):reasons.append('entry_predicate_false')
        declaration=self.catalog[identifier]['game_model']
        players={agent:role for agent,role in roles.items()}
        risk=risk_of(observation)
        outcome={'N':players,'A':{agent:declaration['strategies'][role] for agent,role in players.items()},
                 'I':{'observation_id':observation['request_id'],'sources':declaration['information_sources']},
                 'U':values,'K':{'role_feasible':bool(roles),'physical_and_resource_precheck':feasible},
                 'Theta':{'risk':risk,'uncertainties':declaration['uncertainty']},
                 'E':declaration['stability_criterion']}
        return Candidate(identifier,applicable,utility if applicable else 0.,risk,roles,outcome,reasons,parameters)

    def evaluate(self,observation,policy):
        agents=observation['agents'];active=roles_for(agents);remaining=observation['mission']['termination']['horizon']-observation['time']
        position={a['id']:a['position'] for a in agents}
        disputes={record['target_id'] for record in observation.get('metaevolution',{}).get('contradictions',())
                  if 'target_id' in record}
        targets=[t for t in observation['targets'] if t.get('status')=='confirmed' and t.get('position') is not None and
                 t.get('evacuation_state')=='waiting' and t.get('confidence',0)>=.5 and t['id'] not in disputes]
        target=min(targets,key=lambda t:(-t.get('priority',0),tuple(t['position']),t['id']),default=None)
        coverage=len(policy.completed_sectors);total=len(policy.builder.sectors) if policy.builder else 0
        coverage_gain=1-coverage/max(1,total)
        search=self._candidate(COVERAGE,observation,active,remaining>0,
            coverage_gain,{'uncovered_fraction':coverage_gain,'confirmed_targets':len(targets)})

        carriers=[a for a in agents if active.get(a['id'])=='rescuer' and on_channel(a) and
                  (usable_energy(a) is None or usable_energy(a)>0)]
        best_eta=None
        if target:
            start_times=[math.dist(a['position'],target['position'])/a['physical']['speed_limit_m_s'] for a in carriers
                         if a.get('physical',{}).get('speed_limit_m_s',0)>0]
            if start_times:best_eta=min(start_times)+14
        priority_score=target.get('priority',0)/(1+best_eta/max(1,remaining)) if target and best_eta is not None else 0.
        priority=self._candidate(PRIORITY,observation,{a['id']:'rescuer' for a in carriers},
            best_eta is not None and best_eta<remaining,priority_score,{'priority_value':priority_score,
                'lower_bound_eta_s':best_eta,'target_id':target['id'] if target else None},
            {'target_id':target['id']} if target else None)

        relay,executor,point=self._relay_pair(observation,policy,target)
        team={relay['id']:'relay',executor['id']:'executor'} if relay and executor else {}
        coalition_gain=1/max(1,len(agents)) if team else 0.
        parameters=None
        if team:
            x,y,z=target['position']
            # The ground planner resolves the supported chassis height.
            parameters={'relay_position':point,'target_position':[x,y,z],
                        'target_id':target['id'],'resource_id':'medical_kits',
                        'amount':min(executor['aid_stock']['medical_kits'],target['aid_required']-target['aid_received'])}
        coalition=self._candidate(COALITION,observation,team,remaining>50 and bool(team),
            coalition_gain+(target['priority'] if team else 0),
            {'expected_channel_gain':coalition_gain,'relay_travel_m':math.dist(relay['position'],point) if team else None,
             'estimated_help_priority':target['priority'] if team else None},parameters)

        blocked=[a for a in agents if on_channel(a) and not a.get('physical',{}).get('carrying') and
                 a.get('physical',{}).get('stop_reason') in ('hazard_on_route','obstacle_on_route')]
        affected={a['id']:'safe_holder' for a in blocked}
        safety=self._candidate(SAFETY,observation,affected,bool(affected),float(len(affected)),
            {'safe_holds_available':len(affected),'actual_stop_evidence':sorted(affected)})

        failed=[a['id'] for a in agents if a['status']=='failed']
        restoration=len(active)/max(1,len(active)+len(failed))
        commit=getattr(policy,'global_commit',None)
        desired=active
        changed=False
        if commit and not failed:
            used=commit['participants']|{a['id'] for a in agents if a.get('physical',{}).get('carrying')}
            desired={aid:role for aid,role in active.items() if role!='rescuer' or aid in used}
            accepted=observation.get('metaevolution',{}).get('plan',{}).get('desired_role_assignments',{})
            changed=desired!=accepted
        reconfiguration=self._candidate(COORDINATION,observation,desired,bool(failed or changed),restoration,
            {'confirmed_failed_agents':failed,'available_roles':len(active),'retained_capability_ratio':restoration,
             'failure_positions':{agent:position[agent] for agent in failed},
             'validated_global_role_change':changed,'global_strategy':commit['strategy_id'] if changed else None})
        return {c.identifier:c for c in (search,priority,coalition,safety,reconfiguration)}

    def _relay_pair(self,observation,policy,target):
        if not target or self.radio_range<=0 or target.get('aid_required',0)<=target.get('aid_received',0):
            return None,None,None
        map_data=observation.get('metaevolution',{}).get('announced_map')
        if not map_data:return None,None,None
        box=Box.parse(map_data['bounds']);base=map_data['base_position']
        held=FixedWorkflow.hold_orders(observation)
        idle=lambda a:a['id'] not in held and (a['id'] not in policy.jobs or not policy.jobs[a['id']].pending)
        relays=[a for a in observation['agents'] if a['kind']=='aerial' and 'relay' in a['capabilities'] and
                on_channel(a) and idle(a) and (usable_energy(a) is None or usable_energy(a)>2)]
        executors=[a for a in observation['agents'] if a['status']=='offline' and a['position'] is not None and
                   'deliver' in a['capabilities'] and a.get('aid_stock',{}).get('medical_kits',0)>0 and
                   not a.get('physical',{}).get('carrying') and idle(a)]
        choices=[]
        for executor in executors:
            for relay in relays:
                for fraction in (.4,.5,.6):
                    xy=[base[i]+fraction*(executor['position'][i]-base[i]) for i in range(2)]
                    for altitude in sorted({15.,max(15.,relay['position'][2])}):
                        pose=[*xy,altitude]
                        if any(not box.minimum[i]+2<pose[i]<box.maximum[i]-2 for i in range(3)):continue
                        if max(math.dist(pose,base),math.dist(pose,executor['position']))>.85*self.radio_range:continue
                        cost=math.dist(pose,relay['position'])+math.dist(executor['position'],target['position'])
                        choices.append((cost,tuple(pose),relay['id'],executor['id'],relay,executor))
        if not choices:return None,None,None
        _,pose,_,_,relay,executor=min(choices,key=lambda item:item[:4])
        return relay,executor,list(pose)


class ScenarioCoordinator:
    def __init__(self,capabilities):
        self.capabilities=capabilities;self.games=ScenarioGames(capabilities)
        self.program=None;self.program_id=None
        self.last_change=-60;self.last_safe=-60;self.seen_failures=set()
        self.finished_targets=set();self.trace=[];self.evaluation=None
        self.evaluated_strategy=None;self.role_confirmation=None

    def prepare(self,observation,policy):
        policy.scenario_reserved=set(self.program.reserved_agents) if self.program else set()
        plan=observation['metaevolution']['plan']
        ids=plan['accepted_configuration']['scenario_ids']
        if ids==[SAFETY] and observation['time']<self.last_safe+6:
            policy.scenario_reserved.update(aid for aid,role in plan['desired_role_assignments'].items() if role=='safe_holder')
        self.evaluation=self.games.evaluate(observation,policy)
        self.evaluated_strategy=getattr(policy,'global_commit',None)
        coalition=self.evaluation[COALITION]
        if (not self.program and ids and ids!=[SAFETY] and observation['time']-self.last_change>=8 and
                coalition.applicable and coalition.parameters['target_id'] not in self.finished_targets):
            policy.scenario_reserved.update(coalition.roles)

    def apply(self,observation,result,policy):
        plan=observation['metaevolution']['plan']
        accepted=plan['accepted_configuration'];ids=accepted['scenario_ids'];now=observation['time']
        candidates=self.evaluation
        if candidates is None or self.evaluated_strategy is not getattr(policy,'global_commit',None):
            candidates=self.games.evaluate(observation,policy)
        self.evaluation=None
        active=roles_for(observation['agents'])
        chosen=next((identifier for identifier in ids if identifier in candidates),COVERAGE)
        if self.program:
            chosen=COALITION
            if self.program_id not in ids:
                raise ProgramError('The accepted configuration lost its active program')
            reserved=self.program.reserved_agents
            held=reserved & FixedWorkflow.hold_orders(observation).keys()
            if held:
                self.trace.append({'type':'scenario_waiting_for_operator_release','time':now,
                    'scenario_id':self.program_id,'agent_ids':sorted(held),'reason':'active_operator_hold'})
            if not held and not any(command['agent_id'] in reserved for command in result['commands']):
                proposed=self.program.propose(observation,plan['plan_revision'],
                    route=lambda command,agent:self._route(command,agent,observation,policy))
                if proposed:
                    start=len(result['commands']);indices=list(range(start,start+len(proposed)))
                    result['commands'].extend(proposed)
                    result.setdefault('metaevolution',{}).setdefault('command_groups',[]).append(
                        {'id':'scenario-phase','command_indices':indices})
                    self.program.bind(result,indices)
            self.trace.extend(self.program.drain())
            if self.program.outcome:
                finished=self.program.outcome;target=self.program.parameters['target_id'];self.finished_targets.add(target)
                self.trace.append({'type':'scenario_outcome','scenario_id':self.program_id,'target_id':target,'time':now,'outcome':finished})
                if finished=='safe_degradation':
                    # The relay and executor stop only when able to do so.
                    # An uncontactable actor retains its latest local command.
                    safe={a['id']:'safe_holder' for a in observation['agents'] if a['id'] in reserved and
                          on_channel(a) and self._safe_to_hold(a)}
                    candidates[SAFETY]=self.games._candidate(SAFETY,observation,safe,bool(safe),float(len(safe)),
                        {'safe_holds_available':len(safe),'reason':'phase_failed',
                         'failed_program':self.program_id})
                    self._set_safe(result,observation,safe)
                    self.last_safe=now;chosen=SAFETY
                else:
                    self._set(result,'switch',configuration([COVERAGE]),active);chosen=COVERAGE
                self.program=None;self.program_id=None;self.last_change=now
        elif ids and result['operation']=='keep':
            chosen=self._choose(observation,result,policy,candidates,active) or chosen
        result['candidate_evaluations']=[candidate.report(identifier==chosen or
            identifier in result['selected_configuration']['scenario_ids']) for identifier,candidate in candidates.items()]
        result['constraint_checks'].extend({'constraint_id':'scenario_entry_predicates','scenario_id':identifier,
            'status':'passed' if candidate.applicable else 'unknown' if 'unknown_entry_fact' in candidate.reasons else 'failed'}
            for identifier,candidate in candidates.items())
        return result

    def _choose(self,observation,result,policy,candidates,active):
        now=observation['time'];accepted=observation['metaevolution']['plan']['accepted_configuration']
        ids=accepted['scenario_ids'];roles=result['role_assignments']
        if ids==[SAFETY]:
            if now>=self.last_safe+6:
                self._set(result,'switch',configuration([COVERAGE]),active);self.last_change=now
                return COVERAGE
            return None
        if now-self.last_change<8:return None
        reconfiguration=candidates[COORDINATION]
        failed=set(reconfiguration.evidence['U']['confirmed_failed_agents'])
        if reconfiguration.applicable and failed-self.seen_failures:
            self.seen_failures.update(failed)
            self._set(result,'switch',configuration([COORDINATION]),active)
            policy.request_replan(reason='confirmed_coordination_reconfiguration')
            self.last_change=now;return COORDINATION
        coalition=candidates[COALITION]
        if coalition.applicable and coalition.parameters['target_id'] not in self.finished_targets and self._start_program(result,coalition):
            self.last_change=now;return COALITION
        safety=candidates[SAFETY]
        if safety.applicable and now-self.last_safe>=45 and not any(
                c['agent_id'] in safety.roles and c['action']!='hold' for c in result['commands']):
            self._set_safe(result,observation,safety.roles)
            self.last_safe=self.last_change=now;return SAFETY
        priority=candidates[PRIORITY]
        if priority.applicable and priority.utility>=.55 and ids==[COVERAGE]:
            parameters={'by_scenario':{COVERAGE:accepted['parameters'],PRIORITY:priority.parameters}}
            self._set(result,'compose',configuration([COVERAGE,PRIORITY],parameters),active)
            policy.request_replan(planners=('rescue',),reason='confirmed_priority_task')
            self.last_change=now;return PRIORITY
        if PRIORITY in ids:
            goal=accepted['parameters']['by_scenario'][PRIORITY]['target_id']
            delivered=any(t['id']==goal and t.get('evacuation_state')=='evacuated' for t in observation['targets'])
            if delivered:
                self._set(result,'switch',configuration([COVERAGE]),active);self.last_change=now;return COVERAGE
        if (ids in ([COVERAGE],[COORDINATION]) and reconfiguration.applicable and
                reconfiguration.evidence['U']['validated_global_role_change'] and
                self._delivered_motion(observation,result,policy)):
            request_id=policy.global_commit['request_id']
            role_changes={aid:reconfiguration.roles.get(aid) for aid in set(roles)|set(reconfiguration.roles)
                          if roles.get(aid)!=reconfiguration.roles.get(aid)}
            self._set(result,'switch',configuration([COORDINATION]),reconfiguration.roles)
            self.role_confirmation=(observation['metaevolution']['plan']['plan_revision']+1,
                                    result['decision_id'],request_id,role_changes)
            self.trace.append({'type':'global_roles_proposed','time':now,'decision_id':result['decision_id'],
                               'request_id':request_id,'roles':role_changes})
            self.last_change=now;return COORDINATION
        if ids==[COVERAGE]:
            old_interval=accepted['parameters'].get('observation_interval',2.8)
            delay=observation.get('observation_quality',{}).get('maximum_delay',0)
            interval=round(min(12,max(2.8,delay+.8)),1)
            if abs(interval-old_interval)>=1:
                self._set(result,'modify',configuration([COVERAGE],{'observation_interval':interval}),roles)
                self.last_change=now;return COVERAGE
        return None

    @staticmethod
    def _safe_to_hold(agent):
        body=agent.get('physical',{})
        return (not body.get('carrying') and body.get('state') not in ('loading','unloading','charging','charge_wait') and
                any(action['action']=='hold' for action in agent['available_actions']))

    def _set_safe(self,result,observation,roles):
        agents={a['id']:a for a in observation['agents']}
        commanded={c['agent_id'] for c in result['commands']}
        self._set(result,'switch',configuration([SAFETY]),roles)
        result['commands'].extend({'agent_id':aid,'action':'hold','parameters':{}} for aid in roles
                                  if aid not in commanded and self._safe_to_hold(agents[aid]))

    @staticmethod
    def _delivered_motion(observation,result,policy):
        agents={a['id']:a for a in observation['agents']}
        for aid,job in policy.jobs.items():
            if not job.pending or job.pending==result['decision_id']:continue
            agent=agents.get(aid,{})
            if agent.get('status')=='failed':continue
            if job.action!='follow_route' or agent.get('physical',{}).get('active_command_id')!=f'{job.pending}:{job.pending_index}':
                return False
        return True

    def _start_program(self,result,coalition):
        if any(c['agent_id'] in coalition.roles for c in result['commands']):return False
        declaration=deepcopy(self.games.catalog[COALITION])
        synthesize=coalition.evidence['U']['estimated_help_priority']>=.9 or coalition.risk>=.2
        parameters=dict(coalition.parameters)
        declaration['execution_rules']=coalition_rules(synthesized=synthesize)
        if synthesize:
            declaration.update(id=SYNTHESIS,title='Relay coverage with acknowledged executor briefing')
            schema=declaration['parameter_schema']
            schema['properties']['executor_id']={'type':'string','minLength':1};schema['required'].append('executor_id')
            parameters['executor_id']=next(agent for agent,role in coalition.roles.items() if role=='executor')
        try:self.program=ScenarioProgram(declaration,parameters,coalition.roles,self.capabilities,
                                         known_rules=[coalition_rules()] if synthesize else ())
        except (ProgramError,ProtocolError) as error:
            self.trace.append({'type':'scenario_synthesis_rejected','reason':str(error)});return False
        self.program_id=declaration['id']
        self.program.started=self.program.entered=result['time']
        self._set(result,'synthesize' if synthesize else 'switch',
                  configuration([self.program_id],parameters,declaration if synthesize else None),coalition.roles)
        return True

    @staticmethod
    def _set(decision,operation,selected,roles):
        decision.update(operation=operation,selected_configuration=selected,role_assignments=roles)
        decision['explanation']['reason_codes'].append('scenario_'+operation)

    @staticmethod
    def _route(command,agent,observation,policy):
        announced=observation['metaevolution']['announced_map']
        try:points=policy._route(announced,agent,observation['agents'],command['parameters']['target'])
        except RouteFailure:return None
        return {'agent_id':agent['id'],'action':'follow_route','parameters':{'waypoints':points}}

    def observe(self,response):
        if self.program:self.program.observe(response)
        if self.role_confirmation:
            revision,decision_id,request_id,expected=self.role_confirmation
            observation=response['observation']
            observed_revision=observation['metaevolution']['plan']['plan_revision']
            agents={a['id']:a for a in observation['agents']}
            delivered=all(aid in agents and agents[aid]['role']==role and
                          agents[aid].get('configuration_revision')==revision for aid,role in expected.items())
            if delivered or observed_revision>revision:
                self.trace.append({'type':'global_roles_delivered' if delivered else 'global_roles_superseded',
                                   'time':observation['time'],'decision_id':decision_id,
                                   'request_id':request_id,'roles':expected,'plan_revision':revision})
                self.role_confirmation=None

    def drain(self):
        records=self.trace;self.trace=[];return records
