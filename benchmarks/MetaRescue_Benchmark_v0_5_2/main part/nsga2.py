"""Real, dependency-free, elitist NSGA-II (Deb et al.):
fast non-dominated sorting, crowding, binary crowded tournament, elitist survival.
Two problem-specific genome types are implemented by callers.
"""
from __future__ import annotations
from dataclasses import dataclass
import random, math, time

@dataclass
class Individual:
    genome: object
    f: tuple=()
    rank: int=0
    crowd: float=0.0


def dominates(a,b):
    return all(x<=y+1e-10 for x,y in zip(a,b)) and any(x<y-1e-10 for x,y in zip(a,b))


def assign_fronts(pop):
    # O(MN^2), appropriate for intentionally small real-time populations.
    dominated=[[] for _ in pop]
    counts=[0]*len(pop)
    fronts=[[]]
    for i,p in enumerate(pop):
        for j,q in enumerate(pop):
            if i==j:continue
            if dominates(p.f,q.f):dominated[i].append(j)
            elif dominates(q.f,p.f):counts[i]+=1
        if counts[i]==0:
            p.rank=0;fronts[0].append(i)
    layer=0
    while layer<len(fronts) and fronts[layer]:
        nxt=[]
        for i in fronts[layer]:
            for j in dominated[i]:
                counts[j]-=1
                if counts[j]==0:
                    pop[j].rank=layer+1;nxt.append(j)
        if nxt: fronts.append(nxt)
        layer+=1
    return fronts


def assign_crowding(pop,indices):
    if not indices: return
    for k in indices:pop[k].crowd=0.0
    if len(indices)<3:
        for k in indices:pop[k].crowd=float('inf')
        return
    for m in range(len(pop[indices[0]].f)):
        sorted_idx=sorted(indices,key=lambda i:pop[i].f[m])
        pop[sorted_idx[0]].crowd=pop[sorted_idx[-1]].crowd=float('inf')
        lo=pop[sorted_idx[0]].f[m];hi=pop[sorted_idx[-1]].f[m]
        if hi-lo<1e-12:continue
        for j in range(1,len(sorted_idx)-1):
            ix=sorted_idx[j]
            if not math.isinf(pop[ix].crowd):
                pop[ix].crowd+=(pop[sorted_idx[j+1]].f[m]-pop[sorted_idx[j-1]].f[m])/(hi-lo)


def tournament(pop,rng):
    x,y=rng.sample(pop,2)
    if x.rank!=y.rank:return x if x.rank<y.rank else y
    if x.crowd!=y.crowd:return x if x.crowd>y.crowd else y
    return x if rng.random()<.5 else y


def run_nsga2(init, evaluate, mate, mutate, pop_size=40,generations=35,seed=1234):
    rng=random.Random(seed)
    start=time.perf_counter()
    pop=[Individual(init(rng)) for _ in range(pop_size)]
    cache={};eval_count=0
    def scored(ind):
        nonlocal eval_count
        key=str(ind.genome)
        if key not in cache:
            cache[key]=tuple(float(v) for v in evaluate(ind.genome));eval_count+=1
        ind.f=cache[key]
        return ind
    pop=[scored(ind) for ind in pop]
    for gen in range(generations):
        fronts=assign_fronts(pop)
        for front in fronts:assign_crowding(pop,front)
        children=[]
        while len(children)<pop_size:
            p1=tournament(pop,rng).genome
            p2=tournament(pop,rng).genome
            a,b=mate(p1,p2,rng)
            children.extend([scored(Individual(mutate(a,rng))),
                             scored(Individual(mutate(b,rng)))])
        combined=pop+children[:pop_size]
        next_gen=[]
        fronts=assign_fronts(combined)
        for front in fronts:
            assign_crowding(combined,front)
            if len(next_gen)+len(front)<=pop_size:
                next_gen.extend(combined[i] for i in front)
            else:
                needed=pop_size-len(next_gen)
                next_gen.extend(sorted((combined[i] for i in front),
                                   key=lambda z:z.crowd,reverse=True)[:needed]);break
        pop=next_gen
    fronts=assign_fronts(pop)
    for front in fronts:assign_crowding(pop,front)
    first=[pop[i] for i in fronts[0]]
    return first, {'evaluations':eval_count,'wall_ms':round((time.perf_counter()-start)*1000,1),
                   'population':pop_size,'generations':generations,'pareto_size':len(first)}


def order_crossover(a,b,rng):
    n=len(a)
    if n<2:return a[:],b[:]
    lo,hi=sorted(rng.sample(range(n),2))
    def child(x,y):
        out=[-1]*n
        out[lo:hi+1]=x[lo:hi+1]
        remaining=[v for v in y if v not in out]
        it=iter(remaining)
        return [next(it) if v==-1 else v for v in out]
    return child(a,b),child(b,a)
