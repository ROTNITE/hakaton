"""Transparent baselines and a small real non-dominated sorting GA (NSGA-II)."""
import math
import random
import time
from world import BASE


def dominates(a,b):
    return all(x<=y+1e-9 for x,y in zip(a,b)) and any(x<y-1e-9 for x,y in zip(a,b))


def fronts(values):
    dominated=[[] for _ in values];counts=[0]*len(values)
    first=[]
    for i in range(len(values)):
        for j in range(len(values)):
            if i==j:continue
            if dominates(values[i],values[j]):dominated[i].append(j)
            elif dominates(values[j],values[i]):counts[i]+=1
        if counts[i]==0:first.append(i)
    out=[]
    while first:
        out.append(first);next_set=[]
        for i in first:
            for j in dominated[i]:
                counts[j]-=1
                if counts[j]==0:next_set.append(j)
        first=next_set
    return out


def crowding(front,values):
    dist={i:0.0 for i in front}
    if len(front)<=2:return {i:float('inf') for i in front}
    for d in range(len(values[0])):
        order=sorted(front,key=lambda i:values[i][d])
        dist[order[0]]=dist[order[-1]]=float('inf')
        lo=values[order[0]][d];hi=values[order[-1]][d]
        if hi-lo<1e-10:continue
        for k in range(1,len(order)-1):
            dist[order[k]]+=(values[order[k+1]][d]-values[order[k-1]][d])/(hi-lo)
    return dist


def ga(initial, evaluate, mutate, seed, population=20, generations=10):
    """Returns [ (genome, fitness) ] first-front members; no scalar-only GA shortcut."""
    rng=random.Random(seed)
    pop=[initial(rng) for _ in range(population)]
    values=[evaluate(g) for g in pop]
    for _ in range(generations):
        tiers=fronts(values)
        ranks={i:rank for rank,f in enumerate(tiers) for i in f}
        distance={i:val for f in tiers for i,val in crowding(f,values).items()}
        def tournament():
            a,b=rng.randrange(len(pop)),rng.randrange(len(pop))
            return pop[a if (ranks[a],-distance[a])<(ranks[b],-distance[b]) else b]
        offspring=[mutate(tournament(),rng) for _ in range(population)]
        all_pop=pop+offspring
        all_v=values+[evaluate(v) for v in offspring]
        pop=[];values=[]
        for f in fronts(all_v):
            if len(pop)+len(f)<=population:chosen=f
            else:
                cd=crowding(f,all_v)
                chosen=sorted(f,key=lambda i:cd[i],reverse=True)[:population-len(pop)]
            pop.extend(all_pop[i] for i in chosen)
            values.extend(all_v[i] for i in chosen)
            if len(pop)>=population:break
    return [(pop[i],values[i]) for i in fronts(values)[0]]


def euclidean(a,b):return math.hypot(a[0]-b[0],a[1]-b[1])


