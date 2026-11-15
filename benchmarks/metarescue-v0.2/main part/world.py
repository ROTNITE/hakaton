"""Deterministic hidden-target rescue world with configurable map and fleet size.
Coordinates are continuous cell units; one cell equals CELL_METRES meters.
No planner may access World.people before a target is detected.
"""
from __future__ import annotations
from dataclasses import dataclass
import heapq, math, random

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
    'scarce':'S4 · Мало энергии',
    'uncertain':'S5 · Неполная информация',
    'dynamic':'S6 · Отказ робота',
}

class World:
    def __init__(self, seed=2026, n_people=16, scenario='urban',
                 grid_size=25, n_scouts=3, n_rescuers=4):
        if scenario not in SCENARIOS: raise ValueError('Unknown scenario preset')
        if grid_size not in (25, 35, 45, 55, 65): raise ValueError('Размер карты должен быть 25, 35, 45, 55 или 65')
        if not 1 <= n_scouts <= 10: raise ValueError('Количество дронов должно быть 1..10')
        if not 1 <= n_rescuers <= 12: raise ValueError('Количество эвакуаторов должно быть 1..12')
        if not 3 <= n_people <= 80: raise ValueError('Количество пострадавших должно быть 3..80')
        self.scenario, self.seed = scenario, int(seed)
        self.grid_size = grid_size
        self.sector_size = SECTOR_W
        self.sector_count = grid_size // SECTOR_W
        self.n_scouts, self.n_rescuers = int(n_scouts), int(n_rescuers)
        self.n_people = int(n_people)
        self.horizon = round(HORIZON * (grid_size / GRID))
        scale = grid_size / GRID
        self.scout_battery = (36.0 if scenario == 'scarce' else SCOUT_BATTERY) * scale
        self.ground_battery = (135.0 if scenario == 'scarce' else GROUND_BATTERY) * scale
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

    def scout_speed(self,r):return SCOUT_SPEED[r%len(SCOUT_SPEED)]
    def ground_speed(self,r):return GROUND_SPEED[r%len(GROUND_SPEED)]
    def center(self,sector):
        return (sector%self.sector_count*SECTOR_W+(SECTOR_W-1)/2,
                sector//self.sector_count*SECTOR_W+(SECTOR_W-1)/2)
    def tile_penalty(self,x,y):return 1.45 if self.grid[y][x]==2 else 1.0
    def walkable(self,x,y):
        return 0<=x<self.grid_size and 0<=y<self.grid_size and self.grid[y][x] not in (1,3)
    def route(self,start,finish):
        a=(int(round(start[0])),int(round(start[1])))
        b=(int(round(finish[0])),int(round(finish[1])))
        key=(a,b)
        if key in self._route_cache:return self._route_cache[key]
        if not self.walkable(*a) or not self.walkable(*b):return ([],float('inf'))
        pq=[(abs(a[0]-b[0])+abs(a[1]-b[1]),0.0,a)]
        dist={a:0.0};prev={}
        while pq:
            _,g,node=heapq.heappop(pq)
            if g>dist[node]+1e-8:continue
            if node==b:break
            x,y=node
            for nx,ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                if not self.walkable(nx,ny):continue
                step=(self.tile_penalty(x,y)+self.tile_penalty(nx,ny))/2
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
        self._route_cache[key]=out
        return out

    def public_map(self):
        return {'width':self.grid_size,'height':self.grid_size,'cell_metres':CELL_METRES,
                'grid':self.grid,'sector_size':SECTOR_W,'sector_count':self.sector_count,
                'prior':self.prior,'base':list(BASE),'n_people':self.n_people,
                'seed':self.seed,'scenario_type':self.scenario,
                'scenario_label':SCENARIOS[self.scenario],
                'scout_battery_Wh':self.scout_battery,'ground_battery_Wh':self.ground_battery,
                'sensor_reliability':self.sensor_reliability,'events':self.events,
                'scouts':self.n_scouts,'rescuers':self.n_rescuers,'horizon':self.horizon}
