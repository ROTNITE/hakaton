"""v0.5 causal event simulation: overlapping patrol, discovery, rescue, AI and messages.
No optimizer or LLM receives future world events or undetected hazards/people.
"""
from __future__ import annotations
import heapq,itertools,math,random,time
from dataclasses import replace
from world import BASE,SCOUT_SCAN_S,PICKUP_S,DROPOFF_S
from scout import optimize_routes
from rescue import prepare,get_plan,eval_plan,mission_segments
from observation_engine import Knowledge
from message_bus import MessageBus
from patrol_scheduler import PatrolScheduler
from strategy_engine import StrategyEngine, PROFILES, PROFILE_SEED_OFFSETS, prioritize, worthwhile

class Mission:
    def __init__(self,world,variant='base',ai=None):
        self.w=world;self.variant=variant;self.ai=ai
        self.events=[];self.counter=itertools.count();self.t=0.
        self.knowledge=Knowledge(world);self.bus=MessageBus(world.seed,loss_rate=0.0,latency=.35)
        self.person_by_id={p.id:p for p in world.people}
        self.confirmed=set();self.pending=set();self.rescued=set();self.disabled=set()
        self.scout_segments=[];self.rescue_segments=[];self.visits=[];self.discoveries=[]
        self.scout_active={}
        self.incidents=[];self.stranding=[];self.failures=[];self.decisions=[];self.rescues=[]
        self.signals=[];self.truth_events=[];self.scout_stats={};self.replan_ms=0.;self.rescue_plans=0
        self.ground_jobs={};self.ground_token=[0]*world.n_rescuers
        self.priority_ids=[];self.last_rescue_plan=-9999.;self.next_plan_tick=-1.;self.last_global_event={}
        self.recent_optimizer=[];self.last_global_hazard=-9999
        self.plan_version=1;self.rescue_revision=0;self.scout_revision=1;self.active_scenarios=['coverage_search','priority_response'];self.start_wall=time.perf_counter();self.terrain_replans=0
        self.agent_memory={f'drone_{r+1:02d}':[] for r in range(world.n_scouts)}
        self.agent_memory.update({f'ground_{r+1:02d}':[] for r in range(world.n_rescuers)})
        self.audit=[]
        self.strategy_engine=StrategyEngine(world)
        self.strategy_policy='balanced'
        self.strategic_assignments={}
        self.strategy_expires=-1.
        self.strategy_commit_count=0
        self.strategy_forecasts=0
    def record(self,t,source,type_,**kw):
        entry={'t':round(t,4),'source':source,'type':type_,**kw}
        self.audit.append(entry)
    def schedule(self,t,kind,data=None):
        if t<=self.w.horizon+1e-8:
            heapq.heappush(self.events,(round(t,5),next(self.counter),kind,data or {}))
    def send(self,t,sender,recipient,kind,payload):
        return self.bus.send(t,sender,recipient,kind,payload,self.schedule,self.record)
    def ai_record(self,t,source,kind,**kw):
        self.record(t,source,kind,**kw)
    def scout_pose(self,r,t):
        active=self.scout_active.get(r)
        if active and t>=active['start'] and t<active['end']:
            if t<active['arrival'] and active['arrival']>active['start']:
                frac=(t-active['start'])/(active['arrival']-active['start'])
                return [active['a'][k]+(active['b'][k]-active['a'][k])*frac for k in (0,1)]
            return list(active['b'])
        return list(self.patrol.positions[r])
    def route_summary(self,r,t):
        job=self.ground_jobs.get(r)
        if job:
            k=job['index'];future=[q['b'] for q in job['segments'][k:k+12]]
            return {'id':f'ground_{r+1:02d}','position':job['position'],
                    'target_id':job['person'],'carrying':job['carrying'],
                    'eta':round(job['finish'],2),'route_next':future}
        return {'id':f'ground_{r+1:02d}','position':list(BASE),'status':'idle' if r not in self.disabled else 'disabled'}
    def global_context(self,t,reason,sector=None):
        known=[self.person_by_id[p] for p in sorted(self.confirmed-self.rescued)][:90]
        return {'reason':reason,'scout_plan_version':self.scout_revision,
                'rescue_plan_version':self.rescue_revision,'known_targets':[{'id':p.id,'priority':p.priority,'sector':p.sector,
                'x':p.x,'y':p.y} for p in known],
                'fleet':{'scouts':self.w.n_scouts,'rescuers':self.w.n_rescuers,
                         'rescue_agents':[self.route_summary(r,t) for r in range(self.w.n_rescuers)],
                         'scout_agents':[{'id':f'drone_{r+1:02d}','position':self.scout_pose(r,t),
                             'next_sectors':self.patrol.queues[r][:6]} for r in range(self.w.n_scouts)]},
                'known_hazards':self.knowledge.hazard_summary(),
                'stale_sectors':self.knowledge.recent_sectors(t,12),
                'recent_messages':[{'type':m['type'],'sender':m['sender'],'payload':m['payload']
                                    if m['type']!='SECTOR_OBSERVATION' else {'sector':m['payload']['sector']}}
                                   for m in self.bus.messages[-20:] if m['delivery_status']=='delivered'][-10:],
                'scout_priority_candidates':sorted(set([sector] if sector is not None else [])|
                    {self.w.sector_count*(y//5)+(x//5) for (x,y),(kind,_) in self.knowledge.hazards.items() if kind})[:25],
                'optimizer_candidates':self.recent_optimizer[-3:],
                'active_strategy':self.strategy_policy,
                'constraints':{'hidden_truth':'not_accessible','scout_routes':'NSGA-II-only',
                               'rescue_routes':'NSGA-II/A*-only','energy':'unlimited but counted'}}
    def install_strategy(self,t,candidate):
        """Commit a forecast-checked policy without interrupting active trips."""
        strategy=candidate['id']
        if strategy not in PROFILES:raise ValueError('unknown strategy')
        if not self.patrol.primary_complete and candidate['scout_mode']!='coverage':
            # Primary search is never preempted by optional cooperation.
            self.record(t,'validator','SCOUT_STRATEGY_DEFERRED',strategy=strategy)
        self.strategy_policy=strategy
        self.strategy_expires=t+360
        self.patrol.strategy=candidate['scout_mode'] if self.patrol.primary_complete else 'coverage'
        self.strategic_assignments={int(a['robot_id'][7:])-1:a['target_id']
             for a in candidate['assignments'][:3]
             if a['robot_id'].startswith('ground_') and a['target_id'] in self.pending
             and (int(a['robot_id'][7:])-1) not in self.disabled}
        self.strategy_commit_count+=1
        self.record(t,'plan_manager','STRATEGY_COMMITTED',
            strategy=self.strategy_policy,weights=candidate['policy_weights'],
            assignments=self.strategic_assignments,
            scout_mode=self.patrol.strategy,expires_at=self.strategy_expires)

    def trigger_global(self,t,reason,sector=None):
        if not self.ai or not self.ai.has_global:return
        # Routine target confirmation is already handled by Rescue NSGA-II.
        # An LLM should not destabilize primary coverage for each discovery.
        if reason=='target_detected':
            high=sum(self.person_by_id[p].priority>=3 for p in self.pending)
            # Ordinary discoveries need no LLM. Consider strategic involvement
            # only after coverage, with a sizable unresolved workload.
            if not self.patrol.primary_complete or self.w.initial_people<=12 or len(self.pending)<4:
                self.record(t,'global_ai','GLOBAL_SKIPPED',reason='routine_target_detection')
                return
        if reason=='hazard_confirmed' and sector is not None:
            nearby=any(job and any(self.w.sector_count*(int(q['b'][1])//5)+int(q['b'][0])//5==sector
                                   for q in job.get('segments',[])[job.get('index',0):][:18])
                       for job in self.ground_jobs.values())
            if not nearby:
                self.record(t,'global_ai','GLOBAL_SKIPPED',reason='hazard_not_affecting_active_route',sector=sector)
                return
        key=(reason,sector)
        if t-self.last_global_event.get(key,-1e9)<90:
            self.record(t,'global_ai','GLOBAL_SKIPPED',reason='duplicate_event',event=reason,sector=sector)
            return
        self.last_global_event[key]=t
        context=self.global_context(t,reason,sector)
        context['primary_coverage']={'completed':self.patrol.primary_complete,
            'unvisited':len(self.patrol.unvisited),'total':self.w.sector_count**2}
        # Strategic alternatives are computed ONLY from already delivered targets
        # and observed terrain. This is an advisory bounded known-state forecast,
        # not a clairvoyant replay of the upcoming disaster event tape.
        idle=[r for r in range(self.w.n_rescuers) if r not in self.ground_jobs and r not in self.disabled]
        available_robots=[r for r in range(self.w.n_rescuers) if r not in self.disabled
                          and not self.ground_jobs.get(r,{}).get('stuck')]
        ready_times={r:max(t,job['finish']) for r,job in self.ground_jobs.items()
                     if not job.get('stuck')}
        hazard_sectors=context['scout_priority_candidates']
        alternatives=[]
        if available_robots and self.pending and self.ai.client.active:
            alternatives=self.strategy_engine.propose(t,
                [self.person_by_id[pid] for pid in sorted(self.pending)],available_robots,
                self.knowledge.snapshot(),hazard_sectors,
                [self.scout_pose(r,t) for r in range(self.w.n_scouts)],
                self.patrol.primary_complete,ready_times=ready_times)
            self.strategy_forecasts+=1
            self.record(t,'strategy_engine','STRATEGY_CANDIDATES_EVALUATED',
                        alternatives=alternatives,knowledge_version=self.knowledge.version,
                        pending_count=len(self.pending),idle_count=len(idle),
                        future_capacity=len(available_robots)-len(idle))
        context['strategy_candidates']=alternatives
        available=set(context['scout_priority_candidates'])
        proposal,latency=self.ai.global_decide(t,{'type':reason,'sector':sector},context,
                                                   set(self.confirmed-self.rescued),available)
        if proposal:
            apply_at=t+latency
            self.schedule(apply_at,'global_apply',{'proposal':proposal,'base_version':self.plan_version,
                'candidates':alternatives,'proposed_at':t})
            self.record(t,'global_ai','GLOBAL_REPLAN_REQUESTED',effective_at=round(apply_at,4),
                        scope={'scout':proposal['scout_replan'],'rescue':proposal['rescue_replan']})
    def observe_scan(self,t,r,sector):
        w=self.w;agent=f'drone_{r+1:02d}'
        observation=self.knowledge.sense_sector(sector,t,agent)
        known_before=self.knowledge.last_seen.get(sector,-1)
        # Always deliver observations, including negative evidence, to refresh staleness.
        self.send(t,agent,'global','SECTOR_OBSERVATION',observation)
        self.agent_memory[agent].append({'t':round(t,3),'observed_sector':sector})
        self.record(t,'sensor','SECTOR_SCANNED',drone=r,sector=sector,
                    last_team_observed_at=known_before)
        quality=w.sector_visibility(sector,t)*w.sensor_reliability
        self.visits.append({'t':round(t,4),'sector':sector,'r':r,'visibility':round(quality,3)})
        for p in self.people_by_sector[sector]:
            if p.id in self.locally_found or not w.person_active(p,t):continue
            rng=random.Random(w.seed*100_003+p.id*97)
            if rng.random()>quality:continue
            self.locally_found.add(p.id)
            payload={'person_id':p.id,'position':[p.x,p.y],
                     'priority':p.priority,'sector':sector,'observed_at':round(t,4)}
            self.send(t,agent,'global','TARGET_DETECTED',payload)
            self.record(t,'sensor','TARGET_OBSERVED',agent=agent,target_id=p.id,sector=sector)
        if self.ai and self.ai.has_local and quality<.7 and sector not in self.scout_low_visibility:
            self.scout_low_visibility.add(sector)
            event={'type':'low_visibility','sector':sector,'quality':round(quality,3)}
            options=[{'id':'verify_now','type':'DETOUR','destination':[sector],
                      'duration':SCOUT_SCAN_S*1.65,'energy':.55,'risk':round(1-quality,2)},
                     {'id':'verify_later','type':'DETOUR','destination':[sector],
                      'duration':SCOUT_SCAN_S*2.5,'energy':.75,'risk':round(1-quality,2)}]
            proposal,latency=self.ai.local_decide(t,agent,event,options,
                 {'position':list(self.patrol.positions[r]),'task':'scout_sector',
                  'observed_quality':quality,'known_hazards':self.knowledge.hazard_summary(8)})
            if proposal and proposal['decision']=='DETOUR':
                self.schedule(t+latency,'local_scout_apply',{'agent':agent,'sector':sector,
                    'candidate_id':proposal['candidate']['id'],'known_version':self.knowledge.version})
        self.patrol.scanned(r,sector,t)
        self.scout_active.pop(r,None)
        self.schedule(t,'scout_ready',{'r':r})
    def scout_ready(self,t,r):
        w=self.w
        sector=self.patrol.select(r,t)
        if sector is None:
            self.schedule(t+8,'scout_ready',{'r':r});return
        p=self.patrol.positions[r];dest=w.center(sector)
        length=math.dist(p,dest)
        # Smoke is sensed at scan time; route construction never reads future true hazards.
        flight=length/w.scout_speed(r)
        arrive=t+flight;end=arrive+SCOUT_SCAN_S
        if end>w.horizon:return
        self.scout_active[r]={'start':t,'arrival':arrive,'end':end,'a':list(p),'b':list(dest),'sector':sector}
        if flight>1e-6:
            self.scout_segments.append({'r':r,'t0':round(t,4),'t1':round(arrive,4),
                'a':list(p),'b':list(dest),'e':round(.69*length,4),'action':'fly'})
        self.scout_segments.append({'r':r,'t0':round(arrive,4),'t1':round(end,4),
            'a':list(dest),'b':list(dest),'e':.55,'action':'scan'})
        self.schedule(end,'scout_scan',{'r':r,'sector':sector})
    def delivered_message(self,t,msg):
        self.bus.delivered(msg,t,self.record)
        kind=msg['type'];payload=msg['payload']
        if kind=='SECTOR_OBSERVATION':
            old={tuple(c[:2]):self.knowledge.hazards.get(tuple(c[:2]),(None,-1))[0]
                 for c in payload['cells']}
            report=self.knowledge.merge_delivered(payload,t)
            new_hazards=[c for c in report['cells'] if c[2] and old.get(tuple(c[:2]))!=c[2]]
            cleared=[c for c in report['cells'] if not c[2] and old.get(tuple(c[:2]))]
            if new_hazards or cleared:
                self.record(t,'observation','HAZARD_CONFIRMED',sector=payload['sector'],
                            changes=new_hazards+cleared,knowledge_version=self.knowledge.version)
                self.patrol.highlight([payload['sector']],t,importance=2)
                self.trigger_global(t,'hazard_confirmed',sector=payload['sector'])
                # Existing rescue routes do not magically reroute; checkpoints observe independently.
                self.request_rescue_plan(t,'terrain_observed')
        elif kind=='TARGET_DETECTED':
            pid=payload['person_id']
            if pid not in self.confirmed:
                self.confirmed.add(pid);self.pending.add(pid)
                self.discoveries.append({'t':round(t,4),'id':pid,'x':payload['position'][0],
                     'y':payload['position'][1],'priority':payload['priority'],
                     'r':int(msg['sender'].split('_')[-1])-1,'new':pid>self.w.initial_people})
                self.record(t,'observation','TARGET_CONFIRMED',target_id=pid,observer=msg['sender'])
                self.request_rescue_plan(t,'target_detected')
                self.trigger_global(t,'target_detected',sector=payload['sector'])
        elif kind=='AUDIBLE_SIGNAL':
            self.signals.append({'t':round(t,4),'type':'appearance','sector':payload['sector'],
                                 'cause':payload['cause'],'id':payload['event_id']})
            self.patrol.highlight([payload['sector']],t,importance=4)
            self.trigger_global(t,'audible_signal',sector=payload['sector'])
        elif kind in ('ROUTE_BLOCKED','HELP_REQUEST','HAZARD_WARNING'):
            self.trigger_global(t,kind.lower(),sector=payload.get('sector'))
    def request_rescue_plan(self,t,cause,force=False):
        if not self.pending:return
        # Batching avoids optimizing dozens of simultaneous discoveries.
        cooldown=3 if self.w.initial_people<=90 else 8 if self.w.initial_people<=200 else 22
        due=t if force or t-self.last_rescue_plan>=cooldown else self.last_rescue_plan+cooldown
        if self.next_plan_tick<0 or due<self.next_plan_tick-1e-5:
            self.next_plan_tick=due
            self.schedule(due,'rescue_plan',{'cause':cause})
    def dispatch_job(self,r,person,segments,start,local=False,carrying=False):
        if not segments:return False
        self.ground_token[r]+=1;token=self.ground_token[r]
        self.rescue_segments.extend(segments)
        job={'person':person.id,'segments':segments,'index':0,'token':token,
             'carrying':bool(carrying),'position':list(segments[0]['a']),
             'start':start,'finish':segments[-1]['t1'],'local':local}
        self.ground_jobs[r]=job
        self.record(start,'executor','TASK_REROUTED' if local else 'TASK_STARTED',agent=f'ground_{r+1:02d}',target_id=person.id,
                    plan_version=self.plan_version,local=local)
        self.schedule(segments[0]['t0'],'ground_advance',{'r':r,'token':token})
        return True
    def do_rescue_plan(self,t,cause):
        self.next_plan_tick=-1
        idle=[r for r in range(self.w.n_rescuers) if r not in self.ground_jobs and r not in self.disabled]
        if not idle or not self.pending:return
        cooldown=3 if self.w.initial_people<=90 else 8 if self.w.initial_people<=200 else 22
        if t-self.last_rescue_plan<cooldown-1e-5:
            self.request_rescue_plan(t,cause);return
        self.last_rescue_plan=t
        accepted=[]
        # A committed coalition may reserve the next idle robot for a specific
        # confirmed victim. Reservations never displace an active trip or carrier.
        if t<=self.strategy_expires and self.strategic_assignments:
            available_targets=set(self.pending)
            pairs=[(r,pid) for r,pid in self.strategic_assignments.items()
                   if r in idle and pid in available_targets]
            if pairs:
                wanted=[self.person_by_id[pid] for _,pid in pairs]
                _,target_trips=prepare(self.w,wanted,terrain=self.knowledge.snapshot())
                for j,(r,pid) in enumerate(pairs):
                    if r not in idle or pid not in self.pending:continue
                    tr=target_trips[r][j]
                    if not tr or t+tr['duration']>self.w.horizon:continue
                    p=self.person_by_id[pid]
                    segs,finish=mission_segments(p,r,tr,t)
                    if not segs or finish>self.w.horizon:continue
                    if self.dispatch_job(r,p,segs,t):
                        self.pending.remove(pid);idle.remove(r)
                        accepted.append({'robot':r,'person':pid,'eta':finish,'strategic':True})
                        self.record(t,'plan_manager','COALITION_ROBOT_ASSIGNED',
                                    robot=r,target_id=pid,strategy=self.strategy_policy)
                        self.strategic_assignments.pop(r,None)
        if not idle or not self.pending:
            if accepted:self.record(t,'rescue_nsga2','STRATEGIC_ASSIGNMENTS_ONLY',assignments=accepted)
            return
        people=[self.person_by_id[k] for k in sorted(self.pending)]
        limit=max(30,min(90 if self.w.initial_people<=150 else 65,self.w.n_rescuers*3))
        if len(people)>limit:
            people=sorted(people,key=lambda p:(-p.priority,math.dist((p.x,p.y),BASE),p.id))[:limit]
        boosted=[replace(p,priority=min(3,p.priority+1)) if p.id in self.priority_ids else p for p in people]
        chosen=prioritize(boosted,PROFILES[self.strategy_policy]['priority_mode'])
        # Only confirmed, delivered terrain is used by the planner.
        chosen,trips=prepare(self.w,chosen,terrain=self.knowledge.snapshot())
        avail=[t if r in idle else self.w.horizon+1 for r in range(self.w.n_rescuers)]
        genome,stats=get_plan(self.w,chosen,trips,'nsga2',
                              self.w.seed+int(t*100)+PROFILE_SEED_OFFSETS[self.strategy_policy],
                              now=t,available=avail,small=True,policy=self.strategy_policy)
        self.replan_ms+=stats.get('wall_ms',0.)
        if self.priority_ids and self.strategy_policy=='balanced':
            raw=[self.person_by_id[p.id] for p in chosen]
            base_genome,base_stats=get_plan(self.w,raw,trips,'nsga2',self.w.seed+int(t*100),
                                           now=t,available=avail,small=True)
            self.replan_ms+=base_stats.get('wall_ms',0.)
            m_ai,_=eval_plan(genome,raw,trips,now=t,available=avail,horizon=self.w.horizon)
            m_base,_=eval_plan(base_genome,raw,trips,now=t,available=avail,horizon=self.w.horizon)
            improvement=(m_base[0]-m_ai[0])*10000+(m_base[1]-m_ai[1])+ .12*(m_base[2]-m_ai[2])
            if improvement<=1e-5:
                genome=base_genome;stats=base_stats
                self.record(t,'validator','AI_PLAN_REJECTED',
                    reason='NO_MEASURABLE_BENEFIT' if abs(improvement)<1e-5 else 'QUALITY_DEGRADATION',
                    candidate=m_ai,baseline=m_base)
            else:
                self.record(t,'validator','AI_PLAN_ACCEPTED',candidate=m_ai,baseline=m_base,
                            estimated_improvement=round(improvement,5))
        _,tasks=eval_plan(genome,chosen,trips,now=t,available=avail,horizon=self.w.horizon)
        for r in idle:
            if not tasks[r]:continue
            j,start,finish,tr=tasks[r][0]
            if start>t+1e-5:continue
            p=self.person_by_id[chosen[j].id]
            if p.id not in self.pending:continue
            segs,end=mission_segments(p,r,tr,start)
            if end>self.w.horizon:continue
            if self.dispatch_job(r,p,segs,start):
                accepted.append({'robot':r,'person':p.id,'eta':end})
                self.pending.discard(p.id)
        self.rescue_plans+=1;self.rescue_revision+=1
        decision={'t':round(t,3),'cause':cause,'known':len(self.confirmed),
                  'pending':len(self.pending),'assignments':accepted,'algorithm':'nsga2',
                  'plan_version':self.plan_version,'rescue_plan_version':self.rescue_revision,
                  'strategy_policy':self.strategy_policy,
                  'compute_ms':stats.get('wall_ms',0.)}
        self.decisions.append(decision)
        self.recent_optimizer.append({'t':round(t,2),'assigned':len(accepted),
               'objectives':stats.get('selected_objectives'),'pareto':stats.get('pareto',[])[:4]})
        self.record(t,'rescue_nsga2','PLAN_EVALUATED',**{k:v for k,v in decision.items() if k!='t'})
    def crop_robot(self,r,t):
        """Cancel all future movement without retroactive changes to past energy."""
        kept=[]
        for seg in self.rescue_segments:
            if seg['r']!=r or seg['t1']<=t+1e-7:kept.append(seg);continue
            if seg['t0']>=t-1e-7:continue
            alpha=max(0,min(1,(t-seg['t0'])/max(1e-8,seg['t1']-seg['t0'])))
            partial=dict(seg);partial['b']=[seg['a'][k]+alpha*(seg['b'][k]-seg['a'][k]) for k in range(2)]
            partial['e']=seg['e']*alpha;partial['t1']=round(t,4)
            kept.append(partial)
        self.rescue_segments=kept
    def route_candidate(self,r,t,position,person,carrying,waypoint=None):
        w=self.w;agent=f'ground_{r+1:02d}'
        terrain=self.knowledge.local_snapshot(agent)
        a=(int(round(position[0])),int(round(position[1])))
        target=BASE if carrying else (person.x,person.y)
        legs=[]
        if waypoint and waypoint not in (a,target):
            first,c1=w.route(a,waypoint,terrain);second,c2=w.route(waypoint,target,terrain)
            if not first or not second:return None
            legs=first+second[1:];cost=c1+c2
        else:legs,cost=w.route(a,target,terrain)
        if not legs or not math.isfinite(cost):return None
        if not carrying:
            back,back_cost=w.route((person.x,person.y),BASE,terrain)
            if not back:return None
        else:back=[];back_cost=0.
        speed=w.ground_speed(r)
        clock=t;segments=[];energy=0.
        def add(path,weighted,speed_,factor,action):
            nonlocal clock,energy
            if len(path)<2:return
            lengths=[max(.00001,math.dist(x,y)) for x,y in zip(path,path[1:])]
            total=sum(lengths)
            for (start,end),length in zip(zip(path,path[1:]),lengths):
                share=length/total;dt=weighted/max(.001,speed_)*share;e=weighted*factor*share
                segments.append({'r':r,'t0':round(clock,4),'t1':round(clock+dt,4),
                                 'a':list(start),'b':list(end),'e':round(e,5),'action':action})
                clock+=dt;energy+=e
        if math.dist(position,a)>.0001:
            length=math.dist(position,a)
            dt=length/max(.001,speed)
            segments.append({'r':r,'t0':round(clock,4),'t1':round(clock+dt,4),
                             'a':list(position),'b':list(a),
                             'e':length*.82*w.ground_energy_factor(r),'action':'rejoin_grid'})
            clock+=dt;energy+=length*.82*w.ground_energy_factor(r)
        add(legs,cost,speed*(.79 if carrying else 1.),
            (1.18 if carrying else .82)*w.ground_energy_factor(r),
            'to_base' if carrying else 'to_person')
        if not carrying:
            segments.append({'r':r,'t0':round(clock,4),'t1':round(clock+PICKUP_S,4),
                             'a':[person.x,person.y],'b':[person.x,person.y],'e':0.,'action':'pickup'})
            clock+=PICKUP_S
            add(back,back_cost,speed*.79,1.18*w.ground_energy_factor(r),'to_base')
        segments.append({'r':r,'t0':round(clock,4),'t1':round(clock+DROPOFF_S,4),
                         'a':list(BASE),'b':list(BASE),'e':0.,'action':'dropoff'})
        clock+=DROPOFF_S
        if clock>w.horizon:return None
        return {'id':'direct' if waypoint is None else f'via_{waypoint[0]}_{waypoint[1]}',
                'type':'DETOUR','duration':round(clock-t,3),'energy':round(energy,3),
                'risk':round(0.01+(0 if waypoint is None else .025),3),
                'destination':list(target),'segments':segments}
    def candidate_routes(self,r,t,position,person,carrying):
        direct=self.route_candidate(r,t,position,person,carrying)
        if not direct:return []
        candidates=[direct];w=self.w
        x,y=int(round(position[0])),int(round(position[1]))
        # Feasible geometric alternatives around immediate obstacles, never invented geometry.
        for dx,dy in ((0,4),(0,-4),(4,0),(-4,0),(5,5),(-5,-5)):
            wp=(x+dx,y+dy)
            if not w.walkable(*wp,self.knowledge.local_snapshot(f'ground_{r+1:02d}')):continue
            c=self.route_candidate(r,t,position,person,carrying,wp)
            if not c:continue
            if c['duration']<=direct['duration']*1.55 and [s['b'] for s in c['segments'][:10]]!=[s['b'] for s in direct['segments'][:10]]:
                candidates.append(c)
            if len(candidates)>=3:break
        return candidates
    def ground_advance(self,t,r,token):
        job=self.ground_jobs.get(r)
        if not job or job['token']!=token:return
        i=job['index'];segs=job['segments']
        if i>=len(segs):return
        seg=segs[i];action=seg['action']
        if action in ('to_person','to_base','local_detour','rejoin_grid'):
            dest=(int(round(seg['b'][0])),int(round(seg['b'][1])))
            agent=f'ground_{r+1:02d}'
            previous=self.knowledge.agent_hazards.get(agent,{}).get(dest,(None,False))[0]
            observation=self.knowledge.sense_ground(dest,t,agent)
            kind=observation['cells'][0][2]
            discovered=kind and kind!=previous
            block=not self.w.walkable(*dest,self.w.terrain_at(t))
            if discovered:
                self.send(t,agent,'global','SECTOR_OBSERVATION',observation)
                self.record(t,'sensor','GROUND_HAZARD_OBSERVED',agent=agent,cell=list(dest),hazard=kind)
            if block or (discovered and kind in ('mud','road_damage')):
                self.terrain_replans+=1
                self.incidents.append({'t':round(t,4),'robot':r,'person':job['person'],
                                       'kind':kind or 'blocked','carrying':job['carrying'],
                                       'outcome':'obstacle_detected'})
                self.record(t,'safety','SAFE_STOP',agent=agent,cell=list(dest),hazard=kind,
                            carrying=job['carrying'])
                self.crop_robot(r,t)
                self.ground_token[r]+=1;self.ground_jobs.pop(r,None)
                person=self.person_by_id[job['person']]
                candidates=self.candidate_routes(r,t,list(seg['a']),person,job['carrying'])
                chosen=candidates[0] if candidates else None;delay=0.
                if self.ai and self.ai.has_local:
                    event={'type':kind or 'blocked','cell':list(dest),'t':round(t,4),
                           'observation_version':self.knowledge.version}
                    decision,delay=self.ai.local_decide(t,agent,event,candidates,
                        {'position':list(seg['a']),'task':{'target_id':person.id,'carrying':job['carrying']},
                         'known_hazards':self.knowledge.hazard_summary(16),
                         'plan_version':self.plan_version})
                    if decision:
                        if decision.get('request_global_replan') or decision['decision']=='ESCALATE':
                            self.send(t,agent,'global','HELP_REQUEST',
                                      {'sector':observation['sector'],'target_id':person.id,
                                       'carrying':bool(job['carrying']),'reason':'local_ai_support_requested'})
                        for m in decision.get('messages',[])[:3]:
                            if isinstance(m,dict) and m.get('recipient') in ('global','broadcast'):
                                self.send(t,agent,m['recipient'],m.get('type','HAZARD_WARNING'),
                                          {'sector':observation['sector'],'cell':list(dest)})
                        if decision['decision'] in ('HOLD','ESCALATE'):
                            chosen=None
                        else:chosen=decision['candidate']
                if chosen and chosen['segments']:
                    # Real API latency delays the affected robot only.
                    shift=t+delay-chosen['segments'][0]['t0']
                    shifted=[{**s,'t0':round(s['t0']+shift,4),'t1':round(s['t1']+shift,4)}
                             for s in chosen['segments']]
                    if shifted[-1]['t1']<=self.w.horizon:
                        self.dispatch_job(r,person,shifted,job['start'],local=True,
                                          carrying=job['carrying'])
                        self.record(t+delay,'local_ai' if self.ai and self.ai.has_local else 'safety',
                            'LOCAL_DETOUR_COMMITTED',agent=agent,target_id=person.id,
                            candidate_id=chosen['id'],carrying=job['carrying'],
                            delay_s=round(delay,3),estimated_energy=chosen['energy'])
                        self.incidents[-1]['outcome']='local_detour' if self.ai and self.ai.has_local else 'deterministic_detour'
                        return
                # HOLD/ESCALATE is not task cancellation. Preserve both the victim
                # reservation and carrying status until a confirmed route or transfer.
                self.ground_jobs[r]={'person':person.id,'segments':[], 'index':0,
                    'token':self.ground_token[r],'carrying':bool(job['carrying']),
                    'position':list(seg['a']),'start':job['start'],
                    'finish':self.w.horizon,'stuck':True,'hold_started':t,
                    'retry_count':0,'state':'HOLDING'}
                self.send(t,agent,'global','HELP_REQUEST',
                    {'sector':observation['sector'],'target_id':person.id,
                     'carrying':bool(job['carrying']),'reason':'no_safe_route'})
                self.record(t,'executor','TASK_HELD',agent=agent,target_id=person.id,
                    carrying=bool(job['carrying']),reason='local_hold_or_no_route')
                self.incidents[-1]['outcome']='hold_assignment_preserved'
                return
        if action=='pickup':job['carrying']=True
        job['index']+=1;job['position']=list(seg['b'])
        if job['index']<len(segs):
            self.schedule(seg['t1'],'ground_advance',{'r':r,'token':token})
        else:
            self.schedule(seg['t1'],'rescue_completed',{'r':r,'token':token,'person':job['person']})
    def resume_stuck(self,t):
        for r,job in list(self.ground_jobs.items()):
            if not job.get('stuck'):continue
            p=self.person_by_id[job['person']]
            candidates=self.candidate_routes(r,t,job['position'],p,job['carrying'])
            if candidates:
                self.ground_jobs.pop(r,None)
                self.dispatch_job(r,p,candidates[0]['segments'],job['start'],local=True,
                                  carrying=job['carrying'])
                self.record(t,'executor','HELD_TASK_RECOVERED',robot=r,person=p.id,
                    carrying=job['carrying'])
            else:
                job['retry_count']=job.get('retry_count',0)+1
                self.record(t,'executor','HELD_TASK_RETRY',robot=r,person=p.id,
                    retry_count=job['retry_count'],carrying=job['carrying'])
                # Only an uncollected person can be returned to the common queue.
                # Keep passengers onboard and retry if the robot is carrying.
                if not job['carrying'] and t-job.get('hold_started',t)>90:
                    self.ground_jobs.pop(r,None)
                    self.ground_token[r]+=1
                    self.pending.add(p.id)
                    self.record(t,'executor','TASK_RELEASED_FOR_REASSIGNMENT',
                        robot=r,person=p.id,reason='long_unreachable_without_passenger')
                    self.request_rescue_plan(t,'held_task_released')
    def run(self):
        w=self.w;start=time.perf_counter()
        initial,stats=optimize_routes(w,w.seed,population=30 if w.grid_size<=100 else 18,
                                      generations=15 if w.grid_size<=100 else 8)
        self.scout_stats=stats
        self.patrol=PatrolScheduler(w,initial)
        self.people_by_sector={s:[] for s in range(w.sector_count**2)}
        for p in w.people:self.people_by_sector[p.sector].append(p)
        self.locally_found=set();self.scout_low_visibility=set()
        for r in range(w.n_scouts):self.schedule(0,'scout_ready',{'r':r})
        for ev in w.landscape_events:self.schedule(ev['t'],'terrain_truth',ev)
        for ev in w.appearances:self.schedule(ev['t'],'appearance_signal',ev)
        for ev in w.events:self.schedule(ev['t'],'failure',ev)
        self.schedule(140,'scout_replan',{'source':'periodic'})
        self.schedule(250,'strategic_review',{})
        self.schedule(45,'stuck_retry',{})
        count=0
        while self.events:
            t,_,kind,data=heapq.heappop(self.events);self.t=t;count+=1
            if t>w.horizon:break
            if kind=='scout_ready':self.scout_ready(t,data['r'])
            elif kind=='scout_scan':self.observe_scan(t,data['r'],data['sector'])
            elif kind=='message_delivery':self.delivered_message(t,data)
            elif kind=='local_scout_apply':
                if data['known_version']<=self.knowledge.version:
                    self.patrol.highlight([data['sector']],t,importance=3)
                    self.record(t,'local_ai','REVERIFY_SECTOR_SELECTED',agent=data['agent'],
                                sector=data['sector'],candidate_id=data['candidate_id'])
            elif kind=='terrain_truth':
                self.truth_events.append(data)
                self.record(t,'environment','WORLD_EVENT_PRIVATE',kind=data['type'],cell_count=len(data.get('cells',[])))
                # No team knowledge update. Only a physical sensor can discover this hazard.
            elif kind=='appearance_signal':
                # A vague sound can be heard by a nearby scout; it carries no victim coordinates.
                close=any(math.dist(self.scout_pose(r,t),w.center(data['sector']))<30
                          for r in range(w.n_scouts))
                if close:
                    self.send(t,'acoustic_sensor','global','AUDIBLE_SIGNAL',
                              {'sector':data['sector'],'cause':data.get('cause','sound'),
                               'event_id':data['id']})
                self.record(t,'environment','PERSON_APPEARED_HIDDEN',sector=data['sector'],
                            audible_nearby=close)
            elif kind=='rescue_plan':
                if abs(t-self.next_plan_tick)<.0001:self.do_rescue_plan(t,data.get('cause','planning_tick'))
            elif kind=='robot_ready':self.request_rescue_plan(t,'robot_ready')
            elif kind=='ground_advance':self.ground_advance(t,data['r'],data['token'])
            elif kind=='rescue_completed':
                r=data['r'];job=self.ground_jobs.get(r)
                if job and job['token']==data['token'] and job['person']==data['person']:
                    p=self.person_by_id[job['person']]
                    self.rescued.add(p.id);self.ground_jobs.pop(r,None)
                    event={'t':round(t,4),'start':job['start'],'id':p.id,'x':p.x,'y':p.y,
                           'priority':p.priority,'r':r,'rerouted':bool(job.get('local'))}
                    self.rescues.append(event)
                    self.record(t,'executor','TARGET_RESCUED',agent=f'ground_{r+1:02d}',target_id=p.id)
                    self.request_rescue_plan(t,'rescue_completed')
            elif kind=='scout_replan':
                res=self.patrol.online_nsga2(t)
                if res:
                    self.scout_revision+=1
                    self.record(t,'scout_nsga2','ONLINE_REPLAN',scout_plan_version=self.scout_revision,
                                **{k:v for k,v in res.items() if k!='t'})
                self.schedule(t+140,'scout_replan',{'source':'periodic'})
            elif kind=='global_apply':
                proposal=data['proposal']
                if data['base_version']!=self.plan_version:
                    self.record(t,'validator','STALE_GLOBAL_REJECTED',base_version=data['base_version'],
                                active_version=self.plan_version)
                    continue
                operation=proposal['operation']
                if operation in ('keep','safe_stop'):
                    self.record(t,'validator','GLOBAL_NO_EFFECT',reason='KEEP_OR_SAFE_STOP',operation=operation)
                    continue
                # Validate strategic forecasts independently from the LLM's
                # prose. A proposed profile must beat the explicit balanced
                # counterfactual on known-state, 3-scenario estimates.
                plan_candidates={c['id']:c for c in data.get('candidates',[])}
                baseline=plan_candidates.get('balanced')
                chosen_strategy=plan_candidates.get(proposal.get('strategy_id'))
                strategic_change=False
                if chosen_strategy and baseline and chosen_strategy['id']!='balanced':
                    allowed,why=worthwhile(chosen_strategy,baseline)
                    if allowed and t-data.get('proposed_at',t)<=15:
                        # Preview assignments may have become occupied meanwhile;
                        # leave the actual route and task validity to Rescue NSGA-II.
                        strategic_change=chosen_strategy['id']!=self.strategy_policy
                        self.record(t,'validator','STRATEGY_FORECAST_ACCEPTED',
                            strategy=chosen_strategy['id'],reason=why,
                            baseline=baseline['forecast'],proposed=chosen_strategy['forecast'])
                    else:
                        self.record(t,'validator','STRATEGY_FORECAST_REJECTED',
                            strategy=chosen_strategy['id'],reason=why if not allowed else 'STALE_PROPOSAL',
                            baseline=baseline['forecast'],proposed=chosen_strategy['forecast'])
                        chosen_strategy=None
                evidence_sectors={self.w.sector_count*(y//5)+(x//5)
                    for (x,y),(hazard,_) in self.knowledge.hazards.items() if hazard}
                evidence_sectors.update(e['sector'] for e in self.signals if e['t']<=t)
                sectors=list(dict.fromkeys(sec for sec in proposal['scout_priority_sectors']
                                            if sec in evidence_sectors))
                requested_tasks=[task for task in proposal.get('task_proposals',[])
                    if task['sector_id'] in evidence_sectors]
                if strategic_change and chosen_strategy:
                    requested_tasks += [task for task in chosen_strategy.get('scout_tasks',[])
                                        if task['sector_id'] in evidence_sectors]
                new_ids=[pid for pid in proposal['priority_ids'] if pid in self.confirmed-self.rescued]
                # A known victim is not evidence that already scanned terrain should
                # take precedence over unvisited sectors. Rescue support requires
                # a separate specific hazard/signal, not merely a scenario label.
                scout_changed=bool(sectors or requested_tasks or proposal['scout_replan'])
                if not self.patrol.primary_complete and scout_changed:
                    self.record(t,'validator','SCOUT_REPLAN_REJECTED',
                        reason='PRIMARY_COVERAGE_PROTECTED',unvisited=len(self.patrol.unvisited),
                        proposed_sectors=sectors)
                    sectors=[];requested_tasks=[];scout_changed=False
                priority_changed=set(new_ids)!=set(self.priority_ids)
                rescue_changed=strategic_change or priority_changed or (proposal['rescue_replan'] and
                    bool(self.pending) and proposal['operation'] in ('select','switch','compose','synthesize'))
                if not scout_changed and not rescue_changed:
                    self.record(t,'validator','GLOBAL_NO_EFFECT',reason='NO_MEASURABLE_PLAN_CHANGE',
                                operation=operation)
                    continue
                # Stage changes before committing a new global version.
                if strategic_change and chosen_strategy:
                    self.install_strategy(t,chosen_strategy)
                if scout_changed:
                    for task in requested_tasks:
                        r=int(task['agent_id'][6:])-1
                        if 0<=r<self.w.n_scouts:self.patrol.preferred[r]=task['sector_id']
                    if sectors:self.patrol.highlight(sectors,t,importance=3)
                    if proposal['scout_replan']:
                        result=self.patrol.online_nsga2(t)
                        if result:
                            self.scout_revision+=1
                            self.record(t,'scout_nsga2','GLOBAL_SCOUT_REPLAN',
                                        scout_plan_version=self.scout_revision,result=result)
                        else:self.record(t,'validator','SCOUT_REPLAN_SKIPPED',reason='NO_FEASIBLE_CHANGE')
                if rescue_changed:
                    self.priority_ids=new_ids
                    self.request_rescue_plan(t,'global_policy',force=True)
                self.plan_version+=1
                if self.ai:self.ai.plan_version=self.plan_version
                # Scenarios are explanatory/ephemeral, not infinite multipliers
                # that keep pulling scouts toward previously confirmed victims.
                selected=[x for x in proposal.get('selected_scenarios',[])
                          if x!='rescue_support' or scout_changed]
                if selected:self.active_scenarios=list(dict.fromkeys(selected))
                self.record(t,'plan_manager','GLOBAL_POLICY_COMMITTED',
                    version=self.plan_version,active_scenarios=self.active_scenarios,
                    changed={'scout':scout_changed,'rescue':rescue_changed},proposal=proposal)
            elif kind=='failure':
                r=data['robot'];self.disabled.add(r)
                if r in self.ground_jobs:
                    job=self.ground_jobs.pop(r)
                    self.crop_robot(r,t);self.ground_token[r]+=1
                    if not job['carrying']:self.pending.add(job['person'])
                self.failures.append({'t':round(t,4),'robot':r,'type':'agent_failure'})
                self.record(t,'environment','AGENT_FAILURE',robot=r)
                self.request_rescue_plan(t,'agent_failure',force=True)
                self.trigger_global(t,'agent_failure')
            elif kind=='strategic_review':
                # Periodic cross-agent review supplements event-triggered calls.
                # No idle robots or pending missions -> nothing to coordinate.
                if self.ai and self.ai.has_global and self.w.initial_people>12 and len(self.pending)>=2:
                    self.trigger_global(t,'strategic_review')
                self.schedule(t+210,'strategic_review',{})
            elif kind=='stuck_retry':
                self.resume_stuck(t)
                self.schedule(t+45,'stuck_retry',{})
        return self.result()
    def result(self):
        w=self.w
        self.scout_segments.sort(key=lambda x:(x['r'],x['t0']))
        self.rescue_segments.sort(key=lambda x:(x['r'],x['t0']))
        self.discoveries.sort(key=lambda x:x['t']);self.visits.sort(key=lambda x:x['t']);self.rescues.sort(key=lambda x:x['t'])
        all_segments=self.scout_segments+self.rescue_segments
        energy=sum(s['e']*min(1,max(0,(w.horizon-s['t0'])/max(.00001,s['t1']-s['t0'])))
                   for s in all_segments if s['t0']<w.horizon)
        ai_stats=self.ai.summary() if self.ai else {'mode':'off','connected':False,'calls':0,
             'local_actions':0,'global_actions':0,'fallbacks':0,'messages':len(self.bus.messages)}
        ai_stats['messages']=len(self.bus.messages)
        ai_stats['strategic_commits']=self.strategy_commit_count
        ai_stats['strategy_forecasts']=self.strategy_forecasts
        ai_stats['last_strategy']=self.strategy_policy
        audit=sorted(self.audit+(self.ai.audit if self.ai else []),key=lambda x:x['t'])
        return {'method':self.variant,'label':{'base':'NSGA-II + NSGA-II',
                  'global_ai':'NSGA-II ×2 + Global AI',
                  'global_local_ai':'NSGA-II ×2 + Global + Local AI'}[self.variant],
                'scout_method':'nsga2','rescue_method':'nsga2',
                'scout_segments':self.scout_segments,'rescue_segments':self.rescue_segments,
                'visits':self.visits,'discoveries':self.discoveries,'signals':self.signals,
                'terrain_events':self.truth_events,'knowledge_events':self.knowledge.changes,
                'incidents':self.incidents,'stranding':self.stranding,'ai_stats':ai_stats,
                'audit':audit,'messages':self.bus.messages,'rescues':self.rescues,
                'decisions':self.decisions,'failures':self.failures,
                'opt':{'wall_ms':round(self.scout_stats.get('wall_ms',0)+self.patrol.opt_ms+self.replan_ms,1),
                       'scout_ms':round(self.scout_stats.get('wall_ms',0)+self.patrol.opt_ms,1),
                       'rescue_ms':round(self.replan_ms,1),'replans':self.rescue_plans,
                       'scout_replans':self.patrol.replans,'scout_plan_version':self.scout_revision,
                       'rescue_plan_version':self.rescue_revision,'failures':len(self.failures),
                       'terrain_replans':self.terrain_replans,'aborted_trips':len(self.incidents),
                       'stranded':len(self.stranding),'pareto':self.scout_stats.get('pareto',[])},
                'final':{'found':len(self.confirmed),'rescued':len(self.rescued),
                         'coverage':len(self.patrol.last_scanned),'total':w.n_people,
                         'new_people':len(w.appearances),'energy':round(energy,2),
                         'last_rescue':round(max((r['t'] for r in self.rescues),default=0),2),
                         'finished_at':round(min(w.horizon,max((s['t1'] for s in all_segments),default=0)),2),
                         'scans':len(self.visits),'primary_complete_at':self.patrol.primary_completed_at,
                         'scout_replans':self.patrol.replans,'strategy_commits':self.strategy_commit_count}}

def run_mission_v05(world,variant='base',ai=None):
    return Mission(world,variant,ai).run()
