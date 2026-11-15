"""Independent fair aerial-search benchmark: no planner sees World.people."""
from __future__ import annotations
import math, random, time, heapq
from world import (World, BASE, SCOUT_SCAN_S, ENERGY_RESERVE)
from nsga2 import run_nsga2,order_crossover

LABELS={'random':'Случайный поиск','sweep':'Полосовое покрытие',
        'greedy':'Жадный поиск','frontier':'Frontier / граница', 'nsga2':'Scout NSGA-II'}
COLORS=['#35b8ff','#ac81ff','#ffc46b']

def euclid(a,b):return math.hypot(a[0]-b[0],a[1]-b[1])

def routes_from_genome(genome, world):
    order,assignment=genome
    routes=[[] for _ in range(world.n_scouts)]
    for i,sec in enumerate(order):routes[assignment[sec]].append(sec)
    return routes

def metrics_for_routes(world,routes):
    elapsed=[0.0]*world.n_scouts; energy=[0.0]*world.n_scouts
    locations=[BASE]*world.n_scouts;times={}
    for r,rt in enumerate(routes):
        for sec in rt:
            end=world.center(sec);length=euclid(locations[r],end)
            elapsed[r]+=length/world.scout_speed(r)+SCOUT_SCAN_S
            energy[r]+=length*.69+.55
            times[sec]=elapsed[r]
            locations[r]=end
    # Information gained early and complete meaningful area coverage.
    util=sum(world.prior[s]*max(0,1-times.get(s,world.horizon*2)/world.horizon)
             for s in range(world.sector_count**2))
    late=sum(max(0,elapsed[r]-world.horizon) for r in range(world.n_scouts))
    # Unlimited battery in v0.5. Energy is measured, never a feasibility constraint.
    punishment=late*2
    return (-util+punishment, max(elapsed)+punishment, sum(energy)+punishment)

