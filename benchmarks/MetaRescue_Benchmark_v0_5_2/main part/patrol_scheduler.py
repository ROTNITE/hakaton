"""Online scout sector choice and actual recurring NSGA-II patrol optimizations."""
from __future__ import annotations
import math,random,time
from nsga2 import run_nsga2,order_crossover

class PatrolScheduler:
    def __init__(self,world,initial_routes):
        self.world=world
        self.positions=[(1.,1.) for _ in range(world.n_scouts)]
        self.reserved={};self.last_scanned={};self.priorities={};self.replans=0;self.opt_ms=0.
        self.next_auto=0.;self.preferred={};self.strategy='coverage'
        # Every sector has exactly one initial owner. Replanning may never silently
        # discard unfinished primary reconnaissance.
        n=world.sector_count**2
        self.unvisited=set(range(n))
        self.queues=[[] for _ in range(world.n_scouts)]
        seen=set()
        for r,route in enumerate(initial_routes[:world.n_scouts]):
            for sec in route:
                if 0<=sec<n and sec not in seen:
                    self.queues[r].append(sec);seen.add(sec)
        for sec in range(n):
            if sec not in seen:
                r=min(range(world.n_scouts),key=lambda j:len(self.queues[j]))
                self.queues[r].append(sec)
        self.primary_completed_at=None
    @property
    def primary_complete(self):
        return not self.unvisited
    def priority(self,sector,t):
        age=t-self.last_scanned.get(sector,-self.world.horizon)
        importance,stamp=self.priorities.get(sector,(0.,-1e9))
        # Temporary requests have an expiry; no perpetual rescue-support hotspots.
        extra=max(0.,importance)*2.5 if t-stamp<=90 else 0.
        age_factor={'coverage':1.,'risk':.72,'efficient':.75,'hazard_support':.66}.get(self.strategy,1.)
        hazard_factor={'coverage':1.,'risk':1.8,'efficient':.65,'hazard_support':2.1}.get(self.strategy,1.)
        return self.world.prior[sector]+age_factor*min(4,max(0,age)/105)+extra*hazard_factor
    def select(self,r,t):
        w=self.world
        if self.unvisited:
            # Initial coverage is non-preemptible by Global AI. Another scout may
            # reserve our next sector, so remove only reservations, never other work.
            while self.queues[r] and (self.queues[r][0] in self.reserved or
                                      self.queues[r][0] not in self.unvisited):
                self.queues[r].pop(0)
            if self.queues[r]:
                s=self.queues[r].pop(0)
            else:
                free=[sec for sec in self.unvisited if sec not in self.reserved]
                if not free:return None
                s=min(free,key=lambda sec:(math.dist(self.positions[r],w.center(sec)),sec))
        else:
            preferred=self.preferred.pop(r,None)
            if preferred is not None and preferred not in self.reserved:
                s=preferred
            else:
                candidates=[x for x in range(w.sector_count**2) if x not in self.reserved]
                if not candidates:return None
                distance_penalty=.28 if self.strategy=='efficient' else .10
                s=max(candidates,key=lambda sec:(self.priority(sec,t) -
                  distance_penalty*math.dist(self.positions[r],w.center(sec)), -sec))
        self.reserved[s]=r
        return s
    def scanned(self,r,sector,t):
        self.reserved.pop(sector,None)
        self.last_scanned[sector]=t
        self.unvisited.discard(sector)
        if not self.unvisited and self.primary_completed_at is None:
            self.primary_completed_at=t
        self.positions[r]=self.world.center(sector)
        if sector in self.priorities:
            importance,stamp=self.priorities[sector]
            self.priorities[sector]=(max(0,importance-1),stamp)
    def highlight(self,sectors,t,importance=3):
        # Highlight is advisory and NEVER mutates primary queues. The previous
        # implementation removed sectors from every queue, losing coverage.
        for sec in sectors:
            if 0<=sec<self.world.sector_count**2:
                self.priorities[sec]=(importance,t)
    def online_nsga2(self,t,agents=None,limit=14):
        """Short-horizon genuine NSGA-II replan, not a static label.
        Partial mission only: reprioritize up to 14 sectors, leaving others queued.
        """
        # Scout optimization is for adaptive patrol only. The initial NSGA-II
        # covers all unvisited sectors; postponing it loses early victims.
        if not self.primary_complete:return {}
        st=time.perf_counter()
        w=self.world
        idle=[r for r in (agents if agents is not None else range(w.n_scouts))]
        if not idle:return {}
        candidates=[s for s in range(w.sector_count**2) if s not in self.reserved]
        if len(candidates)<2:return {}
        candidates=sorted(candidates,key=lambda s:(-self.priority(s,t),s))[:limit]
        n=len(candidates);R=len(idle)
        if R==0:return {}
        def fitness(genome):
            order,assign=genome
            loc={r:self.positions[r] for r in idle};clock={r:0. for r in idle};eng=0.;quality=0.
            for j in order:
                r=idle[assign[j]];sector=candidates[j]
                d=math.dist(loc[r],w.center(sector))
                clock[r]+=d/w.scout_speed(r)+2.8
                eng+=d*.69+.55
                quality+=self.priority(sector,t)*clock[r]
                loc[r]=w.center(sector)
            return (quality,max(clock.values()),eng)
        def initial(rng):
            indices=list(range(n));rng.shuffle(indices)
            return (indices,[rng.randrange(R) for _ in range(n)])
        def mate(a,b,rng):
            o1,o2=order_crossover(a[0],b[0],rng)
            return (o1,[a[1][i] if rng.random()<.5 else b[1][i] for i in range(n)]), (o2,[b[1][i] if rng.random()<.5 else a[1][i] for i in range(n)])
        def mutate(a,rng):
            order=a[0][:];ass=a[1][:]
            if n>1:
                i,j=rng.sample(range(n),2);order[i],order[j]=order[j],order[i]
            ass[rng.randrange(n)]=rng.randrange(R)
            return order,ass
        front,stats=run_nsga2(initial,fitness,mate,mutate,pop_size=12,generations=6,seed=w.seed+int(t*37)+177)
        energy_w=1.8 if self.strategy=='efficient' else .05
        best=min(front,key=lambda x:x.f[0]+0.2*x.f[1]+energy_w*x.f[2])
        new={r:[] for r in idle}
        for j in best.genome[0]:new[idle[best.genome[1][j]]].append(candidates[j])
        # Priorities are consumed by each agent at its *next* decision point.
        for r in idle:
            pending=[s for s in self.queues[r] if s not in candidates]
            self.queues[r]=new[r]+pending
        self.opt_ms+=(time.perf_counter()-st)*1000
        self.replans+=1;self.next_auto=t+140
        return {'replan':self.replans,'t':round(t,3),'scope':'scout',
                'assigned':{str(r):new[r] for r in idle},'objectives':list(best.f),
                'pareto':stats.get('pareto_size',0),'compute_ms':round((time.perf_counter()-st)*1000,2)}
