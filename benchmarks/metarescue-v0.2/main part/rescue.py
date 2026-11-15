"""Known-target offline evacuation and event-driven online scheduling."""
from __future__ import annotations
import math, random, time
from world import (World, BASE, GROUND_SPEED, GROUND_BATTERY, ENERGY_RESERVE,
                   PICKUP_S, DROPOFF_S, HORIZON)
from nsga2 import run_nsga2, order_crossover

LABELS={'nearest':'Ближайший робот','greedy':'Greedy / срочность',
        'local':'Local Search 2-opt','nsga2':'Rescue NSGA-II','ortools':'OR-Tools CP-SAT'}
COLORS=['#54ecc9','#ffb95d','#fa85b6','#9c9bff']

def trip(world,p,robot):
    out,weighted=world.route(BASE,(p.x,p.y))
    if not out or not math.isfinite(weighted):return None
    rev=list(reversed(out))
    # Physics-simplified but consistent per all benchmark variants.
    speed=world.ground_speed(robot)
    time_out=weighted/speed
    time_back=weighted/(speed*.79)
    energy_out=weighted*.82
    energy_back=weighted*1.18
    duration=time_out+PICKUP_S+time_back+DROPOFF_S
    return {'out':out,'back':rev,'weighted':weighted,
            'out_s':time_out,'back_s':time_back,
            'energy':energy_out+energy_back,'duration':duration}

def prepare(world,people=None):
    people=list(world.people if people is None else people)
    return people, [[trip(world,p,r) for p in people] for r in range(world.n_rescuers)]

def eval_plan(genome,people,trips,now=0.0,available=None,energy=None,horizon=HORIZON,battery_cap=GROUND_BATTERY):
    order,assign=genome
    starts=list(available or [now]*len(trips))
    remaining=list(energy if energy is not None else [battery_cap]*len(trips))
    saved=set(); completion={};consumed=0.0
    tasks=[[] for _ in range(len(trips))]
    for j in order:
        r=assign[j]
        tr=trips[r][j]
        if tr is None or remaining[r]-tr['energy']<battery_cap*ENERGY_RESERVE:
            continue
        finish=starts[r]+tr['duration']
        if finish>horizon:continue
        tasks[r].append((j,starts[r],finish,tr))
        starts[r]=finish
        remaining[r]-=tr['energy'];consumed+=tr['energy']
        saved.add(j);completion[j]=finish
    unrescued=sum(p.priority for j,p in enumerate(people) if j not in saved)
    total_times=sum(p.priority*completion.get(j,horizon) for j,p in enumerate(people))
    return (float(unrescued),float(total_times),float(consumed)),tasks

def heuristic_plan(people,trips,method,now=0.0,available=None,energy=None,battery_cap=GROUND_BATTERY,horizon=HORIZON):
    n=len(people)
    clock=list(available or [now]*len(trips))
    rem=list(energy if energy is not None else [battery_cap]*len(trips))
    order=[];assign=[0]*n
    remaining=set(range(n))
    while remaining:
        choices=[]
        for j in remaining:
            for r in range(len(trips)):
                tr=trips[r][j]
                if tr is None:continue
                finish=clock[r]+tr['duration']
                if finish>horizon or rem[r]-tr['energy']<battery_cap*ENERGY_RESERVE:continue
                # nearest: shortest immediate mission; greedy: urgent+early completion.
                score=(tr['duration'] if method=='nearest' else finish/max(1,people[j].priority*1.75))
                choices.append((score,finish,j,r))
        if not choices:break
        _,finish,j,r=min(choices)
        order.append(j);assign[j]=r
        clock[r]=finish;rem[r]-=trips[r][j]['energy']
        remaining.remove(j)
    order.extend(sorted(remaining))
    return (order,assign)

