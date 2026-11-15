"""Seeded 2D terrain, time-indexed disturbances and A* for MetaRescue v0.3.

World is complete simulator truth. Planning receives only currently observed
terrain and discovered people via Simulation, not a future-event lookahead.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import heapq
from collections import deque
import math
import random

TERRAIN = {'ground':0, 'obstacle':1, 'rough':2, 'water':3,
           'mud':4,'road_damage':5,'fire':6,'flood':7,'collapse':8}
BLOCKED = {1,3,6,7,8}
TERRAIN_WEIGHTS = {0:1.0, 1:float('inf'), 2:1.55, 3:float('inf'),
                   4:2.25, 5:1.90, 6:float('inf'), 7:float('inf'), 8:float('inf')}
EVENT_LABELS = {
    'collapse':'Обрушение', 'fire':'Пожар', 'flood':'Затопление',
    'mud':'Грязь', 'road_damage':'Повреждение дороги', 'smoke':'Дым',
    'low_visibility':'Плохая видимость', 'new_target':'Новый пострадавший',
}
DEFAULT_PROB = {'collapse':12,'fire':12,'flood':10,'mud':14,
                'road_damage':14,'smoke':15,'low_visibility':12,'new_target':20}
SCENARIOS = {'open':'S1 · Открытая местность', 'urban':'S2 · Разрушенный город',
             'clusters':'S3 · Скопления людей','scarce':'S4 · Мало энергии',
             'uncertain':'S5 · Неполные наблюдения','dynamic':'S6 · Отказ эвакуатора'}
BASE = (1,1)
WINDOW = 30   # Bernoulli probability is applied once per event type per 30 seconds


def stable_unit(*parts):
    raw=':'.join(map(str,parts)).encode()
    return int.from_bytes(hashlib.blake2b(raw,digest_size=8).digest(),'big')/2**64


@dataclass(frozen=True)
class Person:
    id:int
    x:int
    y:int
    sector:int
    priority:int
    appeared_at:float = 0.0
    created_by_event:bool = False

    def public(self):
        return {'id':self.id,'x':self.x,'y':self.y,'sector':self.sector,
                'priority':self.priority,'appeared_at':self.appeared_at,
                'new':self.created_by_event}


class World:
    def __init__(self,seed=2026,people=16,scenario='urban',map_size=25,
                 scouts=3,rescuers=4,probabilities=None):
        if scenario not in SCENARIOS: raise ValueError('Unknown scenario')
        if map_size not in (25,35,45,55,65): raise ValueError('Размер карты: 25, 35, 45, 55, 65')
        if not 1<=scouts<=10 or not 1<=rescuers<=12: raise ValueError('Размер роя: дроны 1–10, эвакуаторы 1–12')
        if not 3<=people<=80: raise ValueError('Пострадавшие: 3–80')
        self.seed=int(seed);self.initial_people=int(people);self.scenario=scenario
        self.size=int(map_size);self.sectors_per_side=self.size//5
        self.scouts=int(scouts);self.rescuers=int(rescuers)
        self.horizon=round(480*self.size/25)
        self.scout_battery=(38 if scenario=='scarce' else 125)*self.size/25
        self.rescuer_battery=(135 if scenario=='scarce' else 240)*self.size/25
        self.sensor_reliability=.83 if scenario=='uncertain' else .99
        self.probabilities=dict(DEFAULT_PROB)
        for key,value in (probabilities or {}).items():
            if key not in DEFAULT_PROB: raise ValueError('Неизвестное событие '+str(key))
            if not 0<=float(value)<=100: raise ValueError('Вероятность должна быть 0–100%')
            self.probabilities[key]=float(value)
        rnd=random.Random(self.seed)
        n=self.size; mid=n//2
        self.grid=[[0 for _ in range(n)] for _ in range(n)]
        for y in range(n):
            for x in range(n):
                if x<=2 or y<=2 or x==mid or y==mid: continue
                u=rnd.random()
                if scenario=='open':
                    self.grid[y][x]=1 if u<.025 else 3 if u<.036 else 2 if u<.09 else 0
                else:
                    self.grid[y][x]=1 if u<.10 else 3 if u<.12 else 2 if u<.30 else 0
        if scenario!='open':
            for a,b in ((.25,.33),(.72,.25),(.72,.74)):
                cx,cy=int(a*n),int(b*n); radius=max(1,n//25)
                for y in range(cy-radius,cy+radius+1):
                    for x in range(cx-radius,cx+radius+1):
                        if 3<=x<n-1 and 3<=y<n-1 and x!=mid and y!=mid and rnd.random()<.72:
                            self.grid[y][x]=1
        k=self.sectors_per_side
        self.prior=[]
        for sy in range(k):
            for sx in range(k):
                cell=[self.grid[y][x] for y in range(sy*5,sy*5+5)
                      for x in range(sx*5,sx*5+5)]
                self.prior.append(round(.5+.1*sum(v in (1,2) for v in cell),3))
        weighted=[max(.05,p)**1.4 for p in self.prior]
        if scenario=='clusters':
            hotspots=rnd.sample(range(k*k),2)
            weighted=[.07+sum(8*math.exp(-((i%k-h%k)**2+(i//k-h//k)**2)/1.35)
                              for h in hotspots) for i in range(k*k)]
        elif scenario=='uncertain':
            weighted=[.5+rnd.random()*2 for _ in weighted]
        self.people=[]; used=set(); attempts=0
        while len(self.people)<people and attempts<30000:
            attempts+=1; sec=rnd.choices(range(k*k),weights=weighted)[0]
            x=rnd.randrange((sec%k)*5,(sec%k)*5+5)
            y=rnd.randrange((sec//k)*5,(sec//k)*5+5)
            if (x,y) in used or self.grid[y][x] in BLOCKED or x<=2 and y<=2:continue
            used.add((x,y))
            self.people.append(Person(len(self.people)+1,x,y,sec,rnd.choices([1,2,3],[.65,.25,.1])[0]))
        if len(self.people)!=people:raise RuntimeError('Не удалось разместить людей')
        self.events=[]
        self._generate_events()

    def sector_center(self,sec):
        return (sec%self.sectors_per_side*5+2,sec//self.sectors_per_side*5+2)

    def sector(self,x,y):
        return int(y)//5*self.sectors_per_side+int(x)//5

    def _generate_events(self):
        n=self.size; rng=random.Random(self.seed+982451653)
        used={(p.x,p.y) for p in self.people}
        eid=0
        for t in range(WINDOW,self.horizon,WINDOW):
            for kind,p in self.probabilities.items():
                if rng.random()*100>=p:continue
                # Events have independent seed and own trajectory, identically for all policies.
                x,y=rng.randrange(4,n-2),rng.randrange(4,n-2)
                if kind=='new_target':
                    choices=[]
                    for _ in range(80):
                        px,py=rng.randrange(4,n-1),rng.randrange(4,n-1)
                        if (px,py) not in used and self.grid[py][px] not in BLOCKED:choices.append((px,py))
                    if not choices:continue
                    px,py=choices[0];used.add((px,py))
                    pid=len(self.people)+1
                    self.people.append(Person(pid,px,py,self.sector(px,py),
                                              rng.choice((1,2,3)),float(t),True))
                    cells=[];section=self.sector(px,py)
                else:
                    radius=rng.choice((1,1,2))
                    cells=[]
                    for yy in range(max(3,y-radius),min(n-1,y+radius+1)):
                        for xx in range(max(3,x-radius),min(n-1,x+radius+1)):
                            if rng.random()<(.84 if radius==1 else .64):
                                if kind=='road_damage' and self.grid[yy][xx] in BLOCKED:continue
                                if kind in ('mud','fire','flood','collapse') and (xx,yy)==BASE:continue
                                cells.append([xx,yy])
                    if not cells:continue
                    section=self.sector(x,y);pid=None
                eid+=1
                event_id=f'E{eid:04d}'
                self.events.append({'id':event_id,'t':float(t),'type':kind,
                                    'label':EVENT_LABELS[kind],'cells':cells,
                                    'sector':section,'person_id':pid,
                                    'source':'seeded_environment','confidence':1.0})
                if kind in ('fire','flood'):
                    # Once ignited, this event can spread to adjacent cells during
                    # the next two windows. The configured probability controls
                    # ignition; spreading is a documented conditional process.
                    frontier=[list(v) for v in cells]
                    for i in (1,2):
                        when=t+i*WINDOW
                        if when>=self.horizon or not frontier or rng.random()>.72:break
                        growth=[]
                        for cx,cy in rng.sample(frontier,min(3,len(frontier))):
                            for nx,ny in ((cx+1,cy),(cx-1,cy),(cx,cy+1),(cx,cy-1)):
                                if 3<=nx<n-1 and 3<=ny<n-1 and (nx,ny)!=BASE and rng.random()<.65:
                                    growth.append([nx,ny])
                        if not growth:break
                        frontier=growth
                        eid+=1
                        self.events.append({'id':f'E{eid:04d}','t':float(when),
                          'type':kind,'label':'Распространение: '+EVENT_LABELS[kind],
                          'cells':growth,'sector':self.sector(growth[0][0],growth[0][1]),
                          'person_id':None,'source':'propagation','parent_id':event_id,
                          'confidence':1.0})
        if self.scenario=='dynamic':
            self.events.append({'id':'E_FAIL','t':95*self.size/25,'type':'agent_failure',
                                'label':'Отказ эвакуатора','robot':min(1,self.rescuers-1),
                                'cells':[],'sector':None,'person_id':None,
                                'source':'seeded_environment','confidence':1.0})
        self.events.sort(key=lambda e:(e['t'],e['id']))

    def public_map(self):
        return {'width':self.size,'height':self.size,'grid':self.grid,'prior':self.prior,
                'sector_size':5,'sector_count':self.sectors_per_side,
                'base':list(BASE),'n_people':len(self.people),'initial_people':self.initial_people,
                'seed':self.seed,'scenario_type':self.scenario,
                'scenario_label':SCENARIOS[self.scenario],
                'horizon':self.horizon,'scouts':self.scouts,'rescuers':self.rescuers,
                'scout_battery_Wh':self.scout_battery,'ground_battery_Wh':self.rescuer_battery,
                'probabilities':self.probabilities,'event_interval':WINDOW,
                'events':[dict(e) for e in self.events]}


class TerrainState:
    """Mutable state owned by a single algorithm run: no crosstalk.
    Dynamic changes are only applied when due. A* cache invalidated on changes.
    """
    def __init__(self,world):
        self.world=world
        self.grid=[row[:] for row in world.grid]
        self.smoke={};self.fog={};self.version=0;self.index=0
        self.routes={}
        self._components=None
        self.time=0.0

    def update(self,time):
        self.time=time
        done=[]
        while self.index<len(self.world.events) and self.world.events[self.index]['t']<=time+1e-9:
            ev=self.world.events[self.index];self.index+=1;done.append(ev)
            kind=ev['type']
            code={'collapse':8,'fire':6,'flood':7,'mud':4,'road_damage':5}.get(kind)
            for x,y in ev['cells']:
                if code is not None:
                    # Maintain base and originally solid structural obstacles.
                    if (x,y)==BASE or self.world.grid[y][x] in (1,3):continue
                    # Mud/damaged roads cannot reopen an existing hazard.
                    if code in (4,5) and self.grid[y][x] in BLOCKED:continue
                    self.grid[y][x]=code
                    if kind=='fire':
                        for ax,ay in ((x,y),(x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                            if 0<=ax<self.world.size and 0<=ay<self.world.size:
                                self.smoke[(ax,ay)]=max(self.smoke.get((ax,ay),0),ev['t']+70)
                elif kind=='smoke':self.smoke[(x,y)]=max(self.smoke.get((x,y),0),ev['t']+90)
                elif kind=='low_visibility':self.fog[(x,y)]=max(self.fog.get((x,y),0),ev['t']+100)
            if code is not None:self.version+=1;self.routes.clear();self._components=None
        return done

    def ground_ok(self,x,y):
        return 0<=x<self.world.size and 0<=y<self.world.size and self.grid[y][x] not in BLOCKED

    def weight(self,x,y):return TERRAIN_WEIGHTS[self.grid[y][x]]

    def visibility(self,x,y):
        # sensor quality in each cell: product of independent weather effects
        vis=1.0
        if self.smoke.get((int(x),int(y)),0)>self.time:vis*=.52
        if self.fog.get((int(x),int(y)),0)>self.time:vis*=.62
        return vis

    def sector_visibility(self,sec):
        xx,yy=self.world.sector_center(sec)
        vals=[self.visibility(x,y) for y in range(yy-2,yy+3)
              for x in range(xx-2,xx+3)]
        return sum(vals)/len(vals)

    def connected_components(self):
        if self._components is not None:return self._components
        k=0;component={}
        for y in range(self.world.size):
            for x in range(self.world.size):
                if (x,y) in component or not self.ground_ok(x,y):continue
                k+=1;component[(x,y)]=k;queue=deque([(x,y)])
                while queue:
                    ax,ay=queue.popleft()
                    for nx,ny in ((ax+1,ay),(ax-1,ay),(ax,ay+1),(ax,ay-1)):
                        if (nx,ny) not in component and self.ground_ok(nx,ny):
                            component[(nx,ny)]=k;queue.append((nx,ny))
        self._components=component
        return component

    def route(self,start,end):
        a=(int(round(start[0])),int(round(start[1])))
        b=(int(round(end[0])),int(round(end[1])))
        key=(a,b,self.version)
        if key in self.routes:return self.routes[key]
        if not self.ground_ok(*a) or not self.ground_ok(*b):return ([],float('inf'))
        component=self.connected_components()
        if component[a]!=component[b]:return ([],float('inf'))
        heap=[(abs(a[0]-b[0])+abs(a[1]-b[1]),0.0,a)]
        dist={a:0.0};prev={}
        while heap:
            _,cost,u=heapq.heappop(heap)
            if cost>dist[u]+1e-8:continue
            if u==b:break
            x,y=u
            for nx,ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                if not self.ground_ok(nx,ny):continue
                ng=cost+(self.weight(x,y)+self.weight(nx,ny))/2
                if ng+1e-8<dist.get((nx,ny),float('inf')):
                    dist[(nx,ny)]=ng;prev[(nx,ny)]=u
                    h=abs(nx-b[0])+abs(ny-b[1])
                    heapq.heappush(heap,(ng+h,ng,(nx,ny)))
        if b not in dist:return ([],float('inf'))
        path=[];cur=b
        while cur!=a:path.append(list(cur));cur=prev[cur]
        path.append(list(a));path.reverse()
        out=(path,round(dist[b],5))
        self.routes[key]=out
        self.routes[(b,a,self.version)]=([pt[:] for pt in reversed(path)],out[1])
        return out
