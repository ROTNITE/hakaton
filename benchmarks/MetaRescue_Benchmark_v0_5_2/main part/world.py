"""Deterministic hidden-target rescue world with configurable map and fleet size.
Coordinates are continuous cell units; one cell equals CELL_METRES meters.
No planner may access World.people before a target is detected.
"""
from __future__ import annotations
from dataclasses import dataclass
import heapq, math, random, bisect

GRID = 25
SECTOR_W = 5
SECTORS = GRID // SECTOR_W
CELL_METRES = 10.0
BASE = (1.0, 1.0)
SCOUTS = 3
RESCUERS = 4
SCOUT_SPEED = (2.1, 1.95, 2.25)
GROUND_SPEED = (0.62, 0.67, 0.59, 0.64)
SCOUT_BATTERY = 120.0
GROUND_BATTERY = 220.0
ENERGY_RESERVE = 0.10
SCOUT_SCAN_S = 2.8
PICKUP_S = 5.0
DROPOFF_S = 3.0
HORIZON = 480
# Probability of at least one event of this kind in each 80-second model window.
DEFAULT_PROBABILITIES = {
    'collapse': 20, 'fire': 18, 'flood': 12, 'mud': 25,
    'road_damage': 23, 'smoke': 28, 'appearance': 30,
}
EVENT_NAMES = {
    'collapse':'Обрушение', 'fire':'Пожар', 'flood':'Затопление',
    'mud':'Грязь', 'road_damage':'Повреждение дороги',
    'smoke':'Дым / плохая видимость', 'smoke_clear':'Дым рассеялся',
    'appearance':'Новый сигнал пострадавшего', 'agent_failure':'Отказ эвакуатора',
}

class TerrainSnapshot:
    """Immutable-in-use terrain at one event epoch; route cache local to epoch."""
    def __init__(self, grid, hazard, smoke, epoch):
        self.grid=grid;self.hazard=hazard;self.smoke=smoke
        self.epoch=epoch;self.route_cache={};self.base_tree=None
    def walkable(self,x,y):
        return 0<=y<len(self.grid) and 0<=x<len(self.grid) and self.grid[y][x] not in (1,3) and self.hazard[y][x] not in ('fire','collapse','flood')
    def cost(self,x,y):
        val=1.45 if self.grid[y][x]==2 else 1.0
        if self.hazard[y][x]=='mud':val*=2.1
        if self.hazard[y][x]=='road_damage':val*=1.75
        return val
    def visibility(self,x,y):
        return .30 if self.smoke[y][x] else 1.0


@dataclass(frozen=True)
class Person:
    id: int
    x: int
    y: int
    priority: int
    sector: int

SCENARIOS = {
    'open':'S1 · Открытая местность',
    'urban':'S2 · Разрушенный город',
    'clusters':'S3 · Скопления людей',
    'scarce':'S4 · Энергозатратный рельеф',
    'uncertain':'S5 · Неполная информация',
    'dynamic':'S6 · Отказ робота',
}