def optimize_rescue(world,people,trips,seed,now=0.0,available=None,energy=None,
                    population=42,generations=38):
    n=len(people)
    if n==0:return ([],[]),{'wall_ms':0.0,'pareto':[],'evaluations':0}
    heuristic=[]
    for kind in ('greedy','nearest'):
        heuristic.append(heuristic_plan(people,trips,kind,now,available,energy,world.ground_battery,world.horizon))
    calls=[0]
    def init(rng):
        calls[0]+=1
        if calls[0]<=len(heuristic):
            order,assignment=heuristic[calls[0]-1]
            return (order[:],assignment[:])
        order=list(range(n));rng.shuffle(order)
        return (order,[rng.randrange(len(trips)) for _ in range(n)])
    def mate(a,b,rng):
        o1,o2=order_crossover(a[0],b[0],rng)
        x=[a[1][j] if rng.random()<.5 else b[1][j] for j in range(n)]
        y=[b[1][j] if rng.random()<.5 else a[1][j] for j in range(n)]
        return (o1,x),(o2,y)
    def mutate(a,rng):
        order=a[0][:]; assignment=a[1][:]
        if n>1 and rng.random()<.85:
            j,k=rng.sample(range(n),2);order[j],order[k]=order[k],order[j]
        if rng.random()<.5:
            assignment[rng.randrange(n)]=rng.randrange(len(trips))
        if n>2 and rng.random()<.16:
            i,j=sorted(rng.sample(range(n),2));order[i:j+1]=reversed(order[i:j+1])
        return order,assignment
    front,stats=run_nsga2(init,lambda g:eval_plan(g,people,trips,now,available,energy,horizon=world.horizon,battery_cap=world.ground_battery)[0],
                          mate,mutate,pop_size=population,generations=generations,seed=seed+915)
    # Lexicographic operational policy: maximise saved priority, then weighted time, then energy.
    best=min(front,key=lambda v:(v.f[0],v.f[1]+.12*v.f[2]))
    stats['pareto']=[[round(v,2) for v in ind.f] for ind in front[:90]]
    stats['selected_objectives']=[round(v,2) for v in best.f]
    return best.genome,stats

def local_plan(people,trips,now=0.0,available=None,energy=None,battery_cap=GROUND_BATTERY,horizon=HORIZON):
    """Deterministic local search: swap visit order + change robot assignment."""
    order,assignment=heuristic_plan(people,trips,'greedy',now,available,energy,battery_cap,horizon)
    best=(order[:],assignment[:])
    def score(g):
        f,_=eval_plan(g,people,trips,now,available,energy,horizon=horizon,battery_cap=battery_cap)
        return f[0]*1_000_000+f[1]*2+f[2]
    current=score(best)
    for _ in range(3):
        improved=False
        for i in range(len(order)):
            for j in range(i+1,len(order)):
                cand=(order[:],assignment[:]);cand[0][i],cand[0][j]=cand[0][j],cand[0][i]
                v=score(cand)
                if v+1e-8<current:
                    order,assignment=cand;current=v;improved=True
        for k in range(len(order)):
            for r in range(len(trips)):
                if r==assignment[k]:continue
                cand=(order[:],assignment[:]);cand[1][k]=r
                v=score(cand)
                if v+1e-8<current:
                    order,assignment=cand;current=v;improved=True
        if not improved:break
    return order,assignment

def ortools_plan(people,trips,now=0.0,available=None,energy=None,limit_s=2.0,battery_cap=GROUND_BATTERY,horizon=HORIZON):
    """Actual OR-Tools CP-SAT optional baseline; no disguised heuristic fallback."""
    from ortools.sat.python import cp_model
    n=len(people)
    model=cp_model.CpModel()
    start={};end={}; use={};intervals=[[] for _ in range(len(trips))]
    feasible=[]
    avail=available or [now]*len(trips)
    bat=energy if energy is not None else [battery_cap]*len(trips)
    t_max=int(horizon*10)
    for i,p in enumerate(people):
        for r in range(len(trips)):
            tr=trips[r][i]
            if tr is None or bat[r]-tr['energy']<battery_cap*ENERGY_RESERVE:continue
            d=math.ceil(tr['duration']*10)
            a=math.ceil(avail[r]*10)
            if a+d>t_max:continue
            b=model.NewBoolVar(f'use_{i}_{r}')
            s=model.NewIntVar(a,t_max-d,f'start_{i}_{r}')
            e=model.NewIntVar(a+d,t_max,f'end_{i}_{r}')
            it=model.NewOptionalIntervalVar(s,d,e,b,f'trip_{i}_{r}')
            start[i,r]=s;end[i,r]=e;use[i,r]=b
            intervals[r].append(it);feasible.append((i,r))
    for i in range(n):model.Add(sum(use[i,r] for r in range(len(trips)) if (i,r) in use)<=1)
    for r in range(len(trips)):
        if intervals[r]:model.AddNoOverlap(intervals[r])
        # Wh*10 integer budget
        model.Add(sum(math.ceil(trips[r][i]['energy']*10)*use[i,r] for i in range(n)
                      if (i,r) in use)<=int((bat[r]-battery_cap*ENERGY_RESERVE)*10))
    # Save lives dominates schedule and energy; late completions are penalised.
    obj=[]
    for i,r in feasible:
        obj.append(people[i].priority*1_000_000*use[i,r])
        # Penalise end times of performed tasks using a reified product.
        actual_end=model.NewIntVar(0,t_max,f'actual_end_{i}_{r}')
        model.Add(actual_end==end[i,r]).OnlyEnforceIf(use[i,r])
        model.Add(actual_end==0).OnlyEnforceIf(use[i,r].Not())
        obj.append(-actual_end*10*people[i].priority)
        obj.append(-math.ceil(trips[r][i]['energy']*10)*use[i,r])
    model.Maximize(sum(obj))
    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=limit_s
    solver.parameters.num_search_workers=1 # deterministic settings
    solver.parameters.random_seed=11
    result=solver.Solve(model)
    if result not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
        return heuristic_plan(people,trips,'greedy',now,available,energy,battery_cap,horizon),{'status':'no_feasible_solver_solution'}
    rows=[];assigned=[0]*n
    for (i,r),b in use.items():
        if solver.Value(b):rows.append((solver.Value(start[i,r]),i,r));assigned[i]=r
    rows.sort()
    scheduled={i for _,i,_ in rows}
    order=[i for _,i,_ in rows]+[i for i in range(n) if i not in scheduled]
    # Must preserve per-robot order; global chronological start order does.
    return (order,assigned), {'status':'optimal' if result==cp_model.OPTIMAL else 'feasible',
                                'objective':solver.ObjectiveValue()}

