"""Event-driven, multi-agent, reproducible search/rescue simulation.

All five strategies share this execution model, true event schedule and
hard movement/energy checks. Controllers only see discovered people.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import replace
import math
import time
from world import BASE, TerrainState, stable_unit
from optimizer import allocate_rescue, scout_choices, euclidean

MISSION_METHODS=[
  ('greedy_greedy','Greedy + Greedy','greedy','greedy'),
  ('frontier_local','Frontier + Local Search','frontier','local'),
  ('nsga2_greedy','Scout NSGA-II + Greedy','nsga2','greedy'),
  ('greedy_nsga2','Greedy + Rescue NSGA-II','greedy','nsga2'),
  ('nsga2_nsga2','NSGA-II + NSGA-II','nsga2','nsga2'),
]
SCOUT_METHODS=[('random','Random'),('sweep','Sweep'),('greedy','Greedy'),
               ('frontier','Frontier'),('nsga2','Scout NSGA-II')]
RESCUE_METHODS=[('nearest','Nearest'),('greedy','Greedy'),
                ('local','Local Search'),('nsga2','Rescue NSGA-II')]


def path_pos(path,frac):
    if not path:return [float(BASE[0]),float(BASE[1])]
    if len(path)==1:return [float(path[0][0]),float(path[0][1])]
    frac=max(0.0,min(1.0,frac))
    lengths=[euclidean(a,b) for a,b in zip(path,path[1:])]
    total=sum(lengths)
    if total<=1e-10:return list(path[-1])
    remaining=total*frac
    for i,dist in enumerate(lengths):
        if remaining<=dist or i==len(lengths)-1:
            f=0 if dist==0 else min(1,remaining/dist)
            return [round(path[i][0]+f*(path[i+1][0]-path[i][0]),5),
                    round(path[i][1]+f*(path[i+1][1]-path[i][1]),5)]
        remaining-=dist
    return list(path[-1])


def clipped_path(path,frac):
    if not path:return []
    if frac>=1:return path
    if frac<=0:return [path[0][:]]
    lengths=[euclidean(a,b) for a,b in zip(path,path[1:])]
    remaining=sum(lengths)*frac
    out=[list(path[0])]
    for i,d in enumerate(lengths):
        if remaining>=d-1e-8:
            out.append(list(path[i+1]));remaining-=d
        else:
            f=remaining/d if d>0 else 0
            out.append([round(path[i][0]+f*(path[i+1][0]-path[i][0]),5),
                        round(path[i][1]+f*(path[i+1][1]-path[i][1]),5)])
            break
    return out


class Simulation:
    def __init__(self,world,mode='mission',method='nsga2_nsga2',label=None):
        if mode not in ('scout','rescue','mission'):raise ValueError('Unknown mode')
        self.world=world;self.mode=mode;self.method=method;self.label=label or method
        self.terrain=TerrainState(world)
        match=next((m for m in MISSION_METHODS if m[0]==method),None)
        self.scout_method=(match[2] if match else method) if mode!='rescue' else None
        self.rescue_method=(match[3] if match else method) if mode!='scout' else None
        self.scouts=[self.new_agent('scout',i,world.scout_battery) for i in range(world.scouts)] if self.scout_method else []
        self.robots=[self.new_agent('rescue',i,world.rescuer_battery) for i in range(world.rescuers)] if self.rescue_method else []
        self.segments=[];self.visits=[];self.discoveries=[];self.rescues=[]
        self.decisions=[];self.replans=[];self.blocked=0;self.incidents=0
        self.covered=set();self.known={};self.rescued=set();self.claimed=set()
        self.sector_claimed=set();self.signals=set();self.signal_wait={};self.signal_attempts=Counter()
        self.computation_ms=0;self.pareto=[]
        self.energy=0.0;self.last_t=0.0;self.next_robot_plan_t=0.0;self.next_scout_plan_t=0.0
        if mode=='rescue':
            for p in world.people:
                if p.appeared_at<=0:
                    self.known[p.id]=p
                    self.discoveries.append({'t':0.0,'id':p.id,'x':p.x,'y':p.y,
                                             'r':-1,'sector':p.sector,'source':'preknown'})

    @staticmethod
    def new_agent(kind,r,battery):
        return {'r':r,'kind':kind,'pos':[float(BASE[0]),float(BASE[1])],
                'battery':battery,'state':'idle','current':None,
                'target':None,'carry':None,'ready_t':0.0,'failed':False,
                'trip_started':None,'trip_energy':0,'plan_version':0}

    def record(self,t,type_,**params):
        self.decisions.append({'t':round(t,2),'type':type_,**params})

    def schedule(self,agent,t,path,duration,energy,action,target=None):
        duration=max(.1,float(duration))
        path=[list(v) for v in path]
        seg={'r':agent['r'],'kind':agent['kind'],'action':action,
             't0':round(t,3),'t1':round(t+duration,3),
             'path':path,'e':round(energy,6),'target':target}
        self.segments.append(seg)
        agent['current']={'t0':t,'t1':t+duration,'path':path,'e':energy,
                          'spent':0.0,'action':action,'target':target,
                          'visual':seg}
        agent['state']=action
        self.last_t=max(self.last_t,min(self.world.horizon,t+duration))

    def advance(self,agent,t):
        s=agent['current']
        if not s:return False
        fraction=max(0.,min(1.,(t-s['t0'])/max(.001,s['t1']-s['t0'])))
        energy=s['e']*fraction
        cost=max(0,energy-s['spent'])
        agent['battery']=max(0,agent['battery']-cost)
        self.energy+=cost
        agent['trip_energy']+=cost
        s['spent']=energy
        agent['pos']=path_pos(s['path'],fraction)
        if t+1e-9>=s['t1']:
            agent['current']=None
            return True
        return False

    def truncate(self,agent,t):
        s=agent['current']
        if not s:return
        frac=max(0,min(1,(t-s['t0'])/max(.001,s['t1']-s['t0'])))
        s['visual']['path']=clipped_path(s['path'],frac)
        s['visual']['t1']=round(t,3)
        s['visual']['e']=round(s['spent'],6)
        agent['current']=None

    def scout_start(self,agent,sec,t,forced=False):
        center=self.world.sector_center(sec)
        distance=euclidean(agent['pos'],center)
        vis=self.terrain.sector_visibility(sec)
        # Fog and smoke reduce speed near target and scanning quality.
        speed=(2.05+.12*(agent['r']%3))*(.75+.25*vis)
        duration=distance/speed
        energy=distance*1.05+3
        reserve=.1*self.world.scout_battery
        return_cost=euclidean(center,BASE)*1.05
        if agent['battery']<energy+return_cost+reserve:
            return False
        agent['target']=sec
        self.sector_claimed.add(sec)
        self.schedule(agent,t,[agent['pos'],list(center)],duration,distance*1.05,'scout_move',sec)
        self.record(t,'scout_assigned',drone=agent['r'],sector=sec,forced=forced)
        return True

    def robot_start(self,robot,pid,t):
        if pid in self.claimed or pid in self.rescued or pid not in self.known:return False
        p=self.known[pid]
        route,cost=self.terrain.route(robot['pos'],(p.x,p.y))
        back,bc=self.terrain.route((p.x,p.y),BASE)
        if not route or not back:return False
        reserve=.10*self.world.rescuer_battery
        energy=(cost+bc)*.92+5
        if robot['battery']<energy+reserve:return False
        robot['trip_started']=t;robot['trip_energy']=0
        robot['target']=pid;self.claimed.add(pid)
        duration=cost/(.60+.045*(robot['r']%4))
        self.schedule(robot,t,route,duration,cost*.92,'to_person',pid)
        self.record(t,'rescue_assigned',robot=robot['r'],person=pid)
        return True

    def robot_leg(self,robot,t,action):
        pid=robot['target']
        if action=='to_person':
            p=self.known[pid];dest=(p.x,p.y)
        else:dest=BASE
        route,cost=self.terrain.route(robot['pos'],dest)
        if not route:
            robot['state']='waiting';robot['ready_t']=t+15
            self.blocked+=1
            self.record(t,'route_blocked',robot=robot['r'],person=pid,leg=action)
            return False
        duration=cost/(.60+.045*(robot['r']%4))
        energy=cost*.92
        if robot['battery']+1e-8<energy:
            # The new route may exceed battery after a disturbance; do not
            # magically move with a depleted pack.
            robot['state']='waiting';robot['ready_t']=t+20
            self.blocked+=1
            self.record(t,'energy_shortage',robot=robot['r'],person=pid,leg=action)
            return False
        self.schedule(robot,t,route,duration,energy,action,pid)
        return True

    def robot_replan(self,robot,t,source):
        if robot['failed'] or robot['state'] not in ('to_person','to_base','waiting'):return
        old_action=robot['state']
        if old_action=='waiting':old_action='to_base' if robot['carry'] else 'to_person'
        if robot['current']:self.truncate(robot,t)
        robot['state']='idle'   # schedule() will set next state
        self.replans.append({'t':round(t,2),'robot':robot['r'],'person':robot['target'],'reason':source})
        self.record(t,'route_replanned',robot=robot['r'],person=robot['target'],reason=source)
        self.robot_leg(robot,t,old_action)

    def on_scout_done(self,scout,t,action):
        sec=scout['target']
        if action=='scout_move':
            self.schedule(scout,t,[scout['pos']],2.8,2.5,'scan',sec)
            return
        if action=='scan':
            self.covered.add(sec)
            self.visits.append({'t':round(t,2),'r':scout['r'],'sector':sec})
            found=0
            for p in self.world.people:
                if p.sector!=sec or p.appeared_at>t or p.id in self.known:continue
                reliability=self.world.sensor_reliability*self.terrain.visibility(p.x,p.y)
                # Repeated observations differ over time, but not by method label.
                draw=stable_unit('sensor',self.world.seed,p.id,int(t//15),sec)
                if draw<=reliability:
                    self.known[p.id]=p;found+=1
                    self.discoveries.append({'t':round(t,2),'id':p.id,'x':p.x,
                        'y':p.y,'r':scout['r'],'sector':sec,'source':'scan',
                        'new':p.created_by_event})
                    self.record(t,'target_detected',person=p.id,drone=scout['r'],sector=sec)
            self.sector_claimed.discard(sec)
            if sec in self.signals:
                if any(p.sector==sec and p.id not in self.known and p.appeared_at<=t for p in self.world.people):
                    self.signal_attempts[sec]+=1
                    self.signal_wait[sec]=t+22
                    if self.signal_attempts[sec]>=3:self.signals.discard(sec)
                else:self.signals.discard(sec)
            scout['state']='idle';scout['target']=None
            return
        if action=='return_scout':
            scout['state']='standby';scout['target']=None

    def on_robot_done(self,robot,t,action):
        pid=robot['target']
        if action=='to_person':
            self.schedule(robot,t,[robot['pos']],5,2.5,'pickup',pid)
        elif action=='pickup':
            robot['carry']=pid
            self.robot_leg(robot,t,'to_base')
        elif action=='to_base':
            self.schedule(robot,t,[robot['pos']],3,2.5,'dropoff',pid)
        elif action=='dropoff':
            # A person counts as rescued ONLY after return to base + dropoff.
            if pid not in self.rescued:
                self.rescued.add(pid)
                self.rescues.append({'t':round(t,2),'id':pid,'r':robot['r'],
                                     'start':round(robot['trip_started'],2),
                                     'e':round(robot['trip_energy'],2),
                                     'new':self.known[pid].created_by_event})
                self.record(t,'target_rescued',robot=robot['r'],person=pid)
            self.claimed.discard(pid)
            robot['target']=None;robot['carry']=None;robot['state']='idle'
            robot['trip_started']=None

    def on_event(self,ev,t):
        kind=ev['type']
        self.record(t,'environment_event',event_id=ev['id'],event_type=kind,
                    affected=len(ev['cells']),sector=ev.get('sector'))
        if kind=='new_target':
            p=next(p for p in self.world.people if p.id==ev['person_id'])
            if self.mode=='rescue':
                # Rescue-only benchmark assumes updated target coordinates are supplied.
                self.known[p.id]=p
                self.discoveries.append({'t':round(t,2),'id':p.id,'x':p.x,'y':p.y,
                                         'r':-1,'sector':p.sector,'source':'preknown_signal','new':True})
            else:
                self.signals.add(p.sector);self.signal_wait[p.sector]=t
                self.record(t,'coarse_signal',sector=p.sector,source='sound_or_debris')
        elif kind=='agent_failure':
            self.next_robot_plan_t=t
            if self.robots:
                robot=self.robots[ev['robot']]
                if robot['current']:self.truncate(robot,t)
                robot['failed']=True;robot['state']='failed'
                if robot['target'] is not None:
                    self.claimed.discard(robot['target'])
                    if robot['carry'] is not None:
                        # Drop passenger at current location, not the original pickup
                        # coordinate. Do not modify World: it is shared by all runs.
                        p=self.known[robot['carry']]
                        x,y=int(round(robot['pos'][0])),int(round(robot['pos'][1]))
                        if not self.terrain.ground_ok(x,y):
                            for ax,ay in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                                if self.terrain.ground_ok(ax,ay):x,y=ax,ay;break
                        self.known[p.id]=replace(p,x=x,y=y,sector=self.world.sector(x,y))
                        self.record(t,'patient_released',person=p.id,x=x,y=y)
                self.record(t,'agent_failed',robot=robot['r'])
        elif kind in ('collapse','fire','flood','mud','road_damage'):
            self.next_robot_plan_t=t
            for robot in self.robots:
                if robot['state'] not in ('to_person','to_base','waiting') or robot['failed']:continue
                active=robot['current']
                nearby=robot['state']=='waiting'
                if active:
                    start_frac=max(0,min(1,(t-active['t0'])/max(.001,active['t1']-active['t0'])))
                    # Inspect remaining legs and nearby cells, not the whole map.
                    route=active['path']
                    start_idx=max(0,int(start_frac*max(0,len(route)-1))-1)
                    path=route[start_idx:]
                    nearby=any(abs(int(x)-int(cx))+abs(int(y)-int(cy))<=1
                               for x,y in ev['cells'] for cx,cy in path)
                if nearby:self.robot_replan(robot,t,kind)
                if kind in ('collapse','fire','flood'):
                    x,y=robot['pos']
                    if any(abs(x-cx)<.6 and abs(y-cy)<.6 for cx,cy in ev['cells']):
                        self.incidents+=1
                        self.record(t,'environment_exposure',robot=robot['r'],event_type=kind)
            # Event effects are shared; inspect newest sector again if newly unsafe/uncertain.
            if self.scout_method and ev['sector'] in self.covered:
                self.signals.add(ev['sector']);self.signal_wait[ev['sector']]=t+3
        elif kind in ('smoke','low_visibility'):
            # Scanning uses updated visibility, including lower detection probability.
            pass

    def dispatch_scouts(self,t):
        idle={a['r']:a for a in self.scouts if a['state'] in ('idle','standby') and not a['failed']}
        if not idle or t<self.next_scout_plan_t:return
        remaining=set(range(self.world.sectors_per_side**2))-self.covered-self.sector_claimed
        requests={s for s in self.signals if s not in self.sector_claimed
                  and t>=self.signal_wait.get(s,0)}
        remaining|=requests
        # Remove sectors where a drone has already failed a battery reserve test.
        if not remaining:
            for a in idle.values():
                if a['state']=='idle':self.scout_retire(a,t)
            return
        # Filter out completely inaccessible sectors for low-energy idle agents by planner.
        plans,pareto,ms=scout_choices(self.world,self.terrain,idle,remaining,
            self.scout_method,self.covered,requests,
            self.world.seed+int(t)*17+len(self.visits))
        self.computation_ms+=ms
        if pareto:self.pareto=pareto
        sent=0
        for r,sec in plans.items():
            if self.scout_start(idle[r],sec,t,forced=sec in requests):sent+=1
        if sent==0:
            # Wait before reconsidering an unaffordable request. A standby
            # scout remains eligible for a later, nearer signal.
            self.next_scout_plan_t=t+15
            for a in idle.values():
                if a['state']=='idle':self.scout_retire(a,t)

    def scout_retire(self,a,t):
        if euclidean(a['pos'],BASE)<.01:
            a['state']='standby';return
        dist=euclidean(a['pos'],BASE)
        if a['battery'] >= dist*1.05:
            self.schedule(a,t,[a['pos'],list(BASE)],dist/(2+.1*(a['r']%3)),
                          dist*1.05,'return_scout',None)
        else:a['state']='grounded'

    def dispatch_robots(self,t):
        idle={a['r']:a for a in self.robots if a['state']=='idle' and not a['failed']}
        available=[p for pid,p in self.known.items() if pid not in self.rescued and pid not in self.claimed]
        if not idle or not available or t+1e-8<self.next_robot_plan_t:return
        robots={r:{'pos':a['pos'],'battery':a['battery'],'time':t} for r,a in idle.items()}
        plans,pareto,ms=allocate_rescue(self.world,self.terrain,available,robots,
             self.rescue_method,self.world.seed+int(t)*23+len(self.rescues))
        self.computation_ms+=ms
        self.next_robot_plan_t=t+(6 if plans else 18)
        if pareto:self.pareto=pareto
        for r,pid in plans.items():self.robot_start(idle[r],pid,t)

    def run(self):
        start=time.perf_counter()
        horizon=int(self.world.horizon)
        for tick in range(horizon+1):
            t=float(tick)
            # Move agents to current time BEFORE applying disturbances.
            done=[]
            for a in self.scouts+self.robots:
                if self.advance(a,t):done.append((a,a['state']))
            for agent,action in done:
                if agent['kind']=='scout':self.on_scout_done(agent,t,action)
                else:self.on_robot_done(agent,t,action)
            for ev in self.terrain.update(t):self.on_event(ev,t)
            if self.scout_method:self.dispatch_scouts(t)
            if self.rescue_method:self.dispatch_robots(t)
            # Once all active people are rescued and no future target can appear,
            # only running scout coverage remains relevant in scout mode.
            if tick%50==0 and tick>0 and not any(p.appeared_at>t for p in self.world.people):
                if self.mode!='scout' and len(self.rescued)==len(self.world.people):break
        self.computation_ms+=0  # measured planner work excludes Python sim overhead
        self.discoveries.sort(key=lambda e:(e['t'],e['id']))
        self.rescues.sort(key=lambda e:(e['t'],e['id']))
        last_rescue=max((e['t'] for e in self.rescues),default=0)
        all_events=len(self.world.events)
        final={'found':len(self.discoveries),'rescued':len(self.rescues),
               'total':len(self.world.people),'coverage':len(self.covered),
               'energy':round(self.energy,2),'compute_ms':round(self.computation_ms,2),
               'replans':len(self.replans),'blocked':self.blocked,
               'incidents':self.incidents,'last_rescue':last_rescue,
               'finished_at':round(min(self.world.horizon,max((s['t1'] for s in self.segments),default=0)),2),
               'events':all_events,'wall_ms':round((time.perf_counter()-start)*1000,1)}
        return {'method':self.method,'label':self.label,'mode':self.mode,
                'segments':self.segments,'visits':self.visits,'discoveries':self.discoveries,
                'rescues':self.rescues,'decisions':self.decisions,'replans':self.replans,
                'pareto':self.pareto,'final':final}


def run_collection(mode,world):
    if mode=='mission':methods=MISSION_METHODS
    elif mode=='scout':methods=[(m,l,m,None) for m,l in SCOUT_METHODS]
    elif mode=='rescue':methods=[(m,l,None,m) for m,l in RESCUE_METHODS]
    else:raise ValueError('Invalid mode')
    runs=[]
    for key,label,_,_ in methods:
        runs.append(Simulation(world,mode,key,label).run())
    return {'mode':mode,'version':'0.3.0','scenario':world.public_map(),'runs':runs}