class World:
    def __init__(self, seed=2026, n_people=16, scenario='urban',
                 grid_size=25, n_scouts=3, n_rescuers=4, probabilities=None):
        if scenario not in SCENARIOS: raise ValueError('Unknown scenario preset')
        if grid_size not in (25, 35, 45, 55, 65, 75, 100, 125, 150): raise ValueError('Размер карты: 25, 35, 45, 55, 65, 75, 100, 125, 150')
        if not 1 <= n_scouts <= 48: raise ValueError('Количество дронов должно быть 1..48')
        if not 1 <= n_rescuers <= 40: raise ValueError('Количество эвакуаторов должно быть 1..40')
        if not 3 <= n_people <= 600: raise ValueError('Количество пострадавших должно быть 3..600')
        self.scenario, self.seed = scenario, int(seed)
        self.grid_size = grid_size
        self.sector_size = SECTOR_W
        self.sector_count = grid_size // SECTOR_W
        self.n_scouts, self.n_rescuers = int(n_scouts), int(n_rescuers)
        self.initial_people = int(n_people)
        self.n_people = int(n_people)
        probabilities = {k:0 for k in DEFAULT_PROBABILITIES} if probabilities is None else probabilities
        self.probabilities = {k: int(probabilities.get(k, 0)) for k in DEFAULT_PROBABILITIES}
        if any(not 0<=v<=100 for v in self.probabilities.values()):
            raise ValueError('Вероятности событий должны быть от 0 до 100%')
        self.horizon = round(HORIZON * (grid_size / GRID))
        scale = grid_size / GRID
        self.scout_battery = SCOUT_BATTERY * scale  # reference only; not a limit
        self.ground_battery = GROUND_BATTERY * scale  # reference only; not a limit
        self.sensor_reliability = .83 if scenario == 'uncertain' else 1.0
        self.events = ([{'t':round(95*scale,1),'type':'agent_failure',
                         'robot':min(1,self.n_rescuers-1)}] if scenario == 'dynamic' else [])
        rnd = random.Random(self.seed)
        n = grid_size
        mid = n // 2
        self.grid = [[0 for _ in range(n)] for _ in range(n)]
        for y in range(n):
            for x in range(n):
                if x <= 2 or y <= 2 or x == mid or y == mid: continue
                q = rnd.random()
                if scenario == 'open':
                    self.grid[y][x] = 1 if q < .025 else 3 if q < .035 else 2 if q < .105 else 0
                else:
                    self.grid[y][x] = 1 if q < .105 else 3 if q < .125 else 2 if q < .32 else 0
        if scenario != 'open':
            # Four blocks that scale with world size, preserving midline corridors.
            centers=[(.25,.33),(.72,.25),(.72,.74)]
            radius=max(1,n//25)
            for fx,fy in centers:
                cx,cy=int(fx*n),int(fy*n)
                for y in range(cy-radius,cy+radius+1):
                    for x in range(cx-radius,cx+radius+1):
                        if 3<=x<n-1 and 3<=y<n-1 and x!=mid and y!=mid:
                            if rnd.random()<.77:self.grid[y][x]=1
        sc = self.sector_count
        self.prior=[]
        for sy in range(sc):
            for sx in range(sc):
                cells=[self.grid[y][x] for y in range(sy*SECTOR_W,(sy+1)*SECTOR_W)
                       for x in range(sx*SECTOR_W,(sx+1)*SECTOR_W)]
                rubble=sum(c in (1,2) for c in cells)
                distance=math.hypot(sx-(sc-1)/2,sy-(sc-1)/2)
                self.prior.append(round(.55+rubble*.065+max(0,3-distance)*.065,3))
        weighted=[p**1.7 for p in self.prior]
        if scenario=='clusters':
            hotspots=rnd.sample(range(sc*sc),2)
            weighted=[0.12+sum(7.0*math.exp(-((s%sc-h%sc)**2+
                      (s//sc-h//sc)**2)/1.1) for h in hotspots)
                      for s in range(sc*sc)]
        if scenario=='uncertain':
            weighted=[.4+rnd.random()*2.2 for _ in weighted]
        if scenario=='scarce':
            self.grid=[[2 if cell==0 and random.Random(self.seed*97+x*13+y*17).random()<.45 else cell
                        for x,cell in enumerate(row)] for y,row in enumerate(self.grid)]
        self.people=[]
        used=set()
        attempts=0
        while len(self.people)<self.n_people and attempts<30000:
            attempts+=1
            sec=rnd.choices(range(sc*sc),weights=weighted,k=1)[0]
            sx,sy=sec%sc,sec//sc
            x=rnd.randrange(sx*SECTOR_W,(sx+1)*SECTOR_W)
            y=rnd.randrange(sy*SECTOR_W,(sy+1)*SECTOR_W)
            if (x,y) in used or self.grid[y][x] in (1,3) or (x<3 and y<3):continue
            used.add((x,y))
            self.people.append(Person(len(self.people)+1,x,y,rnd.choices([1,2,3],[.63,.27,.1])[0],sec))
        if len(self.people)<self.n_people:raise RuntimeError('Unable to place targets')
        self._route_cache={}
        self._active_terrain_route_epoch=None
        self.landscape_events=[]
        self.appearances=[]
        self._terrain_snapshots={}
        self._init_dynamic_events()

    def _init_dynamic_events(self):
        """Single method-independent event tape. All five algorithms see identical disturbances.
        No controller receives this tape: it is ground truth for the replay runner.
        """
        rng=random.Random(self.seed*9973+5103)
        n=self.grid_size
        windows=range(1,max(2,int(self.horizon//80)))
        used={(p.x,p.y) for p in self.people}
        extras=[]
        uid=self.initial_people+1
        for window in windows:
            t0=window*80
            for kind in self.probabilities:
                if rng.random()>=self.probabilities[kind]/100:continue
                t=round(min(self.horizon-3,t0+rng.uniform(-23,23)),2)
                if kind=='appearance':
                    for _ in range(180):
                        x=rng.randrange(3,n-2);y=rng.randrange(3,n-2)
                        if (x,y) not in used and self.grid[y][x] not in (1,3):break
                    else:continue
                    used.add((x,y));sec=(y//SECTOR_W)*self.sector_count+x//SECTOR_W
                    p=Person(uid,x,y,rng.choices([1,2,3],[.6,.3,.1])[0],sec)
                    uid+=1; extras.append(p)
                    cause=rng.choice(['Стук из-под завалов','Звук / голос','Сдвиг обломков','Самостоятельный выход'])
                    self.appearances.append({'t':t,'type':'appearance','id':p.id,'sector':sec,'cause':cause})
                    continue
                for _ in range(120):
                    cx=rng.randrange(3,n-2);cy=rng.randrange(3,n-2)
                    if (cx<4 and cy<4):continue
                    if kind=='road_damage' and self.grid[cy][cx] not in (0,2):continue
                    if kind in ('flood','mud') and self.grid[cy][cx] in (1,3):continue
                    break
                radius=1 if kind in ('collapse','road_damage','mud') else 2
                cells=[]
                for dy in range(-radius,radius+1):
                    for dx in range(-radius,radius+1):
                        x,y=cx+dx,cy+dy
                        if not (3<=x<n-1 and 3<=y<n-1) or (x<5 and y<5):continue
                        if kind not in ('smoke','fire') and self.grid[y][x] in (1,3):continue
                        if dx*dx+dy*dy <= radius*radius+1 and rng.random()<.84:
                            cells.append([x,y])
                if not cells:continue
                self.landscape_events.append({'t':t,'type':kind,'cells':cells})
                if kind in ('fire','flood'):
                    spread=[]
                    for dx,dy in ((-1,0),(1,0),(0,1),(0,-1),(2,0),(0,2)):
                        x,y=cx+dx*rng.randint(1,2),cy+dy*rng.randint(1,2)
                        if 4<=x<n-1 and 4<=y<n-1:spread.append([x,y])
                    if spread:self.landscape_events.append({'t':round(min(self.horizon-1,t+38),2),
                                                             'type':kind,'cells':spread,'spread':True})
                if kind=='smoke':
                    self.landscape_events.append({'t':round(min(self.horizon-1,t+72),2),
                                                  'type':'smoke_clear','cells':cells})
        self.people.extend(extras)
        self.n_people=len(self.people)
        self.landscape_events.sort(key=lambda e:(e['t'],e['type']))
        self.appearances.sort(key=lambda e:e['t'])
        self.dynamic_events=sorted(self.landscape_events+self.appearances,
                                   key=lambda e:(e['t'],e['type']))
        self._terrain_times=[e['t'] for e in self.landscape_events]
        self._appear_time={e['id']:e['t'] for e in self.appearances}

    def person_active(self,person,t):
        return t+1e-7>=self._appear_time.get(person.id,0.0)

    def sector_visibility(self,sector,t):
        """Conservative sensor quality when any smoke intersects the sector."""
        snap=self.terrain_at(t)
        sx=(sector%self.sector_count)*SECTOR_W
        sy=(sector//self.sector_count)*SECTOR_W
        smoked=sum(bool(snap.smoke[y][x]) for y in range(sy,sy+SECTOR_W)
                   for x in range(sx,sx+SECTOR_W))
        if smoked>=4:return 0.38
        if smoked:return 0.56
        return 1.0

    def terrain_at(self,t):
        epoch=bisect.bisect_right(self._terrain_times,t+1e-8)
        if epoch in self._terrain_snapshots:return self._terrain_snapshots[epoch]
        n=self.grid_size
        grid=self.grid  # unchanged base grid
        hazard=[[None]*n for _ in range(n)]
        smoke=[[False]*n for _ in range(n)]
        for ev in self.landscape_events[:epoch]:
            for x,y in ev['cells']:
                if ev['type']=='smoke':smoke[y][x]=True
                elif ev['type']=='smoke_clear':smoke[y][x]=False
                else:hazard[y][x]=ev['type']
        snap=TerrainSnapshot(grid,hazard,smoke,epoch)
        self._terrain_snapshots[epoch]=snap
        return snap

    def scout_speed(self,r):return SCOUT_SPEED[r%len(SCOUT_SPEED)]
    def ground_speed(self,r):return GROUND_SPEED[r%len(GROUND_SPEED)]
    def ground_energy_factor(self,r):
        # Deterministic heterogeneous motor efficiencies. The same physics
        # applies to all three competitors; batteries remain unlimited.
        return (0.82,1.06,1.20,0.94)[r%4]
    def center(self,sector):
        return (sector%self.sector_count*SECTOR_W+(SECTOR_W-1)/2,
                sector//self.sector_count*SECTOR_W+(SECTOR_W-1)/2)
    def tile_penalty(self,x,y,terrain=None):
        return terrain.cost(x,y) if terrain is not None else (1.45 if self.grid[y][x]==2 else 1.0)
    def walkable(self,x,y,terrain=None):
        if terrain is not None:return terrain.walkable(x,y)
        return 0<=x<self.grid_size and 0<=y<self.grid_size and self.grid[y][x] not in (1,3)
    def route(self,start,finish,terrain=None):
        a=(int(round(start[0])),int(round(start[1])))
        b=(int(round(finish[0])),int(round(finish[1])))
        key=(a,b)
        # Only one terrain epoch's geometry cache is needed during an ordered
        # simulation. Releasing prior epochs avoids multi-GB memory usage at 150².
        if terrain is not None and terrain.epoch!=self._active_terrain_route_epoch:
            old=self._terrain_snapshots.get(self._active_terrain_route_epoch)
            if old is not None:
                old.route_cache.clear();old.base_tree=None
            self._active_terrain_route_epoch=terrain.epoch
        cache=terrain.route_cache if terrain is not None else self._route_cache
        if key in cache:return cache[key]
        if not self.walkable(*a,terrain) or not self.walkable(*b,terrain):return ([],float('inf'))
        # A single source shortest-path tree per terrain epoch avoids repeating
        # 40 full A* searches for each victim on 150x150 maps.
        base=(int(BASE[0]),int(BASE[1]))
        if (a==base or b==base) and terrain is not None:
            if terrain.base_tree is None:
                pq=[(0.0,base)];dmap={base:0.};parent={}
                while pq:
                    g,node=heapq.heappop(pq)
                    if g>dmap[node]+1e-8:continue
                    x,y=node
                    for nx,ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                        if not self.walkable(nx,ny,terrain):continue
                        ng=g+(self.tile_penalty(x,y,terrain)+self.tile_penalty(nx,ny,terrain))/2
                        if ng<dmap.get((nx,ny),float('inf'))-1e-9:
                            dmap[nx,ny]=ng;parent[nx,ny]=node;heapq.heappush(pq,(ng,(nx,ny)))
                terrain.base_tree=(dmap,parent)
            dmap,parent=terrain.base_tree
            dest=b if a==base else a
            if dest not in dmap:return ([],float('inf'))
            out=[];cur=dest
            while cur!=base:
                out.append((float(cur[0]),float(cur[1])));cur=parent[cur]
            out.append((float(base[0]),float(base[1])))
            if a==base:out.reverse()
            result=(out,round(dmap[dest],5));cache[key]=result
            return result
        pq=[(abs(a[0]-b[0])+abs(a[1]-b[1]),0.0,a)]
        dist={a:0.0};prev={}
        while pq:
            _,g,node=heapq.heappop(pq)
            if g>dist[node]+1e-8:continue
            if node==b:break
            x,y=node
            for nx,ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                if not self.walkable(nx,ny,terrain):continue
                step=(self.tile_penalty(x,y,terrain)+self.tile_penalty(nx,ny,terrain))/2
                ng=g+step
                if ng<dist.get((nx,ny),float('inf'))-1e-9:
                    dist[(nx,ny)]=ng;prev[(nx,ny)]=node
                    h=abs(nx-b[0])+abs(ny-b[1])
                    heapq.heappush(pq,(ng+h,ng,(nx,ny)))
        if b not in dist:return ([],float('inf'))
        path=[];cur=b
        while cur!=a:path.append(cur);cur=prev[cur]
        path.append(a);path.reverse()
        out=([(float(x),float(y)) for x,y in path],round(dist[b],5))
        cache[key]=out
        return out

    def public_map(self):
        return {'width':self.grid_size,'height':self.grid_size,'cell_metres':CELL_METRES,
                'grid':self.grid,'sector_size':SECTOR_W,'sector_count':self.sector_count,
                'prior':self.prior,'base':list(BASE),'n_people':self.n_people,'initial_people':self.initial_people,
                'seed':self.seed,'scenario_type':self.scenario,
                'scenario_label':SCENARIOS[self.scenario],
                'scout_battery_Wh':self.scout_battery,'ground_battery_Wh':self.ground_battery,
                'energy_unlimited':True,
                'sensor_reliability':self.sensor_reliability,'events':self.events,
                'scouts':self.n_scouts,'rescuers':self.n_rescuers,'horizon':self.horizon,
                'probabilities':self.probabilities,
                'environment_events':self.dynamic_events,
                'event_counts':{k:sum(e['type']==k for e in self.dynamic_events) for k in DEFAULT_PROBABILITIES}}