def get_plan(world,people,trips,method,seed,now=0.0,available=None,energy=None,small=False):
    st=time.perf_counter()
    extra={}
    if method=='nsga2':
        genome,extra=optimize_rescue(world,people,trips,seed,now,available,energy,
                                    population=26 if small else 42,
                                    generations=17 if small else 38)
    elif method in ('greedy','nearest'):
        genome=heuristic_plan(people,trips,method,now,available,energy,world.ground_battery,world.horizon)
    elif method=='local':
        genome=local_plan(people,trips,now,available,energy,world.ground_battery,world.horizon)
    elif method=='ortools':
        genome,extra=ortools_plan(people,trips,now,available,energy,battery_cap=world.ground_battery,horizon=world.horizon)
    else:raise ValueError('Unknown rescue method')
    extra['wall_ms']=round((time.perf_counter()-st)*1000,1)
    return genome,extra

def mission_segments(p,robot,trip,start):
    """Time-resolved path, with leg duration proportional to terrain-weighted edges."""
    seq=[];t=start
    def move(path,seconds,energy,action):
        nonlocal t
        if len(path)<2:return
        weights=[]
        for a,b in zip(path,path[1:]):
            weights.append((1+0.5*(a!=b))) # equally spaced city-block steps
        total=sum(weights)
        for a,b,w in zip(path,path[1:],weights):
            dt=seconds*w/total
            seq.append({'r':robot,'t0':round(t,4),'t1':round(t+dt,4),
                        'a':list(a),'b':list(b),'e':round(energy*w/total,5),'action':action})
            t+=dt
    move(trip['out'],trip['out_s'],trip['weighted']*.82,'to_person')
    seq.append({'r':robot,'t0':round(t,4),'t1':round(t+PICKUP_S,4),
                'a':[p.x,p.y],'b':[p.x,p.y],'e':0.0,'action':'pickup'})
    t+=PICKUP_S
    move(trip['back'],trip['back_s'],trip['weighted']*1.18,'to_base')
    seq.append({'r':robot,'t0':round(t,4),'t1':round(t+DROPOFF_S,4),
                'a':list(BASE),'b':list(BASE),'e':0.0,'action':'dropoff'})
    t+=DROPOFF_S
    return seq,round(t,4)

def run_rescue(world,method,people=None,seed=None,small=False):
    people,trips=prepare(world,people)
    genome,stats=get_plan(world,people,trips,method,world.seed if seed is None else seed,small=small)
    obj,tasks=eval_plan(genome,people,trips,horizon=world.horizon,battery_cap=world.ground_battery)
    segments=[];rescues=[]
    for r,assigned in enumerate(tasks):
        for j,start,finish,tr in assigned:
            seq,end=mission_segments(people[j],r,tr,start)
            segments.extend(seq)
            rescues.append({'t':end,'start':start,'id':people[j].id,'x':people[j].x,'y':people[j].y,
                            'priority':people[j].priority,'r':r})
    segments.sort(key=lambda v:(v['r'],v['t0']))
    rescues.sort(key=lambda v:v['t'])
    resc_count=sum(v['t']<=world.horizon for v in rescues)
    return {'method':method,'label':LABELS[method], 'segments':segments,
            'rescues':rescues,'plan':[[people[j].id for j,*_ in tasks[r]] for r in range(len(trips))],
            'opt':stats,'final':{'rescued':resc_count,'total':len(people),
                'weighted_unrescued':obj[0], 'energy':round(obj[2],2),
                'last_rescue':round(max((e['t'] for e in rescues if e['t']<=world.horizon),default=0),2),
                'finished_at':round(min(world.horizon,max((s['t1'] for s in segments),default=0)),2)},
            'known_people':[{'id':p.id,'x':p.x,'y':p.y,'priority':p.priority} for p in people]}
