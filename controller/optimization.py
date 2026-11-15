"""Public-data NSGA-II problems adapted from the immutable v0.5.2 reference.

Origin: main part/scout.py and rescue.py (optimize/evaluation/heuristics).
The exact evolutionary kernel is vendored separately. No World, sensor,
private layout, event tape, or ID prefix is available in this module.
Distances/trips are estimates supplied by the public geometry adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time

from controller.assignment import AssignmentError,assignment_seed
from controller.vendor.nsga2_v052 import run_nsga2,order_crossover

POLICY_WEIGHTS={'balanced':(1.,.12),'urgent':(1.25,.06),'throughput':(2.25,.04),
                'energy_saver':(.65,4.),'cooperative':(1.6,.2)}
PROFILE_SEED_OFFSETS={'balanced':0,'urgent':101,'throughput':211,'energy_saver':307,'cooperative':419}


def number(value,*,positive=False):
    if type(value) not in (int,float) or not math.isfinite(value) or value<0 or (positive and value==0):
        raise ValueError('Expected a finite nonnegative number')
    return value


def genome_check(genome,n,m):
    order,assignment=genome
    if (len(order)!=n or len(assignment)!=n or any(type(i) is not int for i in order) or
        set(order)!=set(range(n)) or any(type(r) is not int or not 0<=r<m for r in assignment)):
        raise ValueError('Invalid permutation/assignment genome')


@dataclass(frozen=True)
class Crew:
    id:str
    speed:float=1.
    ready_at:float=0.
    usable_wh:float|None=None

    def __post_init__(self):
        if not isinstance(self.id,str) or not self.id:raise ValueError('Opaque crew ID required')
        number(self.speed,positive=True);number(self.ready_at)
        if self.usable_wh is not None:number(self.usable_wh)


@dataclass(frozen=True)
class Sector:
    id:str
    prior:float=1.
    column:int=0
    row:int=0

    def __post_init__(self):
        if not isinstance(self.id,str) or not self.id:raise ValueError('Opaque sector ID required')
        number(self.prior)
        if type(self.column) is not int or type(self.row) is not int:raise ValueError('Integer grid coordinates required')


@dataclass(frozen=True)
class Target:
    id:str
    priority:float
    deadline:float|None=None

    def __post_init__(self):
        if not isinstance(self.id,str) or not self.id:raise ValueError('Opaque target ID required')
        number(self.priority)
        if self.deadline is not None:number(self.deadline)


@dataclass(frozen=True)
class Trip:
    duration_s:float
    energy_wh:float

    def __post_init__(self):number(self.duration_s);number(self.energy_wh)


def unique(items):
    if len({v.id for v in items})!=len(items):raise ValueError('Duplicate public IDs')


class ScoutProblem:
    def __init__(self,sectors,crew,distances,initial_distances,*,horizon,now=0.,scan_s=2.8,
                 scan_wh=.55,wh_per_m=.069,idle_power_w=0.,return_distances=None,
                 initial_seconds=None,initial_wh=None):
        self.sectors=tuple(sectors);self.crew=tuple(crew)
        unique(self.sectors);unique(self.crew)
        self.n=len(self.sectors);self.m=len(self.crew)
        self.horizon=number(horizon,positive=True);self.now=number(now)
        self.scan_s=number(scan_s);self.scan_wh=number(scan_wh);self.wh_per_m=number(wh_per_m)
        self.idle_power_w=number(idle_power_w)
        self.distances=self._matrix(distances,self.n,self.n)
        self.initial=self._matrix(initial_distances,self.m,self.n)
        self.initial_seconds=self._matrix(initial_seconds,self.m,self.n) if initial_seconds is not None else None
        self.initial_wh=self._matrix(initial_wh,self.m,self.n) if initial_wh is not None else None
        self.returns=self._matrix(return_distances,self.m,self.n) if return_distances is not None else None

    @staticmethod
    def _matrix(values,rows,columns):
        if len(values)!=rows or any(len(row)!=columns for row in values):raise ValueError('Distance matrix shape differs')
        return tuple(tuple(None if value is None else number(value) for value in row) for row in values)

    def simulate(self,genome):
        genome_check(genome,self.n,self.m)
        routes=[[] for _ in self.crew]
        for i in genome[0]:routes[genome[1][i]].append(i)
        clocks=[max(self.now,c.ready_at) for c in self.crew];energy=[0.]*self.m
        times={};executed=[[] for _ in self.crew]
        for r,route in enumerate(routes):
            previous=None
            for i in route:
                length=self.initial[r][i] if previous is None else self.distances[previous][i]
                if length is None:continue
                seconds=self.initial_seconds[r][i] if previous is None and self.initial_seconds is not None else length/self.crew[r].speed
                flight_wh=self.initial_wh[r][i] if previous is None and self.initial_wh is not None else length*self.wh_per_m
                if seconds is None or flight_wh is None:continue
                duration=seconds+self.scan_s
                needed=flight_wh+self.scan_wh+duration*self.idle_power_w/3600
                reserve=0.
                if self.crew[r].usable_wh is not None:
                    back=self.returns[r][i] if self.returns is not None else None
                    if back is None:continue
                    reserve=back*self.wh_per_m+back/self.crew[r].speed*self.idle_power_w/3600
                    if energy[r]+needed+reserve>self.crew[r].usable_wh+1e-9:continue
                clocks[r]+=duration;energy[r]+=needed;times[i]=clocks[r]
                executed[r].append(i);previous=i
        utility=sum(s.prior*max(0,1-times.get(i,self.horizon*2)/self.horizon) for i,s in enumerate(self.sectors))
        punishment=sum(max(0,t-self.horizon) for t in clocks)*2
        objectives=(-utility+punishment,max(clocks,default=self.now)+punishment,sum(energy)+punishment)
        return objectives,executed

    def heuristic(self,method):
        routes=[[] for _ in self.crew]
        if not self.m:return routes
        if method=='sweep':
            rows=sorted({s.row for s in self.sectors});ids=[]
            for row in rows:
                line=sorted((i for i,s in enumerate(self.sectors) if s.row==row),key=lambda i:self.sectors[i].column)
                ids.extend(line if row%2==0 else line[::-1])
            for i,s in enumerate(ids):routes[min(self.m-1,i*self.m//max(1,self.n))].append(s)
            return routes
        remaining=set(range(self.n));previous=[None]*self.m;clock=[max(self.now,c.ready_at) for c in self.crew];scanned=set()
        coordinates={(s.column,s.row):i for i,s in enumerate(self.sectors)}
        while remaining:
            r=min(range(self.m),key=lambda k:clock[k])
            def score(i):
                d=self.initial[r][i] if previous[r] is None else self.distances[previous[r]][i]
                if d is None:return -math.inf
                if method=='frontier':
                    s=self.sectors[i]
                    neighbours=[coordinates.get((s.column+dx,s.row+dy)) for dx,dy in ((1,0),(-1,0),(0,1),(0,-1))]
                    return s.prior*(1.3 if any(k in scanned for k in neighbours) else .7)/(.8+d)
                return self.sectors[i].prior/(1+d/self.crew[r].speed)
            i=max(sorted(remaining),key=score)
            d=self.initial[r][i] if previous[r] is None else self.distances[previous[r]][i]
            if d is not None:clock[r]+=d/self.crew[r].speed+self.scan_s
            previous[r]=i;routes[r].append(i);remaining.remove(i);scanned.add(i)
        return routes


class RescueProblem:
    def __init__(self,targets,crew,trips,*,horizon,now=0.,first_trips=None,available_now=None):
        self.targets=tuple(targets);self.crew=tuple(crew)
        unique(self.targets);unique(self.crew)
        self.n=len(self.targets);self.m=len(self.crew)
        self.horizon=number(horizon,positive=True);self.now=number(now)
        self.available_now=tuple(c.ready_at<=now for c in self.crew) if available_now is None else tuple(available_now)
        if len(self.available_now)!=self.m or any(type(v) is not bool for v in self.available_now):
            raise ValueError('Expected one availability boolean per crew')
        self.trips=self._trips(trips)
        self.first=self.trips if first_trips is None else self._trips(first_trips)

    def _trips(self,values):
        if len(values)!=self.m or any(len(row)!=self.n for row in values):raise ValueError('Trip matrix shape differs')
        if any(t is not None and not isinstance(t,Trip) for row in values for t in row):raise ValueError('Expected Trip or unreachable None')
        return tuple(tuple(row) for row in values)

    def simulate(self,genome):
        genome_check(genome,self.n,self.m)
        starts=[max(self.now,c.ready_at) for c in self.crew];remaining=[c.usable_wh for c in self.crew]
        used=[False]*self.m;saved=set();completion={};consumed=0.;tasks=[[] for _ in self.crew]
        for j in genome[0]:
            r=genome[1][j];trip=self.trips[r][j] if used[r] else self.first[r][j]
            if trip is None:continue
            finish=starts[r]+trip.duration_s;deadline=self.targets[j].deadline
            if finish>self.horizon or (deadline is not None and finish>deadline):continue
            if remaining[r] is not None and trip.energy_wh>remaining[r]+1e-9:continue
            tasks[r].append((j,starts[r],finish,trip));used[r]=True;starts[r]=finish
            if remaining[r] is not None:remaining[r]-=trip.energy_wh
            consumed+=trip.energy_wh;saved.add(j);completion[j]=finish
        unrescued=sum(t.priority for j,t in enumerate(self.targets) if j not in saved)
        times=sum(t.priority*completion.get(j,self.horizon) for j,t in enumerate(self.targets))
        return (float(unrescued),float(times),float(consumed)),tasks

    def heuristic(self,method):
        clock=[max(self.now,c.ready_at) for c in self.crew];energy=[c.usable_wh for c in self.crew]
        used=[False]*self.m;order=[];assign=[0]*self.n;remaining=set(range(self.n))
        while remaining:
            choices=[]
            for j in remaining:
                for r in range(self.m):
                    tr=self.trips[r][j] if used[r] else self.first[r][j]
                    if tr is None:continue
                    finish=clock[r]+tr.duration_s;deadline=self.targets[j].deadline
                    if finish>self.horizon or (deadline is not None and finish>deadline):continue
                    if energy[r] is not None and tr.energy_wh>energy[r]+1e-9:continue
                    score=tr.duration_s if method=='nearest' else finish/max(1,self.targets[j].priority*1.75)
                    choices.append((score,finish,j,r))
            if not choices:break
            _,finish,j,r=min(choices);tr=self.trips[r][j] if used[r] else self.first[r][j]
            order.append(j);assign[j]=r;clock[r]=finish;used[r]=True
            if energy[r] is not None:energy[r]-=tr.energy_wh
            remaining.remove(j)
        order.extend(sorted(remaining))
        return order,assign


def _run(problem,seed,population,generations,scout,policy,scout_mode='coverage',rescue_initializer='heuristic'):
    n,m=problem.n,problem.m
    if type(seed) is not int or type(population) is not int or type(generations) is not int or population<4 or generations<0:
        raise ValueError('Invalid optimizer seed or budget')
    if policy not in POLICY_WEIGHTS:raise ValueError('Unknown strategy policy')
    if rescue_initializer not in ('heuristic','assignment'):raise ValueError('Unknown rescue initializer')
    if not n or not m:
        return {'routes':{c.id:[] for c in problem.crew},'pareto':[],
                'stats':{'evaluations':0,'reason':'empty_problem' if not n else 'no_available_crew'}}
    heuristic=[]
    if scout:
        for method in ('greedy','sweep','frontier'):
            rs=problem.heuristic(method);assignment=[0]*n
            for r,route in enumerate(rs):
                for i in route:assignment[i]=r
            heuristic.append(([i for route in rs for i in route],assignment))
    else:heuristic=[problem.heuristic(method) for method in ('greedy','nearest')]
    initializer_audit=None
    if not scout and rescue_initializer=='assignment':
        began=time.perf_counter()
        try:
            candidate,initializer_audit=assignment_seed(problem,heuristic[0])
            heuristic.insert(0,candidate)
        except AssignmentError as error:
            initializer_audit={'method':'assignment_lp_v1','status':'fallback','reason':str(error)}
        initializer_audit['wall_s']=time.perf_counter()-began
    calls=[0]
    def init(rng):
        calls[0]+=1
        if calls[0]<=len(heuristic):
            order,assignment=heuristic[calls[0]-1];return order[:],assignment[:]
        order=list(range(n));rng.shuffle(order)
        return order,[rng.randrange(m) for _ in range(n)]
    def mate(a,b,rng):
        x,y=order_crossover(a[0],b[0],rng)
        u=[a[1][i] if rng.random()<.5 else b[1][i] for i in range(n)]
        v=[b[1][i] if rng.random()<.5 else a[1][i] for i in range(n)]
        return (x,u),(y,v)
    def mutate(a,rng):
        order=a[0][:];assignment=a[1][:]
        if n>1 and rng.random()<(.8 if scout else .85):
            i,j=rng.sample(range(n),2);order[i],order[j]=order[j],order[i]
        if rng.random()<(.42 if scout else .5):
            if scout:
                # Upstream scout draws the target index before the agent;
                # subscript-assignment evaluation order would reverse these.
                k=rng.randrange(n);assignment[k]=rng.randrange(m)
            else:assignment[rng.randrange(n)]=rng.randrange(m)
        if n>(1 if scout else 2) and rng.random()<(.18 if scout else .16):
            i,j=sorted(rng.sample(range(n),2));order[i:j+1]=reversed(order[i:j+1])
        return order,assignment
    front,stats=run_nsga2(init,lambda g:problem.simulate(g)[0],mate,mutate,
        pop_size=population,generations=generations,seed=seed+(781 if scout else 915))
    tw,ew=POLICY_WEIGHTS[policy]
    if not scout:
        key=lambda i:(i.f[0],tw*i.f[1]+ew*i.f[2])
    elif scout_mode=='efficient':
        key=lambda i:(i.f[0]+.005*i.f[1]+.09*i.f[2],i.f[2])
    else:
        key=lambda i:(i.f[0]+.005*i.f[1]+.002*i.f[2],i.f[1])
    best=min(front,key=key)
    objectives,execution=problem.simulate(best.genome)
    routes={c.id:[(problem.sectors[j].id if scout else problem.targets[j[0]].id) for j in execution[r]]
            for r,c in enumerate(problem.crew)}
    pareto=[{'objectives':list(ind.f),'genome':ind.genome,'rank':ind.rank,
             'crowding':ind.crowd if math.isfinite(ind.crowd) else None,
             'crowding_boundary':not math.isfinite(ind.crowd)} for ind in front]
    result={'routes':routes,'selected_objectives':list(objectives),'genome':best.genome,'pareto':pareto,
            'stats':{**stats,'seed':seed,'effective_seed':seed+(781 if scout else 915),
                     'population':population,'generations':generations,'policy':policy}}
    if initializer_audit is not None:
        initializer_audit['selected_genome_matches']=initializer_audit['status']!='fallback' and best.genome==heuristic[0]
        result['initializer']=initializer_audit
    return result


def optimize_scout(problem,seed,*,population=40,generations=32,mode='coverage'):
    return _run(problem,seed,population,generations,True,'balanced',mode)


def optimize_rescue(problem,seed,*,population=42,generations=38,policy='balanced',initializer='heuristic'):
    return _run(problem,seed,population,generations,False,policy,rescue_initializer=initializer)
