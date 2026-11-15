from __future__ import annotations

from dataclasses import dataclass, field
import math

from .domain import Config, Terrain
from .planning import Job, RescuePlanner, ScoutPlanner, SCOUT_METHODS, RESCUE_METHODS


def score(count, total, timestamps, energy, capacity, horizon):
    """One extra located/rescued person outweighs every secondary bonus."""
    if not count:
        return 0.0
    timing = sum(max(0, 1-t/horizon) for t in timestamps) / count
    efficiency = max(0, 1-energy/max(1, capacity*3))
    return 100 * (count + .49*timing + .24*efficiency) / (total+.73)


@dataclass
class Drone:
    id: int
    x: float
    y: float
    energy: float
    mode: str = "idle"
    goals: list = field(default_factory=list)
    distance: float = 0.0

    def json(self):
        return {"id": self.id, "x": self.x, "y": self.y, "z": 0,
                "energy": self.energy, "mode": self.mode, "goals": self.goals[:3]}


class Scouting:
    def __init__(self, terrain, method, label=None):
        self.terrain, self.config = terrain, terrain.config
        self.method, self.label = method, label or dict(SCOUT_METHODS)[method]
        self.planner = ScoutPlanner(method, terrain)
        self.drones = [Drone(i, *terrain.base, self.config.drone_energy)
                       for i in range(self.config.drones)]
        self.coverage = 0
        self.discovered = {}
        self.energy_used = 0.0
        self.finished_at = None
        self.reason = None
        self.history = []
        self._scan(0)
        self._record(0)

    def _scan(self, now):
        for d in self.drones:
            self.coverage |= self.terrain.footprint((d.x,d.y))
        for p in self.terrain.people:
            if p.id not in self.discovered and self.coverage & (1 << (p.y*self.terrain.width+p.x)):
                self.discovered[p.id] = now

    def step(self, now):
        if self.finished_at is not None:
            return
        t, c = self.terrain, self.config
        idle = []
        returning_home = len(self.discovered) == c.people
        for d in self.drones:
            home = math.dist((d.x,d.y), t.base)
            if returning_home and d.mode != "stranded":
                if home < 1e-8:
                    d.mode = "parked"; d.goals = []
                else:
                    d.mode = "returning"; d.goals = [t.base]
            if d.mode == "charging":
                d.energy = min(c.drone_energy, d.energy+12)
                if d.energy >= c.drone_energy-1e-9:
                    d.mode = "idle"
            elif d.mode not in {"returning", "stranded", "parked"}:
                next_goal = d.goals[0] if d.goals else (d.x,d.y)
                needed = math.dist((d.x,d.y),next_goal) + math.dist(next_goal,t.base)+3
                if d.energy < needed:
                    d.mode = "returning"; d.goals = [t.base]
            if d.mode == "idle" and not d.goals:
                idle.append(d)
        if idle:
            active = [point for d in self.drones if d not in idle for point in d.goals]
            plans = self.planner.plan(idle, self.coverage, active, now-1)
            for d in idle:
                if plans.get(d.id):
                    d.goals = list(plans[d.id]); d.mode = "surveying"
                    # Do not dispatch beyond a feasible round trip.
                    goal = d.goals[0]
                    need = math.dist((d.x,d.y),goal)+math.dist(goal,t.base)+3
                    if need > d.energy:
                        d.goals = [t.base]; d.mode = "returning"
                elif math.dist((d.x,d.y), t.base) > 1e-8:
                    d.goals = [t.base]; d.mode = "returning"
                elif d.energy < c.drone_energy - 1e-8:
                    d.mode = "charging"
                else:
                    d.mode = "parked"
        # Four fixed sensing substeps prevent gaps during high-speed movement.
        for substep in range(4):
            for d in self.drones:
                if d.mode in {"charging","stranded"} or not d.goals:
                    continue
                target = d.goals[0]
                distance = math.dist((d.x,d.y),target)
                amount = min(distance, .75, d.energy)
                if distance:
                    d.x += (target[0]-d.x)*amount/distance
                    d.y += (target[1]-d.y)*amount/distance
                d.energy = max(0,d.energy-amount)
                d.distance += amount; self.energy_used += amount
                if distance <= amount+1e-9:
                    d.x,d.y = target; d.goals.pop(0)
                    if d.mode == "returning":
                        d.mode = "charging"
                    elif not d.goals:
                        d.mode = "idle"
                elif d.energy <= 1e-9:
                    d.mode = "stranded"; d.goals=[]
            self._scan(now-1+(substep+1)/4)
        home = all(math.dist((d.x,d.y), t.base) < 1e-8 for d in self.drones)
        if len(self.discovered) == c.people and home:
            self.finished_at = now; self.reason = "all_found"
        elif now >= c.horizon:
            self.finished_at = now; self.reason = "time_limit"
        elif all(d.mode == "stranded" for d in self.drones):
            self.finished_at = now; self.reason = "energy_exhausted"
        elif all(d.mode in {"parked", "stranded"} for d in self.drones):
            self.finished_at = now; self.reason = "no_reachable_sector"
        self._record(now)

    def _record(self, now):
        self.history.append([now,len(self.discovered),self.energy_used,
                             self.coverage.bit_count()/len(self.terrain.eligible)])

    def metrics(self, now):
        c=self.config; n=len(self.discovered)
        elapsed = self.finished_at if self.finished_at is not None else now
        times=list(self.discovered.values())
        return {"found":n,"rescued":None,"expired":None,
            "coverage":self.coverage.bit_count()/len(self.terrain.eligible),
            "energy":self.energy_used,"energy_ground":0,"energy_drone":self.energy_used,
            "energy_per_person":self.energy_used/n if n else None,
            "mean_response":sum(times)/n if n else None,
            "seconds_per_person":elapsed/n if n else None,
            "people_per_minute":60*n/elapsed if elapsed else 0,
            "finished_at":self.finished_at,"all_completed_at":max(times) if n==c.people else None,
            "last_completed_at":max(times) if times else None,
            "score":score(n,c.people,times,self.energy_used,c.drone_energy*c.drones,c.horizon),
            "status":self.reason or "running",
            "planning":self.planner.stats()}

    def snapshot(self, now):
        return {"id":self.method,"label":self.label,"drones":[d.json() for d in self.drones],
            "coverage_mask":format(self.coverage,"x"),
            "robots":[],"people":[{"id":p.id,"status":"found" if p.id in self.discovered else "hidden",
                "discovered_at":self.discovered.get(p.id),"rescued_at":None} for p in self.terrain.people],
            "metrics":self.metrics(now),"history":self.history,"trace":self.planner.trace,
            "trace_time":self.planner.trace_time,
            "trace_kind":"scout"}