def scout_choices(world,terrain,scouts,sectors,method,covered,signals,seed):
    """Assign at most one unclaimed sector to each free drone.

    No true person positions used: only prior, public signal sectors and coverage.
    """
    if not scouts or not sectors:return {},[],0.0
    start=time.perf_counter();order=sorted(sectors)
    pos={r:scouts[r]['pos'] for r in scouts}
    active=list(sorted(scouts))
    def value(sec,r):
        p=world.prior[sec];distance=euclidean(pos[r],world.sector_center(sec))
        sig=8 if sec in signals else 0
        if method=='random':return stable_random(sec,r,seed)
        if method=='sweep':return -(sec+(r%2)*.01)
        if method=='frontier':
            k=world.sectors_per_side
            neighbor=sum(j in covered for j in (sec-1,sec+1,sec-k,sec+k)
                         if 0<=j<k*k and (abs(j%k-sec%k)+abs(j//k-sec//k))==1)
            return sig+3*neighbor+p*1.5-.15*distance
        return sig+2*p-.27*distance
    if method!='nsga2':
        result={};unused=set(order)
        for r in active:
            if not unused:break
            sec=max(unused,key=lambda s:(value(s,r),-s))
            result[r]=sec;unused.remove(sec)
        return result,[],(time.perf_counter()-start)*1000
    # 3 real Pareto objectives: expected information gained, total arrival time,
    # and expended battery per selected scout trip. A short horizon only.
    candidates=sorted(order,key=lambda s:max(value(s,r) for r in active),reverse=True)[:min(18,len(order))]
    n=min(len(active),len(candidates));active=active[:n]
    def init(rng):return tuple(rng.sample(candidates,n))
    def mut(g,rng):
        g=list(g)
        if len(g)>1 and rng.random()<.65:
            a,b=rng.sample(range(len(g)),2);g[a],g[b]=g[b],g[a]
        if rng.random()<.6:
            i=rng.randrange(len(g));choices=[s for s in candidates if s not in g]
            if choices:g[i]=rng.choice(choices)
        return tuple(g)
    def ev(g):
        info=0;time_cost=0;energy=0
        for idx,sec in enumerate(g):
            r=active[idx];dist=euclidean(pos[r],world.sector_center(sec))
            visibility=terrain.sector_visibility(sec)
            utility=world.prior[sec]+(3.5 if sec in signals else 0)
            info+=utility*visibility
            time_cost+=dist/(2.0+.1*(r%3))+2.8
            energy+=dist*1.05+3
        return (-info,time_cost,energy)
    pareto=ga(init,ev,mut,seed,population=18,generations=8)
    # Pick a predeclared trade-off from the Pareto set, not using hidden target truth.
    def scalar(x):
        fit=x[1]
        return fit[0]*2.4 + fit[1]*.11 + fit[2]*.018
    best=min(pareto,key=scalar)[0]
    archive=[{'info':round(-f[0],2),'time':round(f[1],2),
              'energy':round(f[2],2)} for _,f in pareto]
    return dict(zip(active,best)),archive,(time.perf_counter()-start)*1000


def stable_random(sec,r,seed):
    from world import stable_unit
    return stable_unit('random-scout',seed,sec,r)


def allocate_rescue(world,terrain,known,robots,method,seed):
    """Select one currently feasible outward-and-return trip per idle robot.

    Both outbound and return segments are checked against current known map.
    A battery reserve of 10% is mandatory. Only known targets are passed in.
    """
    start=time.perf_counter();out={};archive=[]
    if not robots or not known:return out,archive,0.0
    robot_ids=sorted(robots)
    entries={}
    # Bounded candidate window is a documented short-horizon approximation.
    # Include both nearby and medically urgent cases; revisit remaining targets
    # after each completed trip and at disturbances.
    if len(known)>20:
        ranked=sorted(known,key=lambda p:(
            min(euclidean(robots[r]['pos'],(p.x,p.y)) for r in robot_ids)/max(1,p.priority*.7),
            p.id))
        urgent=sorted(known,key=lambda p:(-p.priority,p.id))[:5]
        pool={p.id:p for p in ranked[:19]}
        pool.update({p.id:p for p in urgent})
        known=list(pool.values())
    for r in robot_ids:

        pos=robots_state_pos(robots[r]);batt=robots[r]['battery']
        for p in known:
            outbound,dc=terrain.route(pos,(p.x,p.y))
            backward,db=terrain.route((p.x,p.y),BASE)
            if not outbound or not backward:continue
            energy=(dc+db)*.92+5.0
            if energy > batt - .1*world.rescuer_battery+1e-8:continue
            duration=(dc+db)/(0.60+.045*(r%4))+8
            if robots[r]['time']+duration>world.horizon:continue
            entries[r,p.id]=(p,dc,db,energy,duration)
    if not entries:return {},[],(time.perf_counter()-start)*1000
    if method!='nsga2':
        remaining={p.id:p for p in known}
        for r in robot_ids:
            candidates=[(p,entries[(r,p.id)]) for p in remaining.values() if (r,p.id) in entries]
            if not candidates:continue
            def key(row):
                p,(_,dc,db,energy,duration)=row
                if method=='nearest':return dc
                if method=='local':return duration/max(1,p.priority)+.010*energy
                return duration/max(1,p.priority)+.035*dc
            p,_=min(candidates,key=key)
            out[r]=p.id;remaining.pop(p.id)
        if method=='local' and len(out)>1:
            # Deterministic pair-wise assignment improvement.
            for _ in range(3):
                improved=False
                for a in robot_ids:
                    for b in robot_ids:
                        if a>=b or a not in out or b not in out:continue
                        pa,pb=out[a],out[b]
                        if (a,pb) not in entries or (b,pa) not in entries:continue
                        before=entries[a,pa][4]+entries[b,pb][4]
                        after=entries[a,pb][4]+entries[b,pa][4]
                        if after+1e-7<before:out[a],out[b]=pb,pa;improved=True
                if not improved:break
        return out,[],(time.perf_counter()-start)*1000
    # NSGA-II assignment across all idle robots, restricted to nearest/urgent
    # 12 known candidates. Genotype contains one person id or None per robot.
    candidate=sorted(known,key=lambda p:(-p.priority,min((entries[r,p.id][4]
                    for r in robot_ids if (r,p.id) in entries),default=1e10)))[:max(6,min(12,len(known)))]
    eligible=[p.id for p in candidate]
    def init(rng):
        perm=rng.sample(eligible,len(eligible));rng.shuffle(perm)
        return tuple(perm[:len(robot_ids)]+[None]*max(0,len(robot_ids)-len(perm)))
    def mut(g,rng):
        g=list(g)
        if len(g)>1:
            a,b=rng.sample(range(len(g)),2);g[a],g[b]=g[b],g[a]
        if rng.random()<.6:
            i=rng.randrange(len(g));free=[p for p in eligible if p not in g]
            if free:g[i]=rng.choice(free)
        if rng.random()<.12:g[rng.randrange(len(g))]=None
        return tuple(g)
    def ev(g):
        useful=0;finish=0;energy=0
        for r,pid in zip(robot_ids,g):
            if pid is None:continue
            item=entries.get((r,pid))
            if not item:continue
            person,_,_,en,duration=item
            useful+=person.priority*2.4
            finish+=duration;energy+=en
        return (-useful,finish,energy)
    pareto=ga(init,ev,mut,seed,population=20,generations=10)
    # Strong preference for more/urgent actual feasible appointments.
    best=min(pareto,key=lambda z:z[1][0]*12+z[1][1]*.08+z[1][2]*.025)[0]
    for r,pid in zip(robots,best):
        if pid is not None and (r,pid) in entries:out[r]=pid
    archive=[{'priority':round(-f[0],2),'time':round(f[1],2),
              'energy':round(f[2],2)} for _,f in pareto]
    return out,archive,(time.perf_counter()-start)*1000


def robots_state_pos(robot):return robot['pos']
