"""Online two-stage mission: scouting and rescue physically overlap in time.
On target-detected / rescue-completed events, rerun rescue planner using public
knowledge only. Do not cancel a rescue trip once it is under way.
"""
from __future__ import annotations
import heapq, time, math, os
from dataclasses import replace
from world import World, BASE, ENERGY_RESERVE, DROPOFF_S, PICKUP_S
from scout import run_scout
from rescue import prepare, get_plan, eval_plan, mission_segments

CONFIGS={
  'greedy_greedy':('greedy','greedy','Greedy + Greedy'),
  'frontier_local':('frontier','local','Frontier + Local Search'),
  'nsga2_greedy':('nsga2','greedy','Scout NSGA-II + Greedy'),
  'greedy_nsga2':('greedy','nsga2','Greedy + Rescue NSGA-II'),
  'nsga2_nsga2':('nsga2','nsga2','NSGA-II + NSGA-II'),
}

def run_mission(world, config, scout_cache=None, offline_rescue_method=None, ai=None):
    if config not in CONFIGS: raise ValueError('Unknown mission config')
    scout_method,rescue_method,label=CONFIGS[config]
    if offline_rescue_method is not None:
        rescue_method=offline_rescue_method
        label='Offline · '+rescue_method
        scout={'discoveries':[{'t':0.,'id':p.id,'x':p.x,'y':p.y,
                               'priority':p.priority,'r':-1} for p in world.people
                              if p.id<=world.initial_people]
             +[{'t':a['t'],'id':a['id'],'x':next(p.x for p in world.people if p.id==a['id']),
                'y':next(p.y for p in world.people if p.id==a['id']),
                'priority':next(p.priority for p in world.people if p.id==a['id']),'r':-1}
                for a in world.appearances],
              'segments':[],'visits':[],'opt':{'wall_ms':0},'signals':[]}
    else:
        scout=(scout_cache or {}).get(scout_method)
        if scout is None:scout=run_scout(world,scout_method,small=True,ai=ai)
    person_by_id={p.id:p for p in world.people}
    heap=[];serial=0
    for item in scout['discoveries']:
        if item['t']<=world.horizon:
            serial+=1;heapq.heappush(heap,(item['t'],serial,'detected',item))
    busy_until=[0.0]*world.n_rescuers
    energy_left=[world.ground_battery]*world.n_rescuers
    pending={}; known=set();rescued=set();disabled=set();inprogress={}
    rescue_segments=[];rescue_events=[];decisions=[];failure_events=[];opt_ms=0.0
    priority_applied=[];last_planning_t=-10000;plan_revision=1
    min_replan_interval=0 if world.grid_size<=65 else 4 if world.grid_size<=100 else (14 if world.initial_people>200 else 10)
    next_planning_tick=None
    terrain_replans=0;aborted_trips=0;stranded=0;terrain_logs=[];incidents=[];stranding=[]
    for change in world.landscape_events:
        serial+=1;heapq.heappush(heap,(change['t'],serial,'terrain_change',change))
    # Positions are known to the simulator only; controllers receive observed route results.
    def pose_at(r,t):
        pieces=sorted((s for s in rescue_segments if s['r']==r),key=lambda s:s['t0'])
        pos=list(BASE)
        for seg in pieces:
            if seg['t0']>t+1e-8:break
            if seg['t1']<=t+1e-8:pos=seg['b'][:]
            elif seg['t0']<=t:
                k=(t-seg['t0'])/max(.000001,seg['t1']-seg['t0'])
                pos=[seg['a'][i]+k*(seg['b'][i]-seg['a'][i]) for i in range(2)]
                break
        return pos
    def crop_robot(r,t):
        """Remove the future part of a route, restoring unspent reserved energy."""
        nonlocal rescue_segments
        kept=[];unspent=0.
        for seg in rescue_segments:
            if seg['r']!=r or seg['t1']<=t+1e-8:
                kept.append(seg);continue
            if seg['t0']>=t-1e-8:
                unspent+=seg['e'];continue
            fraction=max(0.,min(1.,(t-seg['t0'])/max(.000001,seg['t1']-seg['t0'])))
            partial=dict(seg)
            partial['b']=[seg['a'][i]+(seg['b'][i]-seg['a'][i])*fraction for i in range(2)]
            partial['t1']=round(t,4);partial['e']=round(seg['e']*fraction,5)
            unspent+=seg['e']*(1-fraction)
            kept.append(partial)
        rescue_segments=kept
        energy_left[r]+=unspent
    def safe_return(r,person,t,pos,carrying):
        """Immediately re-route the in-flight robot on the updated terrain."""
        from rescue import mission_segments
        # Nearest grid position is used for grid routing; the first sub-cell leg
        # remains part of the simulated trajectory (no instantaneous teleport).
        terrain=world.terrain_at(t)
        px,py=int(round(pos[0])),int(round(pos[1]))
        path,cost=world.route((px,py),BASE,terrain)
        if not path or cost==float('inf'):return None
        initial_dist=((pos[0]-px)**2+(pos[1]-py)**2)**.5
        weighted=cost+initial_dist
        energy=weighted*(1.18 if carrying else .82)
        if energy_left[r]-energy < world.ground_battery*ENERGY_RESERVE:return None
        speed=world.ground_speed(r)*(.79 if carrying else 1.)
        seconds=weighted/speed
        current=t
        full=[list(pos)]+[list(pt) for pt in path if pt!=(px,py)]
        if len(full)<2:full=[list(pos),list(BASE)]
        parts=[]
        distances=[max(.00001,((b[0]-a[0])**2+(b[1]-a[1])**2)**.5)
                   for a,b in zip(full,full[1:])]
        for (a,b),dist in zip(zip(full,full[1:]),distances):
            dt=seconds*dist/sum(distances)
            parts.append({'r':r,'t0':round(current,4),'t1':round(current+dt,4),
                          'a':a,'b':b,'e':round(energy*dist/sum(distances),5),
                          'action':'evacuation_reroute' if carrying else 'safe_return'})
            current+=dt
        if carrying:
            parts.append({'r':r,'t0':round(current,4),'t1':round(current+DROPOFF_S,4),
                          'a':list(BASE),'b':list(BASE),'e':0.,'action':'dropoff'})
            current+=DROPOFF_S
        if current>world.horizon:return None
        energy_left[r]-=energy
        rescue_segments.extend(parts)
        return round(current,4)

    def candidate_detour(r,person,t,pos,carrying):
        """Feasible on-the-fly path to the SAME victim or to base if carrying.
        Does not cancel or reassign a victim. LLM chooses candidate ID only.
        """
        terrain=world.terrain_at(t)
        rounded=(int(round(pos[0])),int(round(pos[1])))
        target=BASE if carrying else (person.x,person.y)
        path,cost=world.route(rounded,target,terrain)
        if not path or not math.isfinite(cost):return None
        first=[list(pos)]+[list(q) for q in path if q!=rounded]
        if len(first)<2:first=[list(pos),list(target)]
        first_cost=cost+math.hypot(pos[0]-rounded[0],pos[1]-rounded[1])
        back=[];back_cost=0.
        if not carrying:
            back,back_cost=world.route((person.x,person.y),BASE,terrain)
            if not back:return None
        speed=world.ground_speed(r)
        duration=first_cost/(speed*(.79 if carrying else 1.))
        if not carrying:duration+=PICKUP_S+back_cost/(speed*.79)+DROPOFF_S
        else:duration+=DROPOFF_S
        energy=first_cost*(1.18 if carrying else .82)+(back_cost*1.18 if not carrying else 0)
        if energy_left[r]-energy < world.ground_battery*ENERGY_RESERVE:return None
        if t+duration>world.horizon:return None
        return {'id':'detour_to_base' if carrying else 'detour_to_target',
                'type':'DETOUR','duration':duration,'energy':energy,
                'destination':list(target),'path':first,'back':back,
                'first_cost':first_cost,'back_cost':back_cost}

    def execute_detour(r,person,t,cand,carrying,prior_start):
        nonlocal rescue_segments
        pieces=[];clock=t
        def add_path(path,seconds,energy,action):
            nonlocal clock
            lengths=[max(.000001,math.hypot(b[0]-a[0],b[1]-a[1])) for a,b in zip(path,path[1:])]
            total=max(1e-9,sum(lengths))
            for (a,b),dist in zip(zip(path,path[1:]),lengths):
                dt=seconds*dist/total
                pieces.append({'r':r,'t0':round(clock,4),'t1':round(clock+dt,4),
                               'a':list(a),'b':list(b),'e':round(energy*dist/total,5),
                               'action':action})
                clock+=dt
        speed=world.ground_speed(r)
        add_path(cand['path'],cand['first_cost']/(speed*(.79 if carrying else 1.)),
                 cand['first_cost']*(1.18 if carrying else .82),'local_detour')
        if not carrying:
            pieces.append({'r':r,'t0':round(clock,4),'t1':round(clock+5,4),
                           'a':[person.x,person.y],'b':[person.x,person.y],'e':0,'action':'pickup'})
            clock+=5
            add_path(cand['back'],cand['back_cost']/(speed*.79),cand['back_cost']*1.18,'to_base')
        pieces.append({'r':r,'t0':round(clock,4),'t1':round(clock+DROPOFF_S,4),
                       'a':list(BASE),'b':list(BASE),'e':0,'action':'dropoff'})
        clock+=DROPOFF_S
        energy_left[r]-=cand['energy']
        rescue_segments.extend(pieces)
        event={'t':round(clock,4),'start':prior_start,'id':person.id,'x':person.x,'y':person.y,
               'priority':person.priority,'r':r,'rerouted':True,'local_ai':True}
        return event

    for event in world.events:
        serial+=1;heapq.heappush(heap,(event['t'],serial,event['type'],dict(event)))
    search_events=[dict(item) for item in scout['discoveries']]
    event_counter=0
    while heap:
        event_counter+=1
        t,_,kind,data=heapq.heappop(heap)
        if os.getenv('DEBUG_MISSION') and event_counter%25==0:
            print('MISSION_DEBUG',ai.variant if ai else 'base','t',round(t,2),
                  'heap',len(heap),'pending',len(pending),'known',len(known),
                  'done',len(rescued),flush=True)
        if t>world.horizon:break
        packet=[(kind,data)]
        while heap and abs(heap[0][0]-t)<0.00001:
            _,_,k,d=heapq.heappop(heap);packet.append((k,d))
        reason=[]
        for kind,data in packet:
            if kind=='global_apply':
                if ai:
                    priority_applied=data.get('priority_ids',[])
                    ai.plan_version+=1;plan_revision=ai.plan_version
                    ai.record(t,'plan_manager','GLOBAL_POLICY_COMMITTED',
                              plan_version=plan_revision,priority_ids=priority_applied,
                              operation=data.get('operation','keep'))
                reason.append('global_policy_updated')
            elif kind=='terrain_change':
                terrain_logs.append(dict(data))
                terrain=world.terrain_at(t)
                if data['type'] not in ('smoke','smoke_clear'):
                    for r,current in list(inprogress.items()):
                        pid,finish_event=current
                        if finish_event.get('cancelled'):continue
                        future=[seg for seg in rescue_segments if seg['r']==r and seg['t1']>t+1e-8]
                        # A route is invalidated if any of its future tiles are
                        # blocked or made more expensive by the disturbance.
                        impacted=set(tuple(c) for c in data['cells'])
                        touched=any((int(round(seg['b'][0])),int(round(seg['b'][1]))) in impacted
                                    or (int(round(seg['a'][0])),int(round(seg['a'][1]))) in impacted
                                    for seg in future if seg['action'] in ('to_person','to_base'))
                        if not touched:continue
                        pos=pose_at(r,t)
                        carrying=any(seg['r']==r and seg['action']=='pickup' and seg['t1']<=t+1e-8
                                     for seg in rescue_segments)
                        crop_robot(r,t)
                        finish_event['cancelled']=True
                        inprogress.pop(r,None)
                        terrain_replans+=1
                        candidate=candidate_detour(r,person_by_id[pid],t,pos,carrying) if ai and ai.has_local else None
                        selected=None;latency=0.
                        if ai and ai.has_local:
                            ai.public_terrain_changes.append({'t':t,'type':data['type'],
                                'cell':list(next(iter(impacted))) if impacted else None})
                            selected,latency=ai.local_event(t,r,pid,data['type'],pos,carrying,
                                [candidate] if candidate else [],energy_left[r])
                        local_done=None
                        if selected and selected.get('type')=='DETOUR' and candidate:
                            # A stopped agent waits for its LLM reply. The physical route
                            # starts at arrival time, never retroactively at t.
                            if t+latency+candidate['duration']<=world.horizon:
                                local_done=execute_detour(r,person_by_id[pid],t+latency,
                                                          candidate,carrying,finish_event['start'])
                        elif selected and selected.get('type')=='HOLD':
                            ai.record(t,'local_ai','HOLD_FALLBACK',agent=r,reason='hold_until_replan')
                        new_finish=local_done['t'] if local_done else safe_return(r,person_by_id[pid],t,pos,carrying)
                        incidents.append({'t':round(t,3),'robot':r,'person':pid,
                                          'kind':data['type'],'carrying':carrying,
                                          'outcome':'local_detour' if local_done else 'rerouted' if new_finish is not None else 'stranded'})
                        if new_finish is None:
                            disabled.add(r);stranded+=1;busy_until[r]=world.horizon+1
                            stranding.append({'t':round(t,3),'robot':r,'person':pid})
                            # People only get re-queued if they were not picked up.
                            if not carrying and pid not in rescued:pending[pid]=person_by_id[pid]
                        elif carrying or local_done:
                            event=local_done or {'t':new_finish,'start':finish_event['start'],
                                   'id':pid,'x':finish_event['x'],'y':finish_event['y'],
                                   'priority':finish_event['priority'],'r':r,'rerouted':True}
                            inprogress[r]=(pid,event)
                            serial+=1;heapq.heappush(heap,(new_finish,serial,'rescued',event))
                            busy_until[r]=new_finish
                        else:
                            if pid not in rescued:pending[pid]=person_by_id[pid]
                            busy_until[r]=new_finish
                            serial+=1;heapq.heappush(heap,(new_finish,serial,'robot_ready',{'r':r}))
                        aborted_trips+=1
                reason.append('environment_change')
                if ai:ai.record(t,'environment','TERRAIN_CHANGED',kind=data['type'],cell_count=len(data.get('cells',[])))
            elif kind=='robot_ready':
                reason.append('robot_ready')
            elif kind=='planning_tick':
                next_planning_tick=None
                reason.append('planning_tick')
            elif kind=='detected':
                known.add(data['id']);pending[data['id']]=person_by_id[data['id']]
                reason.append('target_detected')
                if ai:
                    ai.detections[data['id']]=data
                    ai.record(t,'sensor','TARGET_DETECTED',person=data['id'],drone=data.get('r'))
            elif kind=='rescued':
                if data.get('cancelled'):continue
                rescued.add(data['id'])
                rescue_events.append(data)
                inprogress.pop(data['r'],None)
                reason.append('rescue_completed')
                if ai:ai.record(t,'executor','TARGET_RESCUED',person=data['id'],robot=data['r'])
            elif kind=='agent_failure':
                r=data['robot'];disabled.add(r)
                current=inprogress.pop(r,None)
                # A failed robot cannot finish an ongoing delivery.
                if current:
                    pid,finish_event=current
                    finish_event['cancelled']=True
                    if pid not in rescued:pending[pid]=person_by_id[pid]
                cropped=[];last_pos=[1.0,1.0]
                for seg in rescue_segments:
                    if seg['r']!=r:
                        cropped.append(seg);continue
                    if seg['t1']<=t:
                        cropped.append(seg);last_pos=seg['b'];continue
                    if seg['t0']<t<seg['t1']:
                        k=(t-seg['t0'])/(seg['t1']-seg['t0'])
                        seg=dict(seg);seg['b']=[seg['a'][a]+k*(seg['b'][a]-seg['a'][a]) for a in range(2)]
                        seg['t1']=round(t,4);seg['e']=round(seg['e']*k,5)
                        cropped.append(seg);last_pos=seg['b']
                rescue_segments=cropped
                busy_until[r]=world.horizon+1
                failure_events.append({'t':t,'robot':r,'x':last_pos[0],'y':last_pos[1],
                                       'type':'agent_failure'})
                reason.append('agent_failure')
                if ai:ai.record(t,'environment','AGENT_FAILURE',robot=r)
        if ai and ai.has_global and any(x in reason for x in ('target_detected','agent_failure','environment_change')):
            # Global only knows the actually confirmed detected targets.
            confirmed=[person_by_id[pid] for pid in sorted(known) if pid not in rescued]
            proposal,delay=ai.global_event(t,'+'.join(reason),confirmed,
                                [r for r in range(world.n_rescuers) if r not in disabled and busy_until[r]>t])
            if proposal and proposal.get('rescue_replan'):
                when=round(min(world.horizon,t+delay),4)
                serial+=1;heapq.heappush(heap,(when,serial,'global_apply',proposal))
                ai.record(t,'global_ai','REPLAN_REQUESTED',effective_time=when,scope='rescue')
        idle=[r for r in range(world.n_rescuers) if r not in disabled and busy_until[r]<=t+1e-7]
        if not pending or not idle:
            if reason and any(x in reason for x in ('agent_failure','environment_change','robot_ready')):
                decisions.append({'t':round(t,3),'cause':'+'.join(sorted(set(reason))),
                                  'known':len(known),'pending':len(pending),'assignments':[],
                                  'algorithm':rescue_method,'compute_ms':0})
            continue
        if reason==['target_detected'] and min_replan_interval and t-last_planning_t<min_replan_interval:
            # Batch near-simultaneous discoveries on large maps. Keep an
            # explicit future optimizer tick so no confirmed target is lost.
            target_t=round(last_planning_t+min_replan_interval,4)
            if next_planning_tick is None or target_t<next_planning_tick-1e-7:
                next_planning_tick=target_t
                serial+=1;heapq.heappush(heap,(target_t,serial,'planning_tick',{}))
            continue
        last_planning_t=t
        people=sorted(pending.values(),key=lambda p:p.id)
        # Bound the online NSGA-II chromosome for large swarms. All alternatives
        # use the SAME deterministic candidate selection policy; nothing is hidden.
        limit=max(35,min(80 if world.initial_people>150 else 110,world.n_rescuers*3))
        if len(people)>limit:
            people=sorted(people,key=lambda p:(-p.priority,
                math.hypot(p.x-BASE[0],p.y-BASE[1]),p.id))[:limit]
        if priority_applied:
            people=[replace(p,priority=min(3,p.priority+1)) if p.id in priority_applied else p for p in people]
        people,trips=prepare(world,people,terrain=world.terrain_at(t))
        # Busy robots are masked; they are not reallocated mid-trip.
        avail=[t if r in idle else world.horizon+1 for r in range(world.n_rescuers)]
        genome,stats=get_plan(world,people,trips,rescue_method,world.seed+int(t*100),
                              now=t,available=avail,energy=energy_left,small=True)
        opt_ms+=stats.get('wall_ms',0)
        # Strictly compare an AI-modified optimization with the UNMODIFIED
        # NSGA-II on the same snapshot under original medical priorities.
        if priority_applied and rescue_method=='nsga2':
            original_people=[person_by_id[p.id] for p in people]
            raw_genome,raw_stats=get_plan(world,original_people,trips,rescue_method,
                world.seed+int(t*100),now=t,available=avail,energy=energy_left,small=True)
            opt_ms+=raw_stats.get('wall_ms',0)
            obj_ai,_=eval_plan(genome,original_people,trips,now=t,available=avail,
                              energy=energy_left,horizon=world.horizon,battery_cap=world.ground_battery)
            obj_base,_=eval_plan(raw_genome,original_people,trips,now=t,available=avail,
                              energy=energy_left,horizon=world.horizon,battery_cap=world.ground_battery)
            if (obj_ai[0],obj_ai[1]+.12*obj_ai[2])>(obj_base[0],obj_base[1]+.12*obj_base[2]):
                genome=raw_genome;stats=raw_stats
                if ai:ai.record(t,'validator','AI_PLAN_REJECTED',
                                 reason='predicted_quality_worse_than_base_nsga2',
                                 ai_objectives=obj_ai,baseline_objectives=obj_base)
            elif ai:ai.record(t,'validator','AI_PLAN_ACCEPTED',
                             ai_objectives=obj_ai,baseline_objectives=obj_base)
        _,tasks=eval_plan(genome,people,trips,now=t,available=avail,energy=energy_left,horizon=world.horizon,battery_cap=world.ground_battery)
        assigned=[]
        for r in idle:
            if not tasks[r]:continue
            idx,start,finish,trip=tasks[r][0]
            if start>t+1e-5:continue
            p=person_by_id[people[idx].id]
            if p.id not in pending:continue
            pieces,end=mission_segments(p,r,trip,start)
            rescue_segments.extend(pieces)
            busy_until[r]=end
            energy_left[r]-=trip['energy']
            pending.pop(p.id)
            assigned.append({'robot':r,'person':p.id,'eta':end})
            serial+=1
            event={'t':end,'start':start,'id':p.id,'x':p.x,'y':p.y,'priority':p.priority,'r':r}
            inprogress[r]=(p.id,event)
            heapq.heappush(heap,(end,serial,'rescued',event))
        decisions.append({'t':round(t,3),'cause':'+'.join(sorted(set(reason))),
                          'known':len(known),'pending':len(pending),
                          'assignments':assigned,'algorithm':rescue_method,
                          'plan_version':plan_revision,'compute_ms':stats.get('wall_ms',0)})
        if ai:ai.record(t,'rescue_nsga2','PLAN_EVALUATED',plan_version=plan_revision,
                        assignments=assigned,known=len(known),compute_ms=stats.get('wall_ms',0),
                        objective=stats.get('selected_objectives'),pareto=stats.get('pareto',[])[:8])
    rescue_segments.sort(key=lambda s:(s['r'],s['t0']))
    rescue_events.sort(key=lambda p:p['t'])
    return {'method':config,'label':label,'scout_method':scout_method,
            'rescue_method':rescue_method,
            'scout_segments':scout['segments'], 'rescue_segments':rescue_segments,
            'visits':scout['visits'],'discoveries':search_events,
            'signals':scout.get('signals',[]),'terrain_events':terrain_logs,
            'incidents':incidents,'stranding':stranding,
            'ai_stats':ai.summary() if ai else {'mode':'off','connected':False,'calls':0},
            'audit':sorted(ai.audit,key=lambda e:e['t']) if ai else [],
            'messages':ai.messages if ai else [],
            'rescues':rescue_events,'decisions':decisions,'failures':failure_events,
            'opt':{'wall_ms':round(scout['opt'].get('wall_ms',0)+opt_ms,1),
                   'scout_ms':scout['opt'].get('wall_ms',0),'rescue_ms':round(opt_ms,1),
                   'replans':len(decisions),'failures':len(failure_events),
                   'terrain_replans':terrain_replans,'aborted_trips':aborted_trips,
                   'stranded':stranded,'pareto':scout['opt'].get('pareto',[])},
            'final':{'found':len(known),'rescued':len(rescued),
                     'coverage':len({v['sector'] for v in scout['visits'] if v['t']<=world.horizon}),
                     'total':world.n_people,'new_people':len(world.appearances),
                     'energy':round(sum(s['e'] for s in scout['segments'] if s['t0']<world.horizon)
                            +sum(s['e'] for s in rescue_segments if s['t0']<world.horizon),2),
                     'last_rescue':round(max((r['t'] for r in rescue_events),default=0),2),
                     'finished_at':round(min(world.horizon,max((s['t1'] for s in scout['segments']+rescue_segments),default=0)),2)}}
