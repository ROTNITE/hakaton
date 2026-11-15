"""Online two-stage mission: scouting and rescue physically overlap in time.
On target-detected / rescue-completed events, rerun rescue planner using public
knowledge only. Do not cancel a rescue trip once it is under way.
"""
from __future__ import annotations
import heapq, time
from world import World
from scout import run_scout
from rescue import prepare, get_plan, eval_plan, mission_segments

CONFIGS={
  'greedy_greedy':('greedy','greedy','Greedy + Greedy'),
  'frontier_local':('frontier','local','Frontier + Local Search'),
  'nsga2_greedy':('nsga2','greedy','Scout NSGA-II + Greedy'),
  'greedy_nsga2':('greedy','nsga2','Greedy + Rescue NSGA-II'),
  'nsga2_nsga2':('nsga2','nsga2','NSGA-II + NSGA-II'),
}

def run_mission(world, config, scout_cache=None):
    if config not in CONFIGS: raise ValueError('Unknown mission config')
    scout_method,rescue_method,label=CONFIGS[config]
    scout=(scout_cache or {}).get(scout_method)
    if scout is None:scout=run_scout(world,scout_method,small=True)
    person_by_id={p.id:p for p in world.people}
    heap=[];serial=0
    for item in scout['discoveries']:
        if item['t']<=world.horizon:
            serial+=1;heapq.heappush(heap,(item['t'],serial,'detected',item))
    busy_until=[0.0]*world.n_rescuers
    energy_left=[world.ground_battery]*world.n_rescuers
    pending={}; known=set();rescued=set();disabled=set();inprogress={}
    rescue_segments=[];rescue_events=[];decisions=[];failure_events=[];opt_ms=0.0
    for event in world.events:
        serial+=1;heapq.heappush(heap,(event['t'],serial,event['type'],dict(event)))
    search_events=[dict(item) for item in scout['discoveries']]
    while heap:
        t,_,kind,data=heapq.heappop(heap)
        if t>world.horizon:break
        packet=[(kind,data)]
        while heap and abs(heap[0][0]-t)<0.00001:
            _,_,k,d=heapq.heappop(heap);packet.append((k,d))
        reason=[]
        for kind,data in packet:
            if kind=='detected':
                known.add(data['id']);pending[data['id']]=person_by_id[data['id']]
                reason.append('target_detected')
            elif kind=='rescued':
                if data.get('cancelled'):continue
                rescued.add(data['id'])
                rescue_events.append(data)
                inprogress.pop(data['r'],None)
                reason.append('rescue_completed')
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
        idle=[r for r in range(world.n_rescuers) if r not in disabled and busy_until[r]<=t+1e-7]
        if not pending or not idle:
            if 'agent_failure' in reason:
                decisions.append({'t':round(t,3),'cause':'+'.join(sorted(set(reason))),
                                  'known':len(known),'pending':len(pending),'assignments':[],
                                  'algorithm':rescue_method,'compute_ms':0})
            continue
        people=sorted(pending.values(),key=lambda p:p.id)
        people,trips=prepare(world,people)
        # Busy robots are masked; they are not reallocated mid-trip.
        avail=[t if r in idle else world.horizon+1 for r in range(world.n_rescuers)]
        genome,stats=get_plan(world,people,trips,rescue_method,world.seed+int(t*100),
                              now=t,available=avail,energy=energy_left,small=True)
        opt_ms+=stats.get('wall_ms',0)
        _,tasks=eval_plan(genome,people,trips,now=t,available=avail,energy=energy_left,horizon=world.horizon,battery_cap=world.ground_battery)
        assigned=[]
        for r in idle:
            if not tasks[r]:continue
            idx,start,finish,trip=tasks[r][0]
            if start>t+1e-5:continue
            p=people[idx]
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
                          'compute_ms':stats.get('wall_ms',0)})
    rescue_segments.sort(key=lambda s:(s['r'],s['t0']))
    rescue_events.sort(key=lambda p:p['t'])
    return {'method':config,'label':label,'scout_method':scout_method,
            'rescue_method':rescue_method,
            'scout_segments':scout['segments'], 'rescue_segments':rescue_segments,
            'visits':scout['visits'],'discoveries':search_events,
            'rescues':rescue_events,'decisions':decisions,'failures':failure_events,
            'opt':{'wall_ms':round(scout['opt'].get('wall_ms',0)+opt_ms,1),
                   'scout_ms':scout['opt'].get('wall_ms',0),'rescue_ms':round(opt_ms,1),
                   'replans':len(decisions),'failures':len(failure_events)},
            'final':{'found':len(known),'rescued':len(rescued),
                     'coverage':sum(v['t']<=world.horizon for v in scout['visits']),
                     'total':world.n_people,
                     'energy':round(sum(s['e'] for s in scout['segments'] if s['t0']<world.horizon)
                            +sum(s['e'] for s in rescue_segments if s['t0']<world.horizon),2),
                     'last_rescue':round(max((r['t'] for r in rescue_events),default=0),2),
                     'finished_at':round(min(world.horizon,max((s['t1'] for s in scout['segments']+rescue_segments),default=0)),2)}}