def heuristic_routes(world,method,seed):
    rng=random.Random(seed)
    n=world.sector_count*world.sector_count
    ids=list(range(n))
    routes=[[] for _ in range(world.n_scouts)]
    if method=='random':
        rng.shuffle(ids)
        for i,s in enumerate(ids):routes[i%world.n_scouts].append(s)
        return routes
    if method=='sweep':
        ids=[]
        for y in range(world.sector_count):
            row=list(range(y*world.sector_count,(y+1)*world.sector_count))
            ids.extend(row if y%2==0 else row[::-1])
        # Continuous slices, avoiding every drone crossing the entire map.
        for i,s in enumerate(ids):routes[min(world.n_scouts-1,i*world.n_scouts//n)].append(s)
        return routes
    remaining=set(ids)
    pos=[BASE]*world.n_scouts; clock=[0.0]*world.n_scouts
    scanned=set()
    while remaining:
        r=min(range(world.n_scouts),key=lambda k:clock[k])
        def score(s):
            dist=euclid(pos[r],world.center(s))
            benefit=world.prior[s]
            if method=='frontier':
                sx,sy=s%world.sector_count,s//world.sector_count
                neighbours=[ny*world.sector_count+nx for nx,ny in
                            ((sx+1,sy),(sx-1,sy),(sx,sy+1),(sx,sy-1))
                            if 0<=nx<world.sector_count and 0<=ny<world.sector_count]
                bonus=1.3 if any(u in scanned for u in neighbours) else .7
                return benefit*bonus/(.8+dist)
            return benefit/(1+dist/world.scout_speed(r))
        sec=max(sorted(remaining),key=score)
        dist=euclid(pos[r],world.center(sec))
        clock[r]+=dist/world.scout_speed(r)+SCOUT_SCAN_S
        pos[r]=world.center(sec)
        routes[r].append(sec);remaining.remove(sec);scanned.add(sec)
    return routes

def optimize_routes(world,seed,population=40,generations=32):
    n=world.sector_count*world.sector_count
    heuristic=[]
    for method in ('greedy','sweep','frontier'):
        rs=heuristic_routes(world,method,seed)
        ordering=[s for r in rs for s in r]
        assignment=[0]*n
        for r,route in enumerate(rs):
            for s in route:assignment[s]=r
        heuristic.append((ordering,assignment))
    counter=[0]
    def init(rng):
        counter[0]+=1
        if counter[0]<=len(heuristic):
            a,b=heuristic[counter[0]-1];return (a[:],b[:])
        order=list(range(n));rng.shuffle(order)
        assignment=[rng.randrange(world.n_scouts) for _ in range(n)]
        return (order,assignment)
    def mate(a,b,rng):
        x,y=order_crossover(a[0],b[0],rng)
        u=[a[1][s] if rng.random()<.5 else b[1][s] for s in range(n)]
        v=[b[1][s] if rng.random()<.5 else a[1][s] for s in range(n)]
        return (x,u),(y,v)
    def mutate(a,rng):
        order=a[0][:];assignment=a[1][:]
        if rng.random()<.8:
            i,j=rng.sample(range(n),2);order[i],order[j]=order[j],order[i]
        if rng.random()<.42:
            k=rng.randrange(n);assignment[k]=rng.randrange(world.n_scouts)
        if rng.random()<.18:
            i,j=sorted(rng.sample(range(n),2));order[i:j+1]=reversed(order[i:j+1])
        return (order,assignment)
    front,stats=run_nsga2(init,lambda g:metrics_for_routes(world,routes_from_genome(g,world)),
                           mate,mutate,pop_size=population,generations=generations,seed=seed+781)
    # Safety-feasible solutions first, then quality of expected early information.
    def choice_key(ind):
        f=ind.f
        return (f[0] + 0.005*f[1]+0.002*f[2],f[1])
    best=min(front,key=choice_key)
    rs=routes_from_genome(best.genome,world)
    stats.update({'selected_objectives':[round(x,3) for x in best.f],
                  'pareto':[[round(v,2) for v in ind.f] for ind in front[:75]]})
    return rs,stats

def schedule(world,routes,method,compute=None):
    segments=[];visits=[];discoveries=[]
    all_people_by_sector={s:[] for s in range(world.sector_count**2)}
    for p in world.people:all_people_by_sector[p.sector].append(p)
    for r,route in enumerate(routes):
        x,y=BASE; t=0.0
        consumed=0.0
        for sec in route:
            nx,ny=world.center(sec)
            d=euclid((x,y),(nx,ny))
            needed=d*.69+.55
            # Never abort a route for battery capacity in v0.5.
            consumed+=needed
            if d>1e-8:
                dt=d/world.scout_speed(r)
                segments.append({'r':r,'t0':round(t,4),'t1':round(t+dt,4),
                                 'a':[x,y],'b':[nx,ny],'e':round(d*.69,4),'action':'fly'})
                t+=dt
            segments.append({'r':r,'t0':round(t,4),'t1':round(t+SCOUT_SCAN_S,4),
                             'a':[nx,ny],'b':[nx,ny],'e':.55,'action':'scan'})
            t+=SCOUT_SCAN_S
            visits.append({'t':round(t,4),'sector':sec,'r':r})
            # Ideal deterministic detection at scan completion; all methods share sensor.
            for p in all_people_by_sector[sec]:
                if world.sensor_reliability<1:
                    # Outcome depends only on seed + target, never on the method/scan time.
                    detection_rng=random.Random(world.seed*100_003+p.id*97)
                    if detection_rng.random()>world.sensor_reliability:continue
                discoveries.append({'t':round(t,4),'id':p.id,'x':p.x,'y':p.y,
                                    'priority':p.priority,'r':r})
            x,y=nx,ny
    segments.sort(key=lambda s:(s['r'],s['t0']))
    visits.sort(key=lambda a:a['t']);discoveries.sort(key=lambda a:a['t'])
    energy=sum(v['e']*min(1.0,(world.horizon-v['t0'])/max(.00001,v['t1']-v['t0'])) for v in segments if v['t0']<world.horizon)
    within=[d for d in discoveries if d['t']<=world.horizon]
    first=within[0]['t'] if within else None
    coverage=sum(v['t']<=world.horizon for v in visits)
    finished=min(world.horizon,max((s['t1'] for s in segments),default=0))
    return {'method':method,'label':LABELS.get(method,method),
            'segments':segments,'visits':visits,'discoveries':discoveries,
            'routes':routes,'opt':compute or {},
            'final':{'found':len(within),'coverage':coverage,'first':first,
                     'energy':round(energy,2),'finished_at':round(finished,2)}}

def schedule_dynamic(world,routes,method,compute=None,ai=None):
    """Causal scout replay: the planner knows only scanned sectors and noisy signal sectors.
    Dynamic ground truth is queried by the sensor ONLY at scan completion.
    Each scout operates concurrently; rescans follow observed smoke or audible signals.
    """
    segments=[];visits=[];discoveries=[];signals=[]
    by_sector={s:[] for s in range(world.sector_count**2)}
    for p in world.people:by_sector[p.sector].append(p)
    queues=[list(v) for v in routes]
    locations=[BASE]*world.n_scouts
    energies=[0.0]*world.n_scouts
    ready=[(0.0,r) for r in range(world.n_scouts)]
    heapq.heapify(ready)
    observed=set();last_scanned={};found=set();hints=[];in_hints=set()
    pending_appearances=iter(world.appearances)
    next_appearance=next(pending_appearances,None)
    next_clear=iter(ev for ev in world.landscape_events if ev['type']=='smoke_clear')
    clear_event=next(next_clear,None)
    escalations=0;local_verifications=set()
    while ready:
        t,r=heapq.heappop(ready)
        if t>world.horizon:break
        # Only information already publicly emitted is available to replanning.
        while next_appearance and next_appearance['t']<=t+1e-8:
            sig=next_appearance.copy()
            signals.append(sig)
            sec=sig['sector']
            if ai:
                ai.record(t,'sensor','AUDIBLE_SIGNAL',sector=sec,cause=sig.get('cause'),confirmed_coordinates=False)
                if ai.has_global:
                    # Only previously detected targets; no future or hidden victims.
                    known=[p for p in world.people if p.id in found]
                    ai.global_event(t,'audible_signal',known,[],signal_sector=sec,phase='scout')
            if sig['id'] in found:
                next_appearance=next(pending_appearances,None)
                continue
            if sec in observed and sec not in in_hints:
                hints.append(sec);in_hints.add(sec)
            # Otherwise move an already-planned sector to the front of the next free drone.
            elif sec not in in_hints:
                hints.append(sec);in_hints.add(sec)
            next_appearance=next(pending_appearances,None)
        while clear_event and clear_event['t']<=t+1e-8:
            impacted={((y//world.sector_size)*world.sector_count+x//world.sector_size)
                      for x,y in clear_event['cells']}
            for sec in impacted:
                if sec in last_scanned and last_scanned[sec]=='smoke' and sec not in in_hints:
                    hints.append(sec);in_hints.add(sec)
            clear_event=next(next_clear,None)
        chosen=None
        if hints:
            # All scouts share the same public signal queue; first free drone handles it.
            chosen=hints.pop(0);in_hints.discard(chosen)
            for q in queues:
                if chosen in q:q.remove(chosen)
            escalations+=1
        else:
            while queues[r] and queues[r][0] in observed:queues[r].pop(0)
            if queues[r]:chosen=queues[r].pop(0)
        if chosen is None:
            future=[e['t'] for e in world.appearances if e['t']>t+1e-6]
            future.extend(e['t'] for e in world.landscape_events
                          if e['type']=='smoke_clear' and e['t']>t+1e-6)
            if future:
                heapq.heappush(ready,(min(future),r))
            continue
        nx,ny=world.center(chosen)
        distance=euclid(locations[r],(nx,ny))
        terrain=world.terrain_at(t)
        # Smoke along the air corridor reduces survey speed, while ground hazards
        # are not magically impassable to aerial agents.
        start_x,start_y=int(locations[r][0]),int(locations[r][1])
        end_x,end_y=int(nx),int(ny)
        smoky=terrain.smoke[start_y][start_x] or world.sector_visibility(chosen,t)<1
        flight_dt=distance/world.scout_speed(r)*(1.25 if smoky else 1)
        scan_dt=SCOUT_SCAN_S*(1.65 if smoky else 1)
        energy_flight=distance*.69*(1.20 if smoky else 1)
        energy_scan=.55*(1.45 if smoky else 1)
        if flight_dt>1e-8:
            segments.append({'r':r,'t0':round(t,4),'t1':round(t+flight_dt,4),
                             'a':list(locations[r]),'b':[nx,ny],'e':round(energy_flight,4),'action':'fly'})
        arrival=t+flight_dt;end=arrival+scan_dt
        segments.append({'r':r,'t0':round(arrival,4),'t1':round(end,4),
                         'a':[nx,ny],'b':[nx,ny],'e':round(energy_scan,4),'action':'scan'})
        energies[r]+=energy_flight+energy_scan
        if end<=world.horizon+1e-8:
            snap=world.terrain_at(end)
            quality=world.sector_visibility(chosen,end)*world.sensor_reliability
            visits.append({'t':round(end,4),'sector':chosen,'r':r,'visibility':round(quality,2)})
            if ai:
                ai.record(end,'sensor','SECTOR_SCANNED',drone=r,sector=chosen,visibility=round(quality,3))
                if ai.has_local and quality<.65 and chosen not in local_verifications:
                    local_verifications.add(chosen)
                    proposal=ai.local_scout_event(end,r,chosen,quality)
                    if proposal and chosen not in in_hints:
                        hints.append(chosen);in_hints.add(chosen)
            observed.add(chosen);last_scanned[chosen]='smoke' if quality<.65 else 'clear'
            for person in by_sector[chosen]:
                if person.id in found or not world.person_active(person,end):continue
                # Fixed per-person sensor threshold shared across ALL strategies.
                detection_rng=random.Random(world.seed*100_003+person.id*97)
                if detection_rng.random()>quality:continue
                found.add(person.id)
                discoveries.append({'t':round(end,4),'id':person.id,'x':person.x,'y':person.y,
                                    'priority':person.priority,'r':r,'new':person.id>world.initial_people})
                if ai:
                    ai.record(end,'sensor','PERSON_CONFIRMED',drone=r,person=person.id,sector=chosen)
                    ai.send(end,f'drone_{r+1:02d}','global','TARGET_DETECTED',
                            {'person_id':person.id,'position':[person.x,person.y],
                             'priority':person.priority})
        locations[r]=(nx,ny)
        heapq.heappush(ready,(end,r))
    segments.sort(key=lambda s:(s['r'],s['t0']))
    visits.sort(key=lambda a:a['t']);discoveries.sort(key=lambda a:a['t'])
    energy=sum(v['e']*min(1.0,(world.horizon-v['t0'])/max(.00001,v['t1']-v['t0']))
               for v in segments if v['t0']<world.horizon)
    within=[d for d in discoveries if d['t']<=world.horizon]
    return {'method':method,'label':LABELS.get(method,method),
            'segments':segments,'visits':visits,'discoveries':discoveries,
            'signals':signals,'routes':routes,'opt':compute or {},
            'final':{'found':len(within),'coverage':len({v['sector'] for v in visits}),
                     'first':within[0]['t'] if within else None,'energy':round(energy,2),
                     'search_replans':escalations,
                     'finished_at':round(min(world.horizon,max((s['t1'] for s in segments),default=0)),2)}}

def run_scout(world,method,seed=None,small=False,ai=None):
    seed=world.seed if seed is None else seed
    st=time.perf_counter()
    if method=='nsga2':
        routes,stats=optimize_routes(world,seed,population=30 if small else 40,
                                    generations=17 if small else 32)
    elif method in LABELS:
        routes=heuristic_routes(world,method,seed+405)
        stats={'evaluations':0,'population':0,'generations':0,'pareto_size':0}
    else:raise ValueError('Unknown scout method')
    stats['wall_ms']=round((time.perf_counter()-st)*1000,1)
    return schedule_dynamic(world,routes,method,stats,ai=ai) if world.dynamic_events else schedule(world,routes,method,stats)
