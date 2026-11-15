"""Asynchronous two-problem planning over the common physical workflow."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import math
import time

from controller.baselines import FixedWorkflow
from controller.navigation import observed_surfaces
from controller.optimization import optimize_rescue,optimize_scout
from controller.problem_builder import ProblemBuilder,mobiles
from controller.strategies import continuation_forecast,propose

PAIRS={'greedy_greedy':('greedy','greedy'),'frontier_local':('frontier','local'),
       'nsga2_greedy':('nsga2','greedy'),'greedy_nsga2':('greedy','nsga2'),
       'nsga2_nsga2':('nsga2','nsga2')}


def heuristic_rescue(problem,kind):
    genome=problem.heuristic('greedy');evaluations=0
    def score(g):
        nonlocal evaluations
        evaluations+=1;f=problem.simulate(g)[0]
        return f[0]*1000000+f[1]*2+f[2]
    if kind=='local' and problem.n:
        value=score(genome)
        for _ in range(3):
            improved=False
            for i in range(problem.n):
                for j in range(i+1,problem.n):
                    candidate=(genome[0][:],genome[1][:]);candidate[0][i],candidate[0][j]=candidate[0][j],candidate[0][i]
                    result=score(candidate)
                    if result+1e-8<value:genome=candidate;value=result;improved=True
            for j in range(problem.n):
                for r in range(problem.m):
                    if r==genome[1][j]:continue
                    candidate=(genome[0][:],genome[1][:]);candidate[1][j]=r;result=score(candidate)
                    if result+1e-8<value:genome=candidate;value=result;improved=True
            if not improved:break
    objectives,tasks=problem.simulate(genome);evaluations+=1
    return {'routes':{c.id:[problem.targets[j].id for j,_,_,_ in tasks[r]] for r,c in enumerate(problem.crew)},
            'genome':genome,'selected_objectives':list(objectives),'pareto':[],
            'stats':{'algorithm':kind,'evaluations':evaluations}}


class EvolutionPolicy(FixedWorkflow):
    def __init__(self,*,pair='nsga2_nsga2',seed=2026,strategy_candidates=False,
                 population_scout=40,generations_scout=32,population_rescue=26,generations_rescue=17,
                 executor=None,rescue_initializer='heuristic'):
        if pair not in PAIRS:raise ValueError('Unknown algorithm pair')
        if rescue_initializer not in ('heuristic','assignment'):raise ValueError('Unknown rescue initializer')
        if rescue_initializer!='heuristic' and PAIRS[pair][1]!='nsga2':
            raise ValueError('Assignment initialization requires NSGA-II rescue')
        super().__init__()
        self.pair=pair;self.seed=seed;self.strategy_candidates_enabled=strategy_candidates
        self.budgets=(population_scout,generations_scout,population_rescue,generations_rescue)
        self.rescue_initializer=rescue_initializer
        self.executor=executor or ThreadPoolExecutor(max_workers=2,thread_name_prefix='public-planner')
        self.owns_executor=executor is None
        self.builder=None;self.futures={};self.traces=[];self.generation=0
        self.completed_sectors=set();self.scout_queues={};self.scout_active={};self.arrivals={}
        self.scan_positions={};self.scan_altitudes={};self.scout_goals={}
        self.rescue_queues={};self.last_rescue_signature=None;self.last_rescue_at=-100
        self.latest_strategy_candidates=[];self.strategy_profile='balanced';self.current_observation=None
        self.last_scout_result=None;self.last_rescue_result=None;self.patrol_round=0
        self.patrol_mode='coverage'
        self.priority_patrol={}
        self.replan_revisions={'scout':0,'rescue':0};self.replan_requested=set()
        self.planning_surfaces=()

    def close(self):
        if self.owns_executor:self.executor.shutdown(wait=True,cancel_futures=True)

    def reset_episode(self,episode_id):
        super().reset_episode(episode_id)
        for entry in self.futures.values():entry['future'].cancel()
        self.futures={};self.builder=None;self.generation+=1
        self.completed_sectors=set();self.scout_queues={};self.scout_active={};self.arrivals={};self.rescue_queues={}
        self.scan_positions={};self.scan_altitudes={};self.scout_goals={};self.strategy_profile='balanced'
        self.current_observation=None
        self.last_rescue_signature=None;self.last_rescue_at=-100;self.latest_strategy_candidates=[]
        self.last_scout_result=None;self.last_rescue_result=None;self.patrol_round=0
        self.patrol_mode='coverage'
        self.priority_patrol={}
        self.replan_revisions={'scout':0,'rescue':0};self.replan_requested=set()
        self.planning_surfaces=()

    def _update_navigation(self,observation):
        surfaces=observed_surfaces(observation)
        self.known_surfaces=surfaces
        if self.builder is None:
            self.builder=ProblemBuilder(observation['metaevolution']['announced_map'],surfaces=surfaces)
            self.planning_surfaces=surfaces
        elif surfaces!=self.planning_surfaces:
            self.planning_surfaces=surfaces
            self.builder=ProblemBuilder(observation['metaevolution']['announced_map'],surfaces=surfaces,altitudes=self.scan_altitudes)
            self.latest_strategy_candidates=[]
            self._trace('navigation_knowledge_updated',observed_surfaces=len(surfaces),
                        blocked_surfaces=sum(s.ground_blocked for s in surfaces))
            self.request_replan(reason='delivered_surface_change')

    def request_replan(self,*,planners=('scout','rescue'),reason):
        planners=tuple(planners)
        if not planners or set(planners)-self.replan_revisions.keys() or not isinstance(reason,str) or not 0<len(reason)<=200:
            raise ValueError('Invalid replan request')
        if self.current_observation is None:raise ValueError('Replanning requires a delivered observation')
        for name in set(planners):
            self.replan_revisions[name]+=1;self.replan_requested.add(name)
        # Running workers retain their slots. Repeated triggers cannot enqueue
        # unbounded replacements or cancel a physical action/cargo transaction.
        self._trace('planning_replan_requested',planners=list(planners),reason=reason,revisions=dict(self.replan_revisions))

    def _trace(self,kind,**payload):
        self.traces.append({'type':kind,'episode_id':self.episode,'time':self.current_observation['time'],**payload})

    def drain_traces(self):
        output,self.traces=self.traces,[]
        return output

    def _solve_scout(self,builder,observation,excluded,patrol,mode='coverage'):
        began=time.perf_counter();data=builder.scout(observation,excluded,mode=mode);problem=data.problem
        kind=PAIRS[self.pair][0]
        if kind=='nsga2':
            plan=optimize_scout(problem,self.seed+int(observation['time']*100),
                                population=self.budgets[0],generations=self.budgets[1],mode=mode)
        else:
            routes=problem.heuristic(kind)
            assignment=[0]*problem.n
            for r,route in enumerate(routes):
                for j in route:assignment[j]=r
            genome=([j for route in routes for j in route],assignment)
            objectives,feasible=problem.simulate(genome) if problem.m else ((0,0,0),[])
            plan={'routes':{c.id:[problem.sectors[j].id for j in feasible[r]] for r,c in enumerate(problem.crew)},
                  'selected_objectives':list(objectives),'pareto':[],
                  'stats':{'algorithm':kind,'evaluations':1 if problem.n and problem.m else 0}}
        return {'plan':plan,'positions':data.positions,'altitudes':data.altitudes,
                'patrol':patrol,'scout_mode':mode,'build_and_solve_wall_s':time.perf_counter()-began}

    def _solve_rescue(self,builder,observation,jobs,profile=None,patrol_context=None):
        began=time.perf_counter();problem=builder.rescue(observation,jobs);kind=PAIRS[self.pair][1]
        candidates=[];profile=profile or self.strategy_profile;strategy_gate=None
        if self.strategy_candidates_enabled and kind=='nsga2':
            scout_tasks=builder.hazard_patrol(observation,*patrol_context) if patrol_context and problem.n and problem.m else ()
            candidates=propose(problem,self.seed,population=self.budgets[2],generations=self.budgets[3],
                               cooperative_scout_tasks=scout_tasks,rescue_initializer=self.rescue_initializer)
            plan=next((p for p in candidates if p['id']==profile),None)
            if candidates and (plan is None or (plan['id']!='balanced' and not plan['eligible'])):
                strategy_gate={'requested_profile':profile,'reason':plan['gate_reason'] if plan else 'UNKNOWN_PROFILE'}
                plan=next(p for p in candidates if p['id']=='balanced')
            if plan is None:plan=optimize_rescue(problem,self.seed,population=self.budgets[2],generations=self.budgets[3],
                                               initializer=self.rescue_initializer)
        elif kind=='nsga2':
            plan=optimize_rescue(problem,self.seed+int(observation['time']*100),
                population=self.budgets[2],generations=self.budgets[3],policy=profile,initializer=self.rescue_initializer)
        elif problem.m:plan=heuristic_rescue(problem,kind)
        else:plan={'routes':{},'stats':{'algorithm':kind,'evaluations':0,'reason':'no_available_crew'}}
        if problem.n and problem.m and 'genome' in plan and 'forecast' not in plan:
            _,tasks=problem.simulate(plan['genome'])
            continuations,forecast=continuation_forecast(tasks,problem.targets,problem.now,problem.horizon)
            plan={**plan,'continuations':continuations,'forecast':forecast}
        return {'plan':plan,'strategy_candidates':candidates,'strategy_gate':strategy_gate,
                'based_agents':{a['id']:deepcopy(a) for a in mobiles(observation,'ground')},
                'based_jobs':deepcopy(jobs),'based_on_time':observation['time'],
                'build_and_solve_wall_s':time.perf_counter()-began}

    def _poll(self):
        now=self.current_observation['time']
        available_targets={t['id'] for t in self.current_observation['targets'] if t.get('status')=='confirmed' and
                           t.get('evacuation_state','waiting')=='waiting'}
        reserved={j.target for j in self.jobs.values() if j.target}
        for kind,entry in list(self.futures.items()):
            if not entry['future'].done():continue
            del self.futures[kind]
            try:result=entry['future'].result()
            except Exception as error:
                self._trace('planning_failed',planner=kind,error_type=type(error).__name__,message=str(error));continue
            if entry['generation']!=self.generation or now-entry['time']>30:
                self._trace('planning_result_discarded',planner=kind,reason='superseded_or_stale',based_on_time=entry['time']);continue
            if entry.get('revision',0)!=self.replan_revisions[kind]:
                self._trace('planning_result_discarded',planner=kind,reason='new_replan_request',based_on_time=entry['time']);continue
            if kind=='rescue' and entry.get('strategy_profile',self.strategy_profile)!=self.strategy_profile:
                self.last_rescue_signature=None
                self._trace('planning_result_discarded',planner=kind,reason='strategy_superseded',based_on_time=entry['time']);continue
            plan=result['plan']
            if kind=='scout':
                alive={a['id'] for a in mobiles(self.current_observation,'aerial')}
                active={s for aid,s in self.scout_active.items() if aid in alive}|{s for aid,(s,_) in self.arrivals.items() if aid in alive}
                self.scout_queues={aid:[s for s in route if s not in active and
                    (result['patrol'] or s not in self.completed_sectors)] for aid,route in plan['routes'].items() if aid in alive}
                for aid in alive:
                    current=self.scout_active.get(aid) or (self.arrivals[aid][0] if aid in self.arrivals else None)
                    if current:self.scout_queues[aid]=[current]+self.scout_queues.get(aid,[])
                self.scan_positions.update(result['positions']);self.scan_altitudes.update(result['altitudes']);self.last_scout_result=result
                if result['patrol']:
                    prioritized={aid:sector for aid,sector in self.priority_patrol.items() if aid in alive and
                                 sector not in active and aid in self.scan_altitudes}
                    sectors=set(prioritized.values())
                    for aid,queue in self.scout_queues.items():self.scout_queues[aid]=[s for s in queue if s not in sectors]
                    for aid,sector in prioritized.items():
                        self.scan_positions[sector]=self.builder.positions[sector]
                        queue=self.scout_queues.setdefault(aid,[])
                        queue.insert(1 if aid in self.scout_active or aid in self.arrivals else 0,sector)
            else:
                self.rescue_queues={aid:[t for t in route if t in available_targets and t not in reserved]
                                    for aid,route in plan['routes'].items()}
                self.latest_strategy_candidates=result['strategy_candidates'];self.last_rescue_result=result
                if result.get('strategy_gate'):
                    self.strategy_profile='balanced'
                    self._trace('strategy_profile_fallback',**result['strategy_gate'],selected_profile='balanced')
            self._trace('planning_result_committed',planner=kind,based_on_time=entry['time'],result=result)

    def _schedule(self):
        observation=self.current_observation;now=observation['time']
        if self.builder is None:self._update_navigation(observation)
        alive={a['id'] for a in mobiles(observation,'aerial')}
        for aid in set(self.scout_queues)|set(self.scout_active)|set(self.arrivals):
            if aid not in alive:
                self.scout_queues.pop(aid,None);self.scout_active.pop(aid,None);self.arrivals.pop(aid,None)
                self.scout_goals.pop(aid,None)
                self.priority_patrol.pop(aid,None)
        if alive and 'scout' not in self.futures and ('scout' in self.replan_requested or not any(self.scout_queues.values())):
            active=set(self.scout_active.values())|{s for s,_ in self.arrivals.values()}
            all_sectors={s.id for s in self.builder.sectors}
            patrol=all_sectors<=self.completed_sectors
            excluded=active if patrol else self.completed_sectors|active
            if all_sectors-excluded:
                if patrol:self.patrol_round+=1
                mode=self.patrol_mode if patrol else 'coverage'
                future=self.executor.submit(self._solve_scout,self.builder,deepcopy(observation),set(excluded),patrol,mode)
                self.futures['scout']={'future':future,'time':now,'generation':self.generation,'revision':self.replan_revisions['scout']}
                self.replan_requested.discard('scout')
                self._trace('planning_started',planner='scout',patrol=patrol,scout_mode=mode)
        reserved={j.target for j in self.jobs.values() if j.target}
        available_targets = [t for t in observation['targets'] if t['id'] not in self.reconfirm_after]
        signature=tuple(sorted((t['id'],t.get('priority'),t.get('deadline')) for t in available_targets if
            t.get('status')=='confirmed' and t.get('evacuation_state','waiting')=='waiting' and t['id'] not in reserved))
        if signature and 'rescue' not in self.futures and (signature!=self.last_rescue_signature or
           'rescue' in self.replan_requested or (not any(self.rescue_queues.values()) and now-self.last_rescue_at>=10)):
            jobs={aid:{'phase':j.phase,'target_id':j.target} for aid,j in self.jobs.items()}
            planning_state = deepcopy({**observation, 'targets': available_targets})
            patrol_context=(dict(self.scout_active),dict(self.scout_goals),dict(self.scan_altitudes),set(self.scenario_reserved)) if (
                self.strategy_candidates_enabled and self.builder.positions.keys()<=self.completed_sectors) else None
            future=self.executor.submit(self._solve_rescue,self.builder,planning_state,jobs,self.strategy_profile,patrol_context)
            self.futures['rescue']={'future':future,'time':now,'generation':self.generation,'strategy_profile':self.strategy_profile,
                                    'revision':self.replan_revisions['rescue']}
            self.replan_requested.discard('rescue')
            self.last_rescue_signature=signature;self.last_rescue_at=now
            self._trace('planning_started',planner='rescue',known_target_ids=[row[0] for row in signature])

    def _scan_goal(self,agent,announced):
        aid=agent['id'];now=self.current_observation['time']
        if aid in self.arrivals:
            sector,arrived=self.arrivals[aid]
            observed=agent.get('freshness',{}).get('position',{}).get('observed_at',now)
            goal=self.scout_goals[aid]
            configuration=self.current_observation.get('metaevolution',{}).get('plan',{}).get('accepted_configuration',{})
            parameters=configuration.get('parameters',{})
            if 'by_scenario' in parameters:parameters=parameters['by_scenario'].get('coverage_search',{})
            dwell=parameters.get('observation_interval',2.8)
            if type(dwell) not in (int,float) or not 1<=dwell<=15:dwell=2.8
            if observed is None or observed<arrived+dwell or math.dist(agent['position'],goal)>5:return None
            new_sector = sector not in self.completed_sectors
            self.completed_sectors.add(sector);self.arrivals.pop(aid);self.scout_active.pop(aid,None)
            if (new_sector and self.strategy_candidates_enabled and self.builder.positions.keys() <= self.completed_sectors and
                    any(not s.restriction and (s.ground_blocked or s.cost > 1 or s.visibility < 1) for s in self.known_surfaces)):
                self.request_replan(planners=('rescue',),reason='primary_coverage_completed_with_delivered_hazards')
            self.scout_goals.pop(aid,None)
            queue=self.scout_queues.get(aid,[])
            if queue and queue[0]==sector:queue.pop(0)
            if self.priority_patrol.get(aid)==sector:
                self.priority_patrol.pop(aid)
                self._trace('hazard_patrol_completed',agent_id=aid,sector_id=sector,observed_at=observed)
            self._trace('sector_completed',agent_id=aid,sector_id=sector,observed_at=observed)
        queue=self.scout_queues.get(aid,[])
        if not queue:return None
        sector=queue[0]
        goal=self.scout_goals.get(aid) if self.scout_active.get(aid)==sector else None
        if goal is None:goal=(*self.scan_positions[sector],self.scan_altitudes[aid])
        self.scout_active[aid]=sector;self.scout_goals[aid]=goal
        return goal

    def _choose_target(self,agent,choices):
        allowed={t['id']:t for t in choices};queue=self.rescue_queues.get(agent['id'],[])
        while queue:
            target=queue.pop(0)
            if target in allowed:return allowed[target]
        return None

    def observe_response(self,response):
        received=response.get('observation')
        if received and received.get('episode_id')==self.episode:self.current_observation=received
        service_changed=any(r.get('execution_status')=='completed' and
            (job.action=='handover' or (job.phase=='park' and job.action=='follow_route'))
            for aid,job in self.jobs.items() if job.pending
            for r in response.get('command_results',()) if r['agent_id']==aid and
                r['decision_id']==job.pending and r['command_index']==job.pending_index)
        for aid,job in self.jobs.items():
            if not job.pending:continue
            if not job.charge_station and (job.action!='follow_route' or aid not in self.scout_active):continue
            result=next((r for r in response.get('command_results',()) if r['decision_id']==job.pending and
                r['agent_id']==aid and r['command_index']==job.pending_index),None)
            if job.charge_station:
                if job.action=='charge' and result and result['execution_status']=='completed':
                    self.request_replan(reason='battery_recharged')
                continue
            if result and result['execution_status']=='completed':self.arrivals[aid]=(self.scout_active[aid],response['time'])
            elif result and result['execution_status'] in ('failed','cancelled'):
                self.scout_active.pop(aid,None);self.scout_goals.pop(aid,None);self.arrivals.pop(aid,None)
        super().observe_response(response)
        if service_changed:self.request_replan(planners=('rescue',),reason='service_availability_changed')

    def decide(self,observation):
        if self.episode!=observation['episode_id']:self.reset_episode(observation['episode_id'])
        self.current_observation=observation
        self._released_jobs(observation)
        self._update_navigation(observation)
        if any(e.get('type') in ('agent_failure','agent_degradation','connectivity_loss','mission_priority_change','resource_shortage')
               for e in observation.get('events',())):
            self.request_replan(reason='delivered_mission_disturbance')
        self._poll()
        self._schedule()
        result=super().decide(observation)
        for aid in tuple(self.arrivals):
            if self.jobs[aid].charge_station:self.arrivals.pop(aid)
        result['explanation']['reason_codes']=[self.pair,'public_state_only','independent_scout_rescue_planning']
        summaries={}
        for name,entry in (('scout',self.last_scout_result),('rescue',self.last_rescue_result)):
            if entry is not None:
                plan=entry['plan']
                summaries[name]={'objectives':plan.get('selected_objectives',plan.get('nominal_objectives')),
                                 'stats':plan['stats'],'routes':plan['routes']}
        result.setdefault('metaevolution',{})['optimization']={'algorithm_pair':self.pair,'planners':summaries,
            'primary_sectors_completed':len(self.completed_sectors),'patrol_round':self.patrol_round}
        return result