@dataclass
class Robot:
    id: int
    x: float
    y: float
    energy: float
    mode: str = "idle"
    person: int | None = None
    path: list = field(default_factory=list)
    path_index: int = 1
    service: float = 0.0
    charge_target: float = 0.0
    distance: float = 0.0
    assigned_at: float | None = None

    def json(self):
        return {"id":self.id,"x":self.x,"y":self.y,"z":0,"energy":self.energy,
            "mode":self.mode,"person":self.person,
            "path":self.path[max(0,self.path_index-1):] if self.path else []}


class Evacuation:
    def __init__(self, terrain, method, scouting):
        self.terrain,self.config = terrain,terrain.config
        self.method,self.label = method,dict(RESCUE_METHODS)[method]
        self.scouting = scouting
        self.planner = RescuePlanner(method,self.config)
        self.robots = [Robot(i,*terrain.base,self.config.robot_energy)
                       for i in range(self.config.robots)]
        self.people = [{"id":p.id,"status":"hidden","discovered_at":None,
                        "rescued_at":None,"assigned_at":None} for p in terrain.people]
        self.energy_used = 0.0
        self.finished_at = self.scout_energy_at_finish = None
        self.reason = None
        self.history = []
        self._discover()
        self._record(0)

    def _discover(self, cutoff=math.inf):
        for ident,when in self.scouting.discovered.items():
            if when > cutoff:
                continue
            state=self.people[ident]
            if state["discovered_at"] is None:
                state["discovered_at"]=when
                if state["status"]=="hidden":
                    state["status"]="waiting"

    def _trip_energy(self,person):
        p=self.terrain.people[person]
        return self.terrain.distances[(p.x,p.y)]*2.35+.08*(p.extraction+2)

    def _remaining(self,r):
        if r.mode=="stranded":
            return math.inf,0.0
        if r.mode=="idle":
            return 0.0,r.energy
        if r.mode=="charging":
            return max(0,r.charge_target-r.energy)/10,r.charge_target
        if r.person is None:
            return 0.0,r.energy
        p=self.terrain.people[r.person]
        distance=self.terrain.distances[(p.x,p.y)]
        remaining_cost=0.0
        if r.mode in {"outbound","inbound"}:
            for k in range(r.path_index,len(r.path)):
                a,b=r.path[k-1],r.path[k]
                fraction=math.dist((r.x,r.y),b) if k==r.path_index else 1
                remaining_cost+=self.terrain.edge_cost(a,b)*fraction
        if r.mode=="outbound":
            duration=remaining_cost/1.25+p.extraction+distance/1.05+2
            cost=remaining_cost+distance*1.35+.08*(p.extraction+2)
        elif r.mode=="loading":
            duration=r.service+distance/1.05+2
            cost=distance*1.35+.08*(r.service+2)
        elif r.mode=="inbound":
            duration=remaining_cost/1.05+2
            cost=remaining_cost*1.35+.16
        else:
            duration=r.service;cost=.08*r.service
        return duration,max(0,r.energy-cost)

    def _assign(self,now):
        if now % 5:
            return
        waiting=[Job(p.id,self.terrain.distances[(p.x,p.y)],p.deadline,p.extraction)
                 for p in self.terrain.people if self.people[p.id]["status"]=="waiting"]
        if not waiting or not any(r.mode=="idle" for r in self.robots):
            return
        queues=self.planner.plan(waiting,[self._remaining(r) for r in self.robots],now)
        for r,queue in zip(self.robots,queues):
            if r.mode!="idle" or not queue:
                continue
            ident=queue[0]
            if self.people[ident]["status"]!="waiting":
                continue
            needed=self._trip_energy(ident)
            if needed>r.energy+1e-8:
                r.mode="charging";r.charge_target=min(self.config.robot_energy,needed+1e-6)
                continue
            p=self.terrain.people[ident]
            self.people[ident]["status"]="assigned"
            self.people[ident]["assigned_at"]=now
            r.person=ident;r.assigned_at=now
            r.path=self.terrain.base_path((p.x,p.y));r.path_index=1;r.mode="outbound"

    def _advance(self,r,dt,clock):
        remaining=dt
        while remaining>1e-9:
            if r.mode=="idle" or r.mode=="stranded":
                break
            if r.mode=="charging":
                duration=min(remaining,max(0,r.charge_target-r.energy)/10)
                r.energy=min(self.config.robot_energy,r.energy+10*duration)
                if r.energy>=r.charge_target-1e-8:
                    r.mode="idle"
                break
            if r.mode in {"outbound","inbound"}:
                if r.path_index>=len(r.path):
                    if r.mode=="outbound":
                        r.mode="loading";r.service=self.terrain.people[r.person].extraction
                    else:
                        r.mode="unloading";r.service=2.0
                    continue
                previous,target=r.path[r.path_index-1],r.path[r.path_index]
                distance=math.dist((r.x,r.y),target)
                factor=self.terrain.edge_cost(previous,target)
                speed,rate=(1.25,1.0) if r.mode=="outbound" else (1.05,1.35)
                distance_now=min(distance,speed*remaining/factor,r.energy/(rate*factor))
                duration=distance_now*factor/speed
                if distance>0:
                    r.x+=(target[0]-r.x)*distance_now/distance
                    r.y+=(target[1]-r.y)*distance_now/distance
                cost=distance_now*factor*rate
                r.energy=max(0,r.energy-cost);self.energy_used+=cost
                r.distance+=distance_now
                remaining-=duration;clock+=duration
                if distance<=distance_now+1e-8:
                    r.x,r.y=target;r.path_index+=1
                elif r.energy<=1e-9:
                    r.mode="stranded"
                    break
                elif duration<=1e-12:
                    break
            else:
                duration=min(remaining,r.service)
                cost=min(r.energy,.08*duration)
                r.energy-=cost;self.energy_used+=cost
                remaining-=duration;clock+=duration;r.service-=duration
                if r.service>1e-8:
                    break
                ident=r.person;p=self.terrain.people[ident];state=self.people[ident]
                if r.mode=="loading":
                    state["status"]="carried" if clock<=p.deadline else "expired"
                    r.mode="inbound"
                    r.path=list(reversed(self.terrain.base_path((p.x,p.y))))
                    r.path_index=1
                else:
                    if clock<=p.deadline:
                        state["status"]="rescued";state["rescued_at"]=clock
                    else:
                        state["status"]="expired"
                    r.mode="idle";r.person=None;r.path=[]

    def step(self,now):
        if self.finished_at is not None:
            return
        self._discover(now-1)
        self._assign(now-1)
        for r in self.robots:
            self._advance(r,1.0,now-1)
        self._discover(now)
        for p,state in zip(self.terrain.people,self.people):
            if now>p.deadline and state["status"]!="rescued":
                state["status"]="expired"
        all_rescued=all(s["status"]=="rescued" for s in self.people)
        resolved=all(s["status"] in {"rescued","expired"} for s in self.people)
        idle=all(r.mode in {"idle","stranded"} for r in self.robots)
        if all_rescued:
            self.reason="all_rescued"
        elif resolved and idle:
            self.reason="no_tasks_remaining"
        elif now>=self.config.horizon:
            self.reason="time_limit"
        if self.reason:
            self.finished_at=now
            self.scout_energy_at_finish=self.scouting.energy_used
        self._record(now)

    def metrics(self,now):
        c=self.config
        saved=[s for s in self.people if s["status"]=="rescued"]
        n=len(saved);times=[s["rescued_at"] for s in saved]
        drone_energy=(self.scout_energy_at_finish if self.finished_at is not None
                      else self.scouting.energy_used)
        total_energy=self.energy_used+drone_energy
        elapsed=self.finished_at if self.finished_at is not None else now
        return {"found":sum(s["discovered_at"] is not None for s in self.people),
            "rescued":n,"expired":sum(s["status"]=="expired" for s in self.people),
            "coverage":self.scouting.coverage.bit_count()/len(self.terrain.eligible),
            "energy":total_energy,"energy_ground":self.energy_used,"energy_drone":drone_energy,
            "energy_per_person":total_energy/n if n else None,
            "mean_response":sum(s["rescued_at"]-s["discovered_at"] for s in saved)/n if n else None,
            "seconds_per_person":elapsed/n if n else None,
            "people_per_minute":60*n/elapsed if elapsed else 0,
            "finished_at":self.finished_at,
            "all_completed_at":max(times) if n==c.people else None,
            "last_completed_at":max(times) if times else None,
            "score":score(n,c.people,times,total_energy,
                c.robot_energy*c.robots+c.drone_energy*c.drones,c.horizon),
            "status":self.reason or "running","planning":self.planner.stats()}

    def _record(self,now):
        m=self.metrics(now)
        self.history.append([now,m["rescued"],m["energy"],m["found"]])

    def snapshot(self,now):
        return {"id":self.method,"label":self.label,
            "coverage_mask":format(self.scouting.coverage,"x"),
            "drones":[d.json() for d in self.scouting.drones],
            "robots":[r.json() for r in self.robots],"people":self.people,
            "metrics":self.metrics(now),"history":self.history,
            "trace_time":self.planner.trace_time,
            "trace":self.planner.trace,"trace_kind":"rescue"}


