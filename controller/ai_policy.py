"""Global strategy selection and independent local route recovery over NSGA-II x2.

AI chooses an offered ID only. The physical executor and a fresh geometric check
own every route. A carrier's job and cargo survive braking and replanning.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import math

from controller.advisor import Advisors
from controller.accounting import digest
from controller.ai import utc
from controller.ai_contracts import AIError,make_request
from controller.baselines import Job
from controller.navigation import Box,NavigationMap,RouteFailure,handover_xy
from controller.policy import EvolutionPolicy
from controller.problem_builder import usable_energy
from controller.strategies import PROFILES,worthwhile


def route_signature(routes):
    return tuple(sorted((aid,tuple(route)) for aid,route in routes.items() if route))


class SupervisedPolicy(EvolutionPolicy):
    automatic_route_recovery=False

    def __init__(self,provider,*,advisors=None,local_enabled=True,**kwargs):
        kwargs['strategy_candidates']=True
        super().__init__(**kwargs)
        self.local_enabled=local_enabled
        self.automatic_route_recovery=not local_enabled
        self.advisors=advisors or Advisors(provider,
            local_timeout_s=getattr(provider,'timeouts',{}).get('local',3),
            global_timeout_s=getattr(provider,'timeouts',{}).get('global',6))
        self.ai_version=0;self.global_requested_version=-1;self.last_global_at=-100
        self.route_intents={};self.recoveries={};self.local_started=set();self.local_last={}
        self.applied={'global':0,'local':0};self.observed_blockers={}
        self.ai_command_tickets={};self.issued_tickets={}
        self.announced_digest=None
        self.agent_versions={};self.first_advisory_queue=[]
        self.global_commit=None;self.global_commands={}

    def reset_episode(self,episode_id):
        super().reset_episode(episode_id)
        self.applied={'global':0,'local':0}
        self.ai_version=0;self.global_requested_version=-1;self.last_global_at=-100
        self.route_intents={};self.recoveries={};self.local_started=set();self.local_last={};self.observed_blockers={}
        self.advisors.reset(episode_id)
        self.ai_command_tickets={};self.issued_tickets={}
        self.announced_digest=None
        self.agent_versions={};self.first_advisory_queue=[]
        self.global_commit=None;self.global_commands={}

    def _trace(self,kind,**payload):
        if kind=='navigation_knowledge_updated' or (kind=='planning_result_committed' and payload.get('planner')=='rescue'):
            self.ai_version+=1
        super()._trace(kind,**payload)

    def drain_traces(self):return [*super().drain_traces(),*self.advisors.drain_traces()]

    def close(self):
        self.advisors.close(self.current_observation,self._request_version)
        super().close()

    def _account(self,ticket,**values):
        provider=self.advisors.provider
        if ticket and provider.mode=='LIVE' and hasattr(provider,'record_outcome'):provider.record_outcome(ticket,**values)

    def _request_version(self,request):
        return self.ai_version if request.role=='global' else self.agent_versions.get(request.data['agent_id'],0)

    def _commit_global(self,candidate_id,observation,*,request_id=None,ticket=None):
        candidates=self.latest_strategy_candidates
        candidate=next((p for p in candidates if p['id']==candidate_id),None)
        baseline=next((p for p in candidates if p['id']=='balanced'),None)
        if candidate is None or baseline is None:raise AIError('AI_STRATEGY_SUPERSEDED')
        eligible,reason=worthwhile(candidate,baseline)
        if not eligible:raise AIError('AI_STRATEGY_REJECTED: '+reason)
        agents={a['id']:a for a in observation['agents']}
        reserved={j.target for j in self.jobs.values() if j.target}
        known={t['id'] for t in observation['targets'] if t.get('status')=='confirmed' and
               t['id'] not in self.reconfirm_after and
               t.get('evacuation_state','waiting')=='waiting' and t['id'] not in reserved}
        fresh={aid:[t for t in route if t not in reserved] for aid,route in candidate['routes'].items()}
        targets=[t for route in fresh.values() for t in route]
        if len(set(targets))!=len(targets) or not set(targets)<=known:raise AIError('AI_TARGET_STATE_CHANGED')
        source=self.last_rescue_result or {}
        for aid,route in fresh.items():
            if not route:continue
            agent=agents.get(aid);old=source.get('based_agents',{}).get(aid)
            if agent is None or old is None or agent['status'] in ('failed','offline','unknown'):
                raise AIError('AI_CREW_UNAVAILABLE')
            job=self.jobs.get(aid);busy=bool(job and job.target) or agent.get('physical',{}).get('carrying')
            if not busy and math.dist(agent['position'],old['position'])>2:raise AIError('AI_START_POSE_CHANGED')
            physical=agent.get('physical',{})
            if not physical.get('unlimited_energy'):
                required=candidate.get('agent_requirements',{}).get(aid)
                if required is None:raise AIError('AI_RESOURCE_PROOF_MISSING')
                remaining=usable_energy(agent)
                # The trusted optimizer already subtracts the current job's cost.
                previous_usable=required['usable_wh']
                spent=old.get('physical',{}).get('remaining_wh',0)-physical.get('remaining_wh',0)
                usable=min(remaining,previous_usable-spent) if previous_usable is not None else remaining
                if required['energy_wh']>usable:raise AIError('AI_RESOURCES_CHANGED')
        tasks={}
        if self.builder and self.builder.positions.keys()<=self.completed_sectors:
            active_sectors=set(self.scout_active.values())
            for task in candidate.get('scout_tasks',()):
                aid,sector=task['agent_id'],task['sector_id'];agent=agents.get(aid)
                next_sector=next((sid for sid in self.scout_queues.get(aid,()) if sid not in active_sectors),None)
                if (agent and agent['kind']=='aerial' and agent['status'] not in ('failed','offline','unknown','charging') and
                    aid not in self.scenario_reserved and agent.get('communication',{}).get('reachable') is not False and
                    sector in self.builder.positions and sector not in active_sectors and sector!=next_sector and
                    self.priority_patrol.get(aid)!=sector):
                    tasks[aid]=sector
        if route_signature(fresh)==route_signature(self.rescue_queues) and not tasks:raise AIError('AI_NO_ACTUAL_PLAN_CHANGE')
        before=deepcopy(self.rescue_queues);self.rescue_queues=fresh;self.strategy_profile=candidate_id
        old_slots={target:(aid,index) for aid,route in before.items() for index,target in enumerate(route)}
        changed={(aid,target) for aid,route in fresh.items() for index,target in enumerate(route)
                 if old_slots.get(target)!=(aid,index)}
        participants={aid for aid,route in fresh.items() if route}
        participants.update(aid for aid,job in self.jobs.items() if job.target or job.pending)
        mode=PROFILES[candidate_id]['scout_mode']
        self.priority_patrol=tasks
        if (tasks or self.patrol_mode!=mode) and self.builder and self.builder.positions.keys()<=self.completed_sectors:
            self.request_replan(planners=('scout',),reason='validated_global_patrol_profile')
        self.patrol_mode=mode
        self.global_commit={'request_id':request_id,'ticket':ticket,'strategy_id':candidate_id,
                            'rescue_changes':changed,'participants':participants,'confirmed':set()}
        self.last_rescue_result={**source,'plan':candidate};self.ai_version+=1;self.applied['global']+=1
        self._trace('global_strategy_applied',strategy_id=candidate_id,gate_reason=reason,
                    previous_routes=before,next_routes=fresh,forecast=candidate['forecast'],
                    continuations=candidate['continuations'],plan_version=self.ai_version,request_id=request_id,
                    future_patrol_mode=mode,hazard_scout_tasks=tasks,role_participants=sorted(participants))

    def _navigation(self,observation,agent):
        extra=self._obstacles(agent,observation['agents'])
        extra.extend(self.observed_blockers.get(agent['id'],()))
        return NavigationMap(observation['metaevolution']['announced_map'],observed_obstacles=extra,surfaces=self.known_surfaces,
                             parked_ground_peers=self._parked_ground_peers(agent,observation['agents']))

    def _fresh_route(self,observation,agent,goal,*,precise_stop=False):
        nav=self._navigation(observation,agent);air=agent['kind']=='aerial'
        radius=agent.get('physical',{}).get('chassis_radius_m',1.65 if air else 1.45)
        physical=agent.get('physical',{});job=self.jobs.get(agent['id']);approach=None
        if not air and job and job.phase=='park':approach=self._dock_approach(agent,goal)
        if air:route=nav.route(agent['position'],goal,aerial=True,radius_m=radius,half_height_m=.4,
                               cruise_altitude_m=max(agent['position'][2],goal[2]))
        else:
            target=approach[0] if approach else goal
            route=nav.road_route(agent['position'],(*target[:2],nav.ground_z(*target[:2])),radius_m=radius,precise_stop=precise_stop)
            if approach:
                tail=[route.points[-1],*approach[1:]]
                if not all(nav.clear(a,b,radius,1.1) for a,b in zip(tail,tail[1:])):
                    raise RouteFailure('Known obstacle on declared dock approach')
                route=replace(route,points=(*route.points,*(tuple(p) for p in approach[1:])),
                    distance_m=route.distance_m+sum(math.dist(a,b) for a,b in zip(tail,tail[1:])),
                    weighted_distance_m=route.weighted_distance_m+sum(nav.cost(a,b) for a,b in zip(tail,tail[1:])))
        points=[list(p) for p in route.points[1:]] or [list(goal)]
        speed=physical.get('speed_limit_m_s',0)
        if speed<=0:raise RouteFailure('No delivered speed')
        home=physical.get('dock_position_m',observation['metaevolution']['announced_map']['base_position'])
        if air:back=nav.route(points[-1],home,aerial=True,radius_m=radius,half_height_m=.4,
                              cruise_altitude_m=max(goal[2],home[2]))
        else:
            handover=handover_xy(observation['metaevolution']['announced_map'])
            departure=[points[-1],*physical.get('dock_exit_waypoints',())] if approach else [points[-1]]
            if not all(nav.clear(a,b,radius,1.1) for a,b in zip(departure,departure[1:])):
                raise RouteFailure('Known obstacle on reserved dock departure')
            back=nav.road_route(departure[-1],(*handover,nav.ground_z(*handover)),radius_m=radius)
        reserve=sum(nav.cost(a,b) for a,b in zip(departure,departure[1:])) if not air else 0
        effort=route.weighted_distance_m+back.weighted_distance_m+reserve
        estimate=effort*(.09 if air else .118)+2
        usable=usable_energy(agent)
        if usable is not None and estimate>usable:raise RouteFailure('Insufficient observed energy with return reserve')
        horizon=observation['mission']['termination']['horizon']
        if observation['time']+effort/speed+14>horizon:raise RouteFailure('Route exceeds mission horizon')
        return points,route.distance_m,estimate

    def _options(self,observation,agent,recovery):
        options=[{'id':'hold-3s','action':'HOLD','hold_s':3},
                 {'id':'escalate','action':'ESCALATE'}]
        if self.observed_blockers.get(agent['id']) or self.known_surfaces or recovery.get('reason')=='stationary_vehicle_on_route':
            try:
                intent = recovery['intent']
                route,distance,energy=self._fresh_route(observation,agent,intent['goal'],precise_stop=intent.get('precise_stop',False))
                options.insert(0,{'id':'planned-detour','action':'DETOUR','route':route,
                                  'distance_m':distance,'estimated_energy_wh':energy})
            except (RouteFailure,ValueError):pass
        return options

    def _local_submit(self,observation,agent,options,trigger):
        aid=agent['id']
        try:
            req=make_request('local',observation,self.agent_versions.get(aid,0),options,agent_id=aid,trigger=trigger,
                             memory=self.advisors.memory('local',aid),
                             task={'goal':self.route_intents[aid]['goal'],'target_id':self.jobs[aid].target,
                                   'cargo_target_id':agent.get('physical',{}).get('cargo_target_id')}
                             if trigger=='observed_route_blockage' else None)
        except AIError as error:
            self._trace('ai_request_skipped',role='local',agent_id=aid,reason=str(error))
            self.local_started.add(aid)
            return None
        submitted=self.advisors.submit(req);self.local_last[aid]=observation['time']
        return req.data['request_id'] if submitted else None

    def _apply_outcomes(self,observation):
        for outcome in self.advisors.poll(observation,self._request_version):
            req=outcome['request'];data=req.data
            if req.role=='global':
                if not outcome['accepted']:continue
                proposal=outcome['result']['proposal']
                ticket=outcome['result'].get('budget_ticket')
                if proposal['action']=='SELECT':
                    try:self._commit_global(proposal['candidate_id'],observation,request_id=data['request_id'],ticket=ticket)
                    except AIError as error:
                        self._trace('global_strategy_rejected',request_id=data['request_id'],reason=str(error))
                        self._account(ticket,controller_validated=False,rejection_reason=str(error))
                    else:self._account(ticket,controller_validated=True,controller_applied=True,
                                       application_utc=utc(),physical_application='future_queue_not_confirmed')
                else:self._account(ticket,controller_validated=True,controller_applied=False,physical_application='not_requested_keep')
                continue
            recovery=self.recoveries.get(data['agent_id'])
            if recovery is None or recovery.get('request_id')!=data['request_id']:
                if outcome['accepted'] and outcome['result']['proposal']['action']=='KEEP':
                    self._account(outcome['result'].get('budget_ticket'),controller_validated=True,
                                  controller_applied=False,physical_application='not_requested_keep')
                continue
            if outcome['accepted']:
                proposal=outcome['result']['proposal'];recovery['choice']=proposal['action']
                recovery['candidate']=outcome['candidate'];recovery['ai_validated']=proposal['action']!='KEEP'
                recovery['budget_ticket']=outcome['result'].get('budget_ticket')
                recovery['valid_until']=data['valid_until']
                if proposal['action']=='KEEP':self._account(recovery['budget_ticket'],controller_validated=True,
                    controller_applied=False,physical_application='not_requested_keep')
            else:recovery['choice']='FALLBACK';recovery['ai_validated']=False
            recovery['stage']='decided'

    def _recover(self,observation):
        commands=[];now=observation['time'];agents={a['id']:a for a in observation['agents']}
        directed=self.hold_orders(observation)
        for aid,intent in list(self.route_intents.items()):
            agent=agents.get(aid);job=self.jobs.get(aid)
            if agent is None or job is None or aid in directed or aid in self.scenario_reserved or agent['status'] in ('failed','offline','unknown'):continue
            physical=agent.get('physical',{});reason=physical.get('stop_reason','')
            active=physical.get('active_command_id')
            stationary_yield=self._stationary_yield(observation,agent)
            if (aid not in self.recoveries and job.pending and job.action=='follow_route'
                    and active==f'{job.pending}:{job.pending_index}' and
                    (reason in ('obstacle_on_route','hazard_on_route') or stationary_yield)):
                recovery={'intent':deepcopy(intent),'stage':'braking','choice':None,'request_id':None,'attempt':0,
                          'reason':'stationary_vehicle_on_route' if stationary_yield else reason}
                self.recoveries[aid]=recovery
                blocker=physical.get('route_blocker')
                if blocker and reason=='obstacle_on_route':
                    try:Box.parse(blocker)
                    except ValueError:pass
                    else:
                        records=self.observed_blockers.setdefault(aid,[])
                        if blocker not in records:records.append(deepcopy(blocker))
                        del records[:-64]
                self._trace('local_immediate_brake',agent_id=aid,reason=recovery['reason'],
                            blocker_id=physical.get('stop_obstacle'),cargo_target_id=physical.get('cargo_target_id'))
                commands.append((aid,{'agent_id':aid,'action':'hold','parameters':{}},None))
        self.blocked_agents=set(self.recoveries)
        for aid,recovery in list(self.recoveries.items()):
            agent=agents.get(aid);job=self.jobs[aid]
            if agent is None or aid in directed or aid in self.scenario_reserved or agent['status'] in ('failed','offline','unknown'):continue
            if recovery.get('ai_validated') and now>recovery.get('valid_until',now):
                recovery['ai_validated']=False;recovery['choice']='FALLBACK'
                self._account(recovery.get('budget_ticket'),controller_validated=False,rejection_reason='AI_EXPIRED_BEFORE_APPLICATION')
                self._trace('local_decision_expired',agent_id=aid,request_id=recovery['request_id'])
            if recovery['stage']=='braking' and not job.pending:
                if math.dist(agent.get('physical',{}).get('velocity_m_s',[0,0,0]),[0,0,0])>.1:continue
                if not self.advisors.available('local',aid):continue
                options=self._options(observation,agent,recovery);recovery['options']=options
                recovery['request_id']=self._local_submit(observation,agent,options,'observed_route_blockage')
                recovery['stage']='waiting' if recovery['request_id'] else 'decided'
                if not recovery['request_id']:recovery['choice']='FALLBACK'
            if recovery['stage']=='decided':
                choice=recovery['choice'];candidate=recovery.get('candidate')
                if choice in ('HOLD','ESCALATE'):
                    recovery['until']=now+(candidate.get('hold_s',3) if candidate else 3);recovery['stage']='holding'
                    if recovery.get('ai_validated'):
                        self.applied['local']+=1
                        self._trace('local_action_applied',agent_id=aid,action=choice,request_id=recovery['request_id'])
                        self._account(recovery.get('budget_ticket'),controller_validated=True,controller_applied=True,
                            application_utc=utc(),physical_application='retained_hold' if choice=='HOLD' else 'coordination_signal')
                        recovery['ai_validated']=False  # The later route is a separate controller action.
                    if choice=='ESCALATE':
                        self.last_rescue_signature=None;self.last_global_at=-100;self.global_requested_version=-1
                        self._trace('local_escalation',agent_id=aid,goal=recovery['intent']['goal'])
                else:recovery['stage']='resume'
            if recovery['stage']=='holding' and now>=recovery['until']:recovery['stage']='resume'
            if recovery['stage']=='resume' and not job.pending:
                intent = recovery['intent']
                precise = intent.get('precise_stop', False)
                applying_detour=recovery.get('ai_validated') and recovery['choice']=='DETOUR'
                try:route,_,_=self._fresh_route(observation,agent,intent['goal'],precise_stop=precise)
                except (RouteFailure,ValueError) as error:
                    recovery['stage']='holding';recovery['until']=now+3;recovery['attempt']+=1
                    if applying_detour:
                        recovery['ai_validated']=False
                        self._account(recovery.get('budget_ticket'),controller_validated=False,
                                      rejection_reason='AI_ROUTE_REVALIDATION_FAILED')
                    self._trace('local_safe_fallback_hold',agent_id=aid,reason=str(error),attempt=recovery['attempt'])
                    continue
                if applying_detour and route!=(recovery.get('candidate') or {}).get('route'):
                    applying_detour=False
                    self._account(recovery.get('budget_ticket'),controller_validated=False,
                                  rejection_reason='AI_OFFERED_ROUTE_CHANGED')
                    self._trace('local_detour_rejected',agent_id=aid,request_id=recovery['request_id'],
                                reason='AI_OFFERED_ROUTE_CHANGED')
                parameters = {'waypoints': route}
                if precise:
                    parameters['precise_stop'] = True
                commands.append((aid,{'agent_id':aid,'action':'follow_route','parameters':parameters},intent['next_phase']))
                if applying_detour:
                    self.applied['local']+=1
                    self._trace('local_action_applied',agent_id=aid,action='DETOUR',request_id=recovery['request_id'],route=route)
                    self.issued_tickets[aid]=recovery.get('budget_ticket')
                del self.recoveries[aid];self.blocked_agents.discard(aid)
        # A resumed agent must stay excluded until its replacement command has
        # been appended; otherwise the common executor emits a second route.
        self.blocked_agents.update(aid for aid,_,_ in commands)
        return commands

    def decide(self,observation):
        if self.episode!=observation['episode_id']:self.reset_episode(observation['episode_id'])
        provider=self.advisors.provider
        if hasattr(provider,'context'):
            if self.announced_digest is None:
                self.announced_digest=digest(observation.get('metaevolution',{}).get('announced_map',{}))
            provider.context['map_sha256']=self.announced_digest
        self.current_observation=observation
        self._update_navigation(observation)
        self._poll()
        self._apply_outcomes(observation)
        extra=self._recover(observation) if self.local_enabled else ()
        result=super().decide(observation)
        for aid,command,next_phase in extra:
            # This agent was blocked from the shared executor above.
            index=len(result['commands']);result['commands'].append(command)
            job=self.jobs[aid];job.pending=result['decision_id'];job.pending_index=index
            job.next_phase=next_phase;job.action=command['action'];job.acknowledgement_unknown_at=None
            ticket=self.issued_tickets.pop(aid,None)
            if ticket:
                self.ai_command_tickets[(result['decision_id'],index,aid)]=ticket
                self._account(ticket,controller_validated=True,controller_applied=True,physical_application='pending_ack',
                              related_command_id=result['decision_id']+':'+str(index),application_utc=utc())
        agents={a['id']:a for a in observation['agents']}
        for index,command in enumerate(result['commands']):
            aid=command['agent_id']
            if command['action'] in ('follow_route','move','hold','pickup','handover','inspect'):
                self.agent_versions[aid]=self.agent_versions.get(aid,0)+1
            if self.local_enabled and command['action']=='follow_route':
                self.route_intents[aid]={'goal':command['parameters']['waypoints'][-1],
                                        'next_phase':self.jobs[aid].next_phase,
                                        'precise_stop':command['parameters'].get('precise_stop',False)}
                if aid not in self.local_started and aid not in self.first_advisory_queue:self.first_advisory_queue.append(aid)
            if self.global_commit:
                job=self.jobs.get(aid)
                target=job.target if job else None
                category=None
                if (aid,target) in self.global_commit['rescue_changes'] and command['action'] in ('follow_route','pickup','handover'):
                    category='rescue'
                scout=self.last_scout_result
                if (scout and scout['patrol'] and scout['scout_mode']==self.patrol_mode!='coverage' and
                        command['action']=='follow_route' and aid in self.scout_active):
                    category='patrol'
                if category:
                    self.global_commands[(result['decision_id'],index,aid)]=(self.global_commit,category)
        for aid in list(self.first_advisory_queue):
            if aid not in agents:
                self.first_advisory_queue.remove(aid);continue
            if aid in self.recoveries or agents[aid]['status'] in ('failed','offline','unknown'):continue
            if not self.advisors.available('local',aid):continue
            submitted=self._local_submit(observation,agents[aid],[],'first_task_assigned')
            if submitted or aid in self.local_started or self.advisors.provider.mode=='OFF':
                self.local_started.add(aid);self.first_advisory_queue.remove(aid)
        if self.latest_strategy_candidates and self.global_requested_version!=self.ai_version and observation['time']-self.last_global_at>=35:
            try:
                req=make_request('global',observation,self.ai_version,self.latest_strategy_candidates,
                                 trigger='strategic_candidates_ready',memory=self.advisors.memory('global'))
            except AIError as error:self._trace('ai_request_skipped',role='global',reason=str(error))
            else:self.advisors.submit(req)
            self.last_global_at=observation['time'];self.global_requested_version=self.ai_version
        result['metaevolution']['ai']={**self.advisors.status(),'plan_version':self.ai_version,
                                     'local_enabled':self.local_enabled,
                                     'local_plan_versions':dict(self.agent_versions),'first_advisories_waiting':len(self.first_advisory_queue),
                                     'applied':dict(self.applied),
                                     'safe_local_holds':list(self.recoveries)}
        return result

    def observe_response(self,response):
        super().observe_response(response)
        for command in response.get('command_results',()):
            key=(command['decision_id'],command['command_index'],command['agent_id'])
            state=command['execution_status']
            if command['validation_status']=='rejected' or command['delivery_status'] in ('expired','lost'):state='rejected'
            if state in ('completed','failed','cancelled','rejected'):
                ticket=self.ai_command_tickets.pop(key,None)
                self._account(ticket,physical_application='confirmed' if state=='completed' else state)
                origin=self.global_commands.pop(key,None)
                if origin:
                    commit,category=origin
                    command_id=f'{key[0]}:{key[1]}'
                    self._trace('global_command_result',request_id=commit['request_id'],
                                strategy_id=commit['strategy_id'],category=category,command_id=command_id,
                                agent_id=key[2],action=command['action'],outcome=state)
                    if state=='completed':
                        if not commit['confirmed']:
                            self._account(commit['ticket'],physical_application='confirmed',related_command_id=command_id)
                        commit['confirmed'].add(category)
