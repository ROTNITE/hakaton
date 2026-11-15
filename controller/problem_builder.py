"""Construct optimization inputs exclusively from a delivered Observation.

Version native-road-air-1: metre geometry, 8/6s physical service plus an explicit
turn/ramp allowance. These are estimates, not privileged physical rollouts.
"""
from __future__ import annotations

from dataclasses import dataclass,replace
from functools import lru_cache
import math

from controller.navigation import NavigationMap,RouteFailure,handover_xy,observed_surfaces
from controller.optimization import Crew,RescueProblem,ScoutProblem,Sector,Target,Trip


@dataclass(frozen=True)
class ScoutInput:
    problem:ScoutProblem
    positions:dict
    altitudes:dict


def mobiles(observation,kind):
    # Array order and prefixes do not encode speed, assignment or priority.
    agents=[a for a in observation['agents'] if a['kind']==kind and a['position'] is not None and
            a['status'] not in ('failed','offline','unknown','safe_mode') and
            a.get('communication',{}).get('reachable') is not False]
    return sorted(agents,key=lambda a:(tuple(a['position']),tuple(sorted(a['capabilities'])),a['id']))


def usable_energy(agent):
    physical=agent.get('physical',{})
    if physical.get('unlimited_energy') is True:return None
    value=physical.get('remaining_wh')
    if type(value) not in (int,float) or not math.isfinite(value):return 0.
    reserve=physical.get('reserve_wh',physical.get('capacity_wh',value)*.1)
    if type(reserve) not in (int,float) or not math.isfinite(reserve) or reserve<0:return 0.
    return max(0.,value-reserve)