class Comparison:
    def __init__(self,config=None,mode="rescue"):
        self.config=config or Config()
        if mode not in {"scout","rescue"}:
            raise ValueError("Неизвестная страница бенчмарка.")
        self.mode=mode;self.time=0
        self.terrain=Terrain(self.config)
        if mode=="scout":
            self.shared_scout=None
            self.runs=[Scouting(self.terrain,key,label) for key,label in SCOUT_METHODS]
        else:
            self.shared_scout=Scouting(self.terrain,self.config.scout_policy)
            self.runs=[Evacuation(self.terrain,key,self.shared_scout) for key,_ in RESCUE_METHODS]

    @property
    def done(self):
        return all(r.finished_at is not None for r in self.runs)

    def step(self,count=1, *, snapshot=True):
        for _ in range(count):
            if self.done:
                break
            self.time+=1
            if self.shared_scout:
                self.shared_scout.step(self.time)
            for r in self.runs:
                r.step(self.time)
        return self.snapshot() if snapshot else None

    def snapshot(self,include_world=False):
        out={"mode":self.mode,"time":self.time,"done":self.done,"config":self.config.json(),
            "runs":[r.snapshot(self.time) for r in self.runs],
            "shared_scout_planning":self.shared_scout.planner.stats() if self.shared_scout else None}
        if include_world:
            out["world"]=self.terrain.json()
        return out

    def finish(self,cancel=None):
        while not self.done:
            if cancel is not None and cancel.is_set():
                return False
            self.step(1, snapshot=False)
        return True

    def results(self):
        return [{"algorithm":r.method,"label":r.label,**r.metrics(self.time)} for r in self.runs]