class ProblemBuilder:
    def __init__(self,announced_map,*,surfaces=(),altitudes=None):
        self.map=announced_map
        self.nav=NavigationMap(announced_map,surfaces=surfaces)
        self._cached_trip=lru_cache(maxsize=4096)(self._geometric_trip)
        xy=handover_xy(announced_map)
        self.base=(*xy,self.nav.ground_z(*xy))
        bounds=announced_map['bounds'];self.width=math.ceil((bounds['max'][0]-bounds['min'][0])/50)
        self.height=math.ceil((bounds['max'][1]-bounds['min'][1])/50)
        self.sectors=[];self.positions={}
        for y in range(self.height):
            for x in range(self.width):
                sid=f'sector-{x}-{y}'
                self.sectors.append(Sector(sid,1.,x,y))
                self.positions[sid]=(min(bounds['max'][0]-2,bounds['min'][0]+x*50+25),
                                     min(bounds['max'][1]-2,bounds['min'][1]+y*50+25))
        self.altitudes=dict(altitudes or {})

    def scout(self,observation,completed=(),*,mode='coverage'):
        agents=mobiles(observation,'aerial')
        sectors=[]
        targets=[]
        if mode in ('risk','hazard_support'):
            for target in observation['targets']:
                observed=target.get('observed_at',observation['time'])
                if (target.get('status') in ('suspected','confirmed') and target.get('evacuation_state')!='evacuated' and
                        target.get('position') and type(observed) in (int,float) and 0<=observed<=observation['time']):
                    targets.append(target)
        for sector in self.sectors:
            if sector.id in completed:continue
            xy=self.positions[sector.id]
            visibility=self.nav.sector_visibility(xy)
            prior=visibility
            if mode in ('risk','hazard_support'):
                nearby=max((t.get('priority',0.) for t in targets if math.dist(t['position'][:2],xy)<=37.),default=0.)
                prior+=nearby*(1. if mode=='risk' else .45)
                if mode=='hazard_support':prior+=(1.-visibility)*.85
            sectors.append(replace(sector,prior=prior))
        now=observation['time'];points=[self.positions[s.id] for s in sectors]
        for i,a in enumerate(agents):self.altitudes.setdefault(a['id'],20.+5*(i%5))
        top=max((b['bounds']['max'][2] for b in self.map.get('buildings',())),default=0)
        for a in agents:self.altitudes[a['id']]=max(self.altitudes[a['id']],top+3)
        crew=[];initial=[];initial_seconds=[];initial_wh=[];returns=[]
        for a in agents:
            physical=a.get('physical',{});speed=physical.get('speed_limit_m_s',0)
            if not speed or speed<=0:continue
            altitude=self.altitudes[a['id']]
            if altitude>self.map['bounds']['max'][2]-.4:continue
            crew.append(Crew(a['id'],speed,ready_at=now,usable_wh=usable_energy(a)))
            climb=physical.get('climb_rate_m_s',5.)
            if type(climb) not in (int,float) or climb<=0:raise ValueError('Invalid declared climb rate')
            vertical=abs(altitude-a['position'][2])
            initial.append([vertical+math.dist(a['position'][:2],p) for p in points])
            initial_seconds.append([vertical/climb+math.dist(a['position'][:2],p)/speed for p in points])
            initial_wh.append([distance*.069 for distance in initial[-1]])
            # Descending is slower. Equivalent return distance is conservative
            # for both finite-energy feasibility and the standing-power cost.
            home=physical.get('dock_position_m',a['position'])
            returns.append([math.dist(p,home[:2])+max(0,altitude-home[2])*speed/2.5 for p in points])
        distances=[[math.dist(a,b) for b in points] for a in points]
        problem=ScoutProblem(sectors,crew,distances,initial,horizon=observation['mission']['termination']['horizon'],
            now=now,scan_s=2.8,scan_wh=.55,wh_per_m=.069,idle_power_w=130.,return_distances=returns,
            initial_seconds=initial_seconds,initial_wh=initial_wh)
        return ScoutInput(problem,{s.id:self.positions[s.id] for s in sectors},dict(self.altitudes))

    def _geometric_trip(self,start,target):
        dx,dy=start[0]-target[0],start[1]-target[1]
        angle=math.atan2(dy,dx)
        for offset in (0,math.pi/2,-math.pi/2,math.pi):
            heading=angle+offset
            x,y=target[0]+2.5*math.cos(heading),target[1]+2.5*math.sin(heading)
            goal=(x,y,self.nav.ground_z(x,y))
            try:
                outgoing=self.nav.road_route(start,goal)
                returning=self.nav.road_route(goal,self.base)
                return outgoing.weighted_distance_m,returning.weighted_distance_m
            except RouteFailure:continue
        return None

    def hazard_patrol(self,observation,active,goals,altitudes,reserved):
        """Offer bounded, flyable revisits to delivered hazards after primary coverage."""
        affected=set()
        for surface in observed_surfaces(observation):
            if surface.restriction or not (surface.ground_blocked or surface.cost>1 or surface.visibility<1):continue
            x,y=((a+b)*.5 for a,b in zip(surface.bounds.minimum[:2],surface.bounds.maximum[:2]))
            low=self.map['bounds']['min']
            affected.add(f'sector-{math.floor((x-low[0])/50)}-{math.floor((y-low[1])/50)}')
        candidates=[];used=set(reserved)
        agents=mobiles(observation,'aerial')
        remaining=observation['mission']['termination']['horizon']-observation['time']
        for sector in sorted((affected & self.positions.keys())-set(active.values())):
            xy=self.positions[sector]
            for agent in sorted(agents,key=lambda a:(math.dist(a['position'][:2],xy),a['id'])):
                aid=agent['id'];physical=agent.get('physical',{});speed=physical.get('speed_limit_m_s',0)
                if aid in used or aid not in altitudes or 'sense' not in agent['capabilities'] or speed<=0:continue
                start=goals.get(aid,agent['position']);goal=(*xy,altitudes[aid])
                radius=physical.get('radius_m',1.65)
                try:
                    path=self.nav.route(start,goal,aerial=True,radius_m=radius,half_height_m=.4,cruise_altitude_m=goal[2])
                    home=physical.get('dock_position_m',start)
                    back=self.nav.route(goal,home,aerial=True,radius_m=radius,half_height_m=.4,cruise_altitude_m=goal[2])
                except RouteFailure:continue
                approach=math.dist(agent['position'],start)
                energy=path.distance_m*.069+.55;usable=usable_energy(agent)
                if (approach+path.distance_m)/speed+5.6>remaining or (
                    usable is not None and energy+(approach+back.distance_m)*.069>usable):continue
                candidates.append({'agent_id':aid,'sector_id':sector,'estimated_energy_wh':energy})
                used.add(aid)
                break
            if len(candidates)==2:break
        return candidates

    def _trip(self,start,target,speed,exit_points=()):
        prefix=0.
        if exit_points:
            prefix=sum(math.dist(a,b) for a,b in zip([start,*exit_points],exit_points));start=tuple(exit_points[-1])
        geometry=self._cached_trip(tuple(start),tuple(target))
        if geometry is None:return None
        out,back=geometry;out+=prefix
        duration=out/speed+back/(speed*.8)+8+6+4
        return Trip(duration,out*.082+back*.118+duration*35/3600)

    def rescue(self,observation,jobs,*,max_targets=30):
        now=observation['time'];agents=mobiles(observation,'ground')
        known={t['id']:t for t in observation['targets']}
        reserved={job.get('target_id') for job in jobs.values() if job.get('target_id')}
        targets=[t for t in known.values() if t.get('status')=='confirmed' and t.get('position') and
                 t.get('evacuation_state','waiting')=='waiting' and t['id'] not in reserved and
                 t.get('observed_at',now)<=now]
        targets=sorted(targets,key=lambda t:(-t.get('priority',0),math.dist(t['position'],self.base),t['id']))[:max_targets]
        target_data=[Target(t['id'],t.get('priority',1)*3,deadline=t.get('deadline')) for t in targets]
        crews=[];trips=[];first=[];available=[]
        for a in agents:
            # Clearing a shared service position is a protected physical task.
            # It is not an idle carrier ready to claim another rescue; an
            # obstructed parker must not starve actually available teammates.
            if jobs.get(a['id'],{}).get('phase')=='park':continue
            physical=a.get('physical',{});speed=physical.get('speed_limit_m_s',0)
            if not speed or speed<=0:continue
            remaining=usable_energy(a);ready=now;start=tuple(a['position'])
            job=jobs.get(a['id'],{});busy=physical.get('carrying') or job.get('target_id') is not None
            actions={v['action'] for v in a.get('available_actions',())}
            available.append(not busy and job.get('phase','choose')=='choose' and
                'carry' in a['capabilities'] and {'follow_route','pickup'}<=actions)
            if busy:
                if physical.get('carrying'):
                    try:
                        distance=self.nav.road_route(start,self.base).weighted_distance_m
                        delay=distance/(speed*.8)+6+4
                        expense=distance*.118+delay*35/3600
                    except RouteFailure:delay=observation['mission']['termination']['horizon']+1;expense=0
                else:
                    target=known.get(job.get('target_id'))
                    work=self._trip(start,target['position'],speed) if target is not None else None
                    delay=work.duration_s if work else observation['mission']['termination']['horizon']+1
                    expense=work.energy_wh if work else 0
                ready+=delay;start=self.base
                if remaining is not None:remaining=max(0,remaining-expense)
            crews.append(Crew(a['id'],speed,ready_at=ready,usable_wh=remaining))
            row=[self._trip(self.base,t['position'],speed) for t in targets]
            trips.append(row)
            exits=physical.get('dock_exit_waypoints',()) if physical.get('at_dock') and not busy else ()
            first.append([self._trip(start,t['position'],speed,exits) for t in targets])
        return RescueProblem(target_data,crews,trips,horizon=observation['mission']['termination']['horizon'],
                             now=now,first_trips=first,available_now=available)
