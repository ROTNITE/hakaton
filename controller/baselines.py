"""Fixed rescue workflow baseline. Not the primary NSGA-II controller.

All poses, targets, command acknowledgements and geometry come from public
Observation/StepResponse. Private layouts and environment modules are absent.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import math

from controller.decisions import decision
from controller.navigation import Box, NavigationMap, RouteFailure, handover_xy, observed_surfaces


BASELINES=('fixed_workflow','local_reactive')


@dataclass
class Job:
    phase:str
    target:str|None=None
    pending:str|None=None
    next_phase:str|None=None
    pending_index:int=0
    action:str|None=None
    charge_station:str|None=None
    acknowledgement_unknown_at:float|None=None
    using_dock_exit:bool=False


class FixedWorkflow:
    automatic_route_recovery=True
    select_initial_scenario=True
    reason_code='fixed_rescue_workflow'

    def __init__(self,*,prefer_roads=True):
        self.prefer_roads=prefer_roads
        self.episode=None
        self.jobs={}
        self.scan={}
        self.scan_cursor=0
        self.route_cache=None
        self.failures=[]
        self.previous=None
        self.blocked_agents=set()
        self.scenario_reserved=set()
        self.known_surfaces=()
        self.local_obstacles={}
        self.home_positions={}
        self.route_failures=[]
        self.static_yields={}
        self.traffic_holds={}
        self.reconfirm_after={}

    @staticmethod
    def available(agent,action):
        return any(a.get('action')==action for a in agent['available_actions'])

    def observe_response(self,response):
        results=response.get('command_results',[])
        for agent,job in self.jobs.items():
            if not job.pending:continue
            current=next((r for r in results if r['decision_id']==job.pending and r['agent_id']==agent and r['command_index']==job.pending_index),None)
            if current is None:continue
            status=current['execution_status']
            if status=='completed':
                job.pending=None;job.acknowledgement_unknown_at=None;job.using_dock_exit=False
                if job.next_phase is not None:job.phase=job.next_phase;job.next_phase=None
                if job.action=='handover':job.target=None
                if job.action=='charge':job.charge_station=None
            elif status in ('failed','cancelled') or current['validation_status']=='rejected' or current['delivery_status'] in ('expired','lost'):
                self.failures.append({'agent_id':agent,'result':current})
                job.pending=None;job.next_phase=None;job.acknowledgement_unknown_at=None;job.using_dock_exit=False
                if job.action=='charge':job.charge_station=None
            elif status=='unknown':
                job.acknowledgement_unknown_at=current['updated_at']
        if response.get('status')=='running':
            # Updated only after an actual successful StepResponse.
            self.previous=self.last_decision

    @staticmethod
    def _obstacles(agent,agents):
        obstacles=[]
        for other in agents:
            if other['id']==agent['id'] or other['position'] is None:continue
            x,y,z=other['position'];radius=other.get('physical',{}).get('radius_m',1.65 if other['kind']=='aerial' else 1.45)
            half=.4 if other['kind']=='aerial' else 1.1
            obstacles.append({'kind':'box','min':[x-radius,y-radius,z-half],
                              'max':[x+radius,y+radius,z+half]})
        return obstacles

    @staticmethod
    def _still(agent, key):
        speed = agent.get('physical', {}).get(key)
        return isinstance(speed, (list, tuple)) and len(speed) == 3 and math.dist(speed, (0, 0, 0)) <= .1

    @staticmethod
    def _yielding_to(agent, peer):
        physical = agent.get('physical', {})
        return physical.get('stop_reason') == 'yield_to_vehicle' and physical.get('stop_obstacle') == peer['id']

    @classmethod
    def _parked_ground_peers(cls, agent, agents):
        if agent['kind'] != 'ground':
            return ()
        peers = []
        for other in agents:
            if other['id'] == agent['id'] or other['kind'] != 'ground' or other['position'] is None:
                continue
            physical = other.get('physical', {})
            if cls._still(other, 'velocity_m_s') and (cls._still(other, 'intended_velocity_m_s') or
                    cls._yielding_to(other, agent)):
                peers.append((other['position'][:2], physical.get('radius_m', 1.45)))
        return peers

    def _planned_route(self,announced,agent,agents,goal,*,precise_stop=False):
        obstacles=self._obstacles(agent,agents)
        obstacles.extend(self.local_obstacles.get(agent['id'],()))
        nav=NavigationMap(announced,observed_obstacles=obstacles,surfaces=self.known_surfaces,
                          parked_ground_peers=self._parked_ground_peers(agent,agents))
        air=agent['kind']=='aerial'
        radius=agent.get('physical',{}).get('radius_m',1.65 if air else 1.45)
        if not air and self.prefer_roads:
            goal=(*goal[:2],nav.ground_z(*goal[:2]))
            result=nav.road_route(agent['position'],goal,radius_m=radius,precise_stop=precise_stop)
        else:
            result=nav.route(agent['position'],goal,aerial=air,radius_m=radius,half_height_m=.4 if air else 1.1,
                             cruise_altitude_m=max(agent['position'][2],goal[2]) if air else 25.)
        return result

    def _route(self,announced,agent,agents,goal,*,precise_stop=False):
        try:route=self._planned_route(announced,agent,agents,goal,precise_stop=precise_stop)
        except RouteFailure as error:
            self._route_failure(agent,goal,error)
            raise
        return [list(p) for p in route.points[1:]] or [list(route.points[-1])]

    def _approach_target(self, announced, agent, agents, target, *, inspect=False):
        x, y, _ = target
        ax, ay, z = agent['position']
        bearing = math.atan2(ay - y, ax - x)
        failed_nearby = any(other['status'] == 'failed' and other['kind'] == 'ground' and other['position'] is not None
                            and math.dist(other['position'][:2], target[:2]) < 2. for other in agents)
        # A released stretcher may still be beside the failed chassis. The
        # ordinary pickup offset can put the second vehicle inside its hull.
        offsets = [(8., False)] if inspect else [(2.5, False)]
        if not inspect and failed_nearby:
            offsets.extend((distance, True) for distance in (3.1, 3.4, 3.55, 3.6))
        for distance, precise in offsets:
            angles = (0, math.pi / 2, -math.pi / 2, math.pi) if not precise else tuple(i * math.pi / 4 for i in range(8))
            for offset in angles:
                angle = bearing + offset
                goal = (x + distance * math.cos(angle), y + distance * math.sin(angle), z)
                try:
                    waypoints = self._route(announced, agent, agents, goal, precise_stop=precise)
                except RouteFailure:
                    continue
                parameters = {'waypoints': waypoints}
                if precise:
                    parameters['precise_stop'] = True
                return parameters
        return None

    def _route_failure(self,agent,goal,error):
        job=self.jobs.get(agent['id'])
        self.route_failures.append({'agent_id':agent['id'],'phase':job.phase if job else None,
            'position':list(agent['position']),'goal':list(goal),'reason':str(error)})

    def _stationary_yield(self,observation,agent):
        """Require six delivered seconds of a parked obstruction or mutual standstill."""
        aid=agent['id'];physical=agent.get('physical',{});now=observation['time']
        other=next((a for a in observation['agents'] if a['id']==physical.get('stop_obstacle')),None)
        def fresh(a):
            stamp=a.get('freshness',{}).get('position',{}).get('observed_at')
            return stamp if type(stamp) in (int,float) and 0<=now-stamp<=2 else None
        observed=fresh(agent);other_observed=fresh(other) if other else None
        reciprocal = (other is not None and agent['kind'] == other['kind'] == 'ground' and
                      self._yielding_to(other, agent))
        # The empty vehicle attempts the bypass first. For two equivalent
        # vehicles use a stable tie-break, so only one cancels its live route.
        must_clear = reciprocal and (bool(physical.get('carrying')), aid) < (
            bool(other['physical'].get('carrying')), other['id'])
        valid=(other is not None and self._yielding_to(agent, other) and other.get('position') is not None
               and observed is not None and other_observed is not None and self._still(agent,'velocity_m_s')
               and self._still(other,'velocity_m_s') and (self._still(other,'intended_velocity_m_s') or must_clear))
        if not valid:self.static_yields.pop(aid,None);return False
        stamps = (observed, other_observed);command_id=physical.get('active_command_id')
        prior=self.static_yields.get(aid)
        if (prior is None or prior['blocker']!=other['id'] or prior.get('command_id')!=command_id or
                any(not 0 <= stamp - last <= 2 for stamp, last in zip(stamps, prior['last'])) or
                math.dist(prior['position'],other['position'])>.25):
            prior={'blocker':other['id'],'command_id':command_id,'position':list(other['position']),
                   'since':max(stamps),'last':stamps}
            self.static_yields[aid]=prior
        prior['last']=stamps
        return min(stamps)-prior['since']>=6

    def _coordinate_ground_yields(self,observation,directives):
        """Freeze one conflicting intent while its stationary peer bypasses it.

        Both holds use ordinary delivered commands. Cargo and job phases remain
        intact. A fresh separation beyond the braking buffer releases the peer.
        """
        agents={a['id']:a for a in observation['agents']};now=observation['time'];events=[]
        def fresh(a):
            stamp=a.get('freshness',{}).get('position',{}).get('observed_at')
            return a.get('position') is not None and type(stamp) in (int,float) and 0<=now-stamp<=2
        for held,lease in list(self.traffic_holds.items()):
            clearer=agents.get(lease['clearing_agent']);peer=agents.get(held)
            failed=clearer is not None and clearer['status']=='failed'
            peer_failed=peer is not None and peer['status']=='failed'
            clear=clearer is not None and peer is not None and fresh(clearer) and fresh(peer) and (
                math.dist(clearer['position'][:2],peer['position'][:2])>=8 and
                math.dist(clearer['position'][:2],lease['start'][:2])>=2)
            if failed or peer_failed or clear:
                del self.traffic_holds[held]
                events.append({'action':'release','agent_id':held,'clearing_agent':lease['clearing_agent'],
                               'reason':'clearing_agent_failed' if failed else 'held_agent_failed' if peer_failed else 'fresh_separation'})
        if not self.automatic_route_recovery:return events
        used=set(self.traffic_holds)|{v['clearing_agent'] for v in self.traffic_holds.values()}
        for aid,a in sorted(agents.items()):
            job=self.jobs[aid];physical=a.get('physical',{})
            if (aid in used or aid in directives or aid in self.blocked_agents or aid in self.scenario_reserved or
                a['kind']!='ground' or not job.pending or job.action!='follow_route' or
                a.get('communication',{}).get('reachable') is False or
                physical.get('active_command_id')!=f'{job.pending}:{job.pending_index}' or
                not self.available(a,'hold') or not self._stationary_yield(observation,a)):continue
            peer=agents.get(physical.get('stop_obstacle'))
            if (peer is None or peer['id'] in used or peer['id'] in directives or
                peer['id'] in self.blocked_agents or peer['id'] in self.scenario_reserved or
                peer.get('communication',{}).get('reachable') is False or
                not self._yielding_to(peer,a) or not self.available(peer,'hold')):continue
            peer_job=self.jobs[peer['id']]
            if (not peer_job.pending or peer_job.action!='follow_route' or
                peer.get('physical',{}).get('active_command_id')!=f'{peer_job.pending}:{peer_job.pending_index}'):continue
            self.traffic_holds[peer['id']]={'clearing_agent':aid,'start':list(a['position'])}
            used.update((aid,peer['id']))
            events.append({'action':'hold_peer','agent_id':peer['id'],'clearing_agent':aid,
                           'reason':'reciprocal_ground_standstill'})
        return events

    @staticmethod
    def _dock_approach(agent,home):
        exits=agent.get('physical',{}).get('dock_exit_waypoints',())
        if not exits:return None
        entry=exits[0];dx,dy=home[0]-entry[0],home[1]-entry[1];length=math.hypot(dx,dy)
        if length<1:raise RouteFailure('invalid_delivered_dock_entry')
        # Turn in the open apron, then enter along the declared dock axis.
        # A diagonal shortcut to home intersects the narrow guide rails.
        staging=[entry[0]-4*dx/length,entry[1]-4*dy/length,entry[2]]
        return [staging,list(entry),list(home)]

    def _parking_route(self,announced,agent,agents,home):
        approach=self._dock_approach(agent,home)
        if not approach:return self._route(announced,agent,agents,home)
        return [*self._route(announced,agent,agents,approach[0]),*approach[1:]]

    def _charge_command(self,observation,announced,agent,job):
        physical=agent.get('physical',{})
        if physical.get('unlimited_energy') is not False or physical.get('carrying') or job.phase in ('pickup','return','handover'):
            return False,None
        capacity=physical.get('capacity_wh',0);remaining=physical.get('remaining_wh',0)
        if not capacity:return False,None
        if job.charge_station is None and remaining>max(.35*capacity,physical.get('reserve_wh',.10*capacity)):
            return False,None
        aid=agent['id'];air=agent['kind']=='aerial'
        occupied={j.charge_station for owner,j in self.jobs.items() if owner!=aid}
        stations=[]
        for item in observation.get('infrastructure',()):
            charger=item.get('charger')
            if (item['kind']=='charging_station' and item['status']=='active' and isinstance(charger,dict)
                    and charger.get('kind')==agent['kind'] and charger.get('agent_id') in (None,aid)
                    and charger.get('remaining_wh',0)>0 and item['id'] not in occupied):
                stations.append(item)
        stations.sort(key=lambda item:(item['id']!=job.charge_station,math.dist(agent['position'],item['position']),item['id']))
        job.charge_station=None
        for station in stations:
            center=station['position'];radius=station['charger']['docking_distance_m']
            distance=math.dist(agent['position'][:2],center[:2])
            if self.available(agent,'charge') and distance<=radius and abs(agent['position'][2]-center[2])<(.25 if air else 1.25):
                job.charge_station=station['id']
                return True,{'agent_id':aid,'action':'charge','parameters':{'station_id':station['id']}}
            if distance<.95 and (not air or abs(agent['position'][2]-center[2])<.25):
                # Route completion can precede the local docking speed check.
                job.charge_station=station['id'];return True,None
            if not self.available(agent,'follow_route'):continue
            try:
                route=self._planned_route(announced,agent,observation['agents'],center)
            except RouteFailure as error:
                self._route_failure(agent,center,error);continue
            speed=physical.get('speed_limit_m_s',0)
            effort=route.weighted_distance_m*(.069 if air else .082)
            if speed<=0 or effort+route.distance_m/speed*(144. if air else 44.)/3600.+.25>=remaining:continue
            waypoints=[list(p) for p in route.points[1:]] or [list(route.points[-1])]
            if not air and physical.get('at_dock') and physical.get('dock_exit_waypoints'):
                waypoints=physical['dock_exit_waypoints']
            job.charge_station=station['id']
            return True,{'agent_id':aid,'action':'follow_route','parameters':{'waypoints':waypoints}}
        return True,None

    @staticmethod
    def _scan_path(announced):
        axes=announced.get('road_axes_m') or list(range(25,int(announced['size_m']),50))
        return [(x,y,25.) for j,y in enumerate(axes) for x in (axes if j%2==0 else axes[::-1])]

    def _scan_goal(self,agent,announced):
        path=self._scan_path(announced)
        if not path:return None
        index=self.scan_cursor%len(path);self.scan_cursor+=1
        return path[index]

    def _reconcile(self,agent,job,known):
        observed_at=agent.get('freshness',{}).get('position',{}).get('observed_at')
        if observed_at is None or observed_at<job.acknowledgement_unknown_at:return None
        physical=agent.get('physical',{});active=physical.get('active_command_id')
        command_id=f'{job.pending}:{job.pending_index}'
        if physical.get('state') in ('loading','unloading','charging','charge_wait'):return None
        completed=False
        if job.action in ('move','follow_route') and active==command_id:
            if physical.get('route_finished') is not True:return None
            completed=True
        elif job.action=='pickup':
            completed=job.target is not None and physical.get('cargo_target_id')==job.target
        elif job.action=='handover':
            completed=known.get(job.target,{}).get('evacuation_state')=='evacuated'
            if not completed and not physical.get('carrying'):return None
        if completed:
            if job.next_phase is not None:job.phase=job.next_phase
            if job.action=='handover':job.target=None
        if job.action=='charge':job.charge_station=None
        job.pending=job.next_phase=job.acknowledgement_unknown_at=None
        return {'agent_id':agent['id'],'command_id':command_id,'observed_at':observed_at,
                'outcome':'observed_complete' if completed else 'ready_for_new_command'}

    def _choose_target(self,agent,choices):
        prioritized=any('operator_priority' in target for target in choices)
        return min(choices,key=lambda t:(-t.get('priority',0) if prioritized else 0,
                   math.dist(agent['position'],t['position']),t['id'])) if choices else None

    @staticmethod
    def hold_orders(observation):
        now=observation['time'];orders={}
        for directive in observation.get('mission',{}).get('directives',()):
            if directive.get('status','active')!='active':continue
            if directive.get('action')!='hold' or not isinstance(directive.get('agent_id'),str):continue
            issued=directive.get('issued_at');expires=directive.get('expires_at')
            if type(issued) not in (int,float) or type(expires) not in (int,float) or not issued<=now<expires:continue
            existing=orders.get(directive['agent_id'])
            if existing is None or existing['expires_at']<expires:orders[directive['agent_id']]=directive
        return orders

    def reset_episode(self,episode_id):
        self.episode=episode_id;self.jobs={};self.scan={};self.scan_cursor=0
        self.failures=[];self.previous=None
        self.blocked_agents=set()
        self.known_surfaces=()
        self.local_obstacles={}
        self.home_positions={}
        self.route_failures=[]
        self.static_yields={}
        self.traffic_holds={}
        self.reconfirm_after={}

    def _released_jobs(self, observation):
        now = observation['time']
        for agent in observation['agents']:
            job = self.jobs.get(agent['id'])
            if job is None or agent['status'] != 'failed' or agent.get('physical', {}).get('carrying'):
                continue
            if job.target:
                # Only delivered state invalidates the old confirmation. The
                # actual drop position still has to come from a sensor report.
                observed = agent.get('freshness', {}).get('position', {}).get('observed_at')
                self.reconfirm_after[job.target] = now if observed is None else observed
            job.target = None
            job.phase = 'scan' if agent['kind'] == 'aerial' else 'choose'
            if not job.pending:
                job.charge_station = None
        for target in observation['targets']:
            cutoff = self.reconfirm_after.get(target['id'])
            observed = target.get('observed_at')
            if cutoff is not None and observed is not None and cutoff < observed <= now and target['status'] == 'confirmed':
                del self.reconfirm_after[target['id']]

    def decide(self,observation):
        if self.episode!=observation['episode_id']:
            self.reset_episode(observation['episode_id'])
        agents=observation['agents'];known={t['id']:t for t in observation['targets']}
        self.known_surfaces=observed_surfaces(observation)
        announced=observation.get('metaevolution',{}).get('announced_map')
        if announced is None:raise ValueError('FixedWorkflow requires a declared spatial-map adapter')
        self.route_failures=[]
        self._released_jobs(observation)
        for a in agents:
            job=self.jobs.setdefault(a['id'],Job('scan' if a['kind']=='aerial' else 'choose'))
            if a['kind']=='ground' and a.get('position') and not a.get('physical',{}).get('carrying'):
                base=announced.get('base',{});low=base.get('min');high=base.get('max')
                if low and high and all(low[i]<=a['position'][i]<=high[i] for i in (0,1)):
                    self.home_positions.setdefault(a['id'],list(a['position']))
        outgoing=[];effects=[];reconciliations=[];directive_checks=[]
        directives=self.hold_orders(observation)
        traffic_events=self._coordinate_ground_yields(observation,directives)
        disputes={r.get('target_id') for r in observation.get('metaevolution',{}).get('contradictions',())}
        disputes.update(self.reconfirm_after)
        exit_in_use=any(self.jobs[a['id']].pending and self.jobs[a['id']].using_dock_exit
                        for a in agents if a['kind']=='ground' and a['status']!='failed')
        exit_departures=set()

        def departure_order(agent):
            physical=agent.get('physical',{})
            exit_points=physical.get('dock_exit_waypoints')
            at_dock=agent['kind']=='ground' and physical.get('at_dock') and exit_points and agent.get('position')
            if not at_dock:return (0,0.)
            return (1,math.dist(agent['position'][:2],exit_points[-1][:2]))

        for a in sorted(agents,key=departure_order):
            command=None;next_phase=None
            job=self.jobs[a['id']]
            directive=directives.get(a['id'])
            if directive is not None:
                physical=a.get('physical',{})
                if a['status'] in ('failed','offline','unknown') or not self.available(a,'hold'):
                    outcome='agent_unavailable'
                elif physical.get('state') in ('loading','unloading') or (job.pending and job.action in ('pickup','handover','charge')):
                    outcome='waiting_for_safe_service_boundary'
                elif job.action=='hold' and (job.pending or physical.get('stop_reason')=='external_hold'):
                    outcome='retained_hold'
                else:
                    outgoing.append({'agent_id':a['id'],'action':'hold','parameters':{}})
                    effects.append((a['id'],None));outcome='proposed_hold'
                directive_checks.append({'directive_id':directive.get('id'),'agent_id':a['id'],'outcome':outcome})
                continue
            if a['id'] in self.traffic_holds:
                physical=a.get('physical',{})
                if self.available(a,'hold') and not (job.action=='hold' and (job.pending or physical.get('stop_reason')=='external_hold')):
                    outgoing.append({'agent_id':a['id'],'action':'hold','parameters':{}})
                    effects.append((a['id'],None))
                continue
            if (a['id'] in self.blocked_agents or a['id'] in self.scenario_reserved or
                a['kind'] not in ('ground','aerial') or a['status'] in ('offline','unknown','charging') or
                a.get('communication',{}).get('reachable') is False):continue
            if a['status']=='failed' and not self.available(a,'charge'):continue
            if job.pending and job.acknowledgement_unknown_at is not None:
                evidence=self._reconcile(a,job,known)
                if evidence is None:continue
                reconciliations.append(evidence)
            if job.pending:
                physical=a.get('physical',{})
                reason=physical.get('stop_reason')
                active_id=physical.get('active_command_id')
                stationary_yield=self._stationary_yield(observation,a)
                if (self.automatic_route_recovery and job.action=='follow_route'
                        and active_id==f'{job.pending}:{job.pending_index}' and
                        (reason in ('obstacle_on_route','hazard_on_route') or stationary_yield)
                        and self.available(a,'hold')):
                    blocker=physical.get('route_blocker')
                    if reason=='obstacle_on_route' and blocker:
                        try:Box.parse(blocker)
                        except ValueError:pass
                        else:
                            stored=self.local_obstacles.setdefault(a['id'],[])
                            if blocker not in stored:stored.append(deepcopy(blocker))
                            del stored[:-64]
                    outgoing.append({'agent_id':a['id'],'action':'hold','parameters':{}})
                    effects.append((a['id'],None))
                continue
            needs_charge,charge=self._charge_command(observation,announced,a,job)
            if needs_charge:
                if charge:
                    uses_exit=a['kind']=='ground' and a.get('physical',{}).get('at_dock') and charge['action']=='follow_route'
                    if uses_exit and exit_in_use:continue
                    if uses_exit:
                        exit_in_use=True;exit_departures.add(a['id'])
                    outgoing.append(charge);effects.append((a['id'],None))
                continue
            if a['kind']=='aerial':
                suspects=[t for t in known.values() if (t['status']=='suspected' or t['id'] in disputes) and t.get('position') and
                          math.dist(a['position'],t['position'])<40]
                if suspects and self.available(a,'inspect'):
                    target=min(suspects,key=lambda t:(math.dist(a['position'],t['position']),t['id']))
                    command={'agent_id':a['id'],'action':'inspect','parameters':{'target_id':target['id']}}
                elif self.available(a,'follow_route'):
                    goal=self._scan_goal(a,announced)
                    if goal is None:continue
                    try:points=self._route(announced,a,agents,goal)
                    except RouteFailure:continue
                    command={'agent_id':a['id'],'action':'follow_route','parameters':{'waypoints':points}}
            elif a['kind']=='ground':
                at_dock=a.get('physical',{}).get('at_dock') and a['physical'].get('dock_exit_waypoints')
                if exit_in_use and (job.phase=='depart' or (job.phase=='choose' and at_dock)):
                    continue
                if job.phase=='choose':
                    reserved={j.target for j in self.jobs.values() if j.target}
                    choices=[t for t in known.values() if t['status']=='confirmed' and
                             t.get('position') and t.get('evacuation_state','waiting')=='waiting' and
                             t['id'] not in reserved and t['id'] not in disputes]
                    selected=self._choose_target(a,choices)
                    if selected is None:
                        unconfirmed = [t for t in known.values() if t['id'] in self.reconfirm_after and
                                       t['id'] not in reserved and t.get('position') and self.available(a, 'inspect')]
                        selected = min(unconfirmed, key=lambda t: (math.dist(a['position'], t['position']), t['id']), default=None)
                    if selected is None:continue
                    job.target=selected['id']
                    job.phase='depart' if at_dock else 'approach'
                target = known.get(job.target)
                if job.phase in ('approach', 'pickup') and (not target or target['status'] != 'confirmed' or
                                                           not target.get('position') or job.target in disputes):
                    if (target and target.get('position') and math.dist(a['position'], target['position']) <= 16 and
                            self.available(a, 'inspect')):
                        outgoing.append({'agent_id': a['id'], 'action': 'inspect', 'parameters': {'target_id': job.target}})
                        effects.append((a['id'], 'approach'))
                    elif target and target.get('position') and job.target in self.reconfirm_after:
                        parameters = self._approach_target(announced, a, agents, target['position'], inspect=True)
                        if parameters and self.available(a, 'follow_route'):
                            outgoing.append({'agent_id': a['id'], 'action': 'follow_route', 'parameters': parameters})
                            effects.append((a['id'], 'approach'))
                    else:
                        job.target, job.phase = None, 'choose'
                    continue
                if job.phase=='depart' and self.available(a,'follow_route'):
                    command={'agent_id':a['id'],'action':'follow_route',
                             'parameters':{'waypoints':a['physical']['dock_exit_waypoints']}}
                    exit_in_use=True;exit_departures.add(a['id'])
                    next_phase='approach'
                elif job.phase=='approach' and job.target in known and self.available(a,'follow_route'):
                    parameters = self._approach_target(announced, a, agents, target['position'])
                    if parameters is None:continue
                    command={'agent_id':a['id'],'action':'follow_route','parameters':parameters}
                    next_phase='pickup'
                elif job.phase=='pickup' and self.available(a,'pickup'):
                    if math.dist(a['position'][:2], target['position'][:2]) > 3.7:
                        job.phase = 'approach'
                        continue
                    velocity=a.get('physical',{}).get('velocity_m_s',[0,0,0])
                    if math.dist(velocity,[0,0,0])>.2:continue
                    command={'agent_id':a['id'],'action':'pickup','parameters':{'target_id':job.target}};next_phase='return'
                elif job.phase=='return' and self.available(a,'follow_route'):
                    goal=(*handover_xy(announced),a['position'][2])
                    try:points=self._route(announced,a,agents,goal)
                    except RouteFailure:continue
                    command={'agent_id':a['id'],'action':'follow_route','parameters':{'waypoints':points}};next_phase='handover'
                elif job.phase=='handover' and self.available(a,'handover'):
                    velocity=a.get('physical',{}).get('velocity_m_s',[0,0,0])
                    if math.dist(velocity,[0,0,0])>.2:continue
                    command={'agent_id':a['id'],'action':'handover','parameters':{'station_id':'rescue-base'}};next_phase='park'
                elif job.phase=='park' and self.available(a,'follow_route'):
                    home=a.get('physical',{}).get('dock_position_m') or self.home_positions.get(a['id'])
                    if home is None:
                        self.route_failures.append({'agent_id':a['id'],'phase':'park',
                            'position':list(a['position']),'goal':None,'reason':'no_delivered_home_position'})
                        continue
                    try:points=self._parking_route(announced,a,agents,home)
                    except RouteFailure:continue
                    command={'agent_id':a['id'],'action':'follow_route','parameters':{'waypoints':points}};next_phase='choose'
            if command is not None:
                outgoing.append(command);effects.append((a['id'],next_phase))
        accepted=observation.get('metaevolution',{}).get('plan',{}).get('accepted_configuration',{})
        initial=self.select_initial_scenario and not accepted.get('scenario_ids') and not self.previous
        roles={a['id']:'scout' if a['kind']=='aerial' else 'rescuer' for a in agents if a['kind'] in ('aerial','ground')}
        result=decision(observation,commands=outgoing,
            operation='select' if initial else 'keep',
            selected={'scenario_ids':['coverage_search'],'parameters':{},'synthesized_scenario':None} if initial else None,
            roles=roles if initial else None,previous=self.previous)
        result['explanation']['reason_codes']=[self.reason_code]
        if reconciliations:result['metaevolution']={'execution_reconciliation':reconciliations}
        if directive_checks:result.setdefault('metaevolution',{})['directive_checks']=directive_checks
        if traffic_events:result.setdefault('metaevolution',{})['traffic_coordination']=traffic_events
        if self.route_failures:result.setdefault('metaevolution',{})['workflow']={'route_failures':self.route_failures}
        for index,(owner,next_phase) in enumerate(effects):
            job=self.jobs[owner];job.pending=result['decision_id'];job.pending_index=index;job.next_phase=next_phase
            job.using_dock_exit=owner in exit_departures or (job.using_dock_exit and outgoing[index]['action']=='hold')
            job.action=outgoing[index]['action'];job.acknowledgement_unknown_at=None
        self.last_decision=result
        return result


class LocalReactive(FixedWorkflow):
    """Local navigation and service rules on the same physical executor."""
    select_initial_scenario=False
    reason_code='local_reactive_rules'

    def _scan_goal(self,agent,announced):
        path=self._scan_path(announced)
        if not path:return None
        visited=self.scan.setdefault(agent['id'],set())
        if len(visited)==len(path):visited.clear()
        x,y,_=agent['position']
        remaining=(point for point in path if point not in visited)
        selected=min(remaining,key=lambda point:(math.hypot(x-point[0],y-point[1]),point))
        visited.add(selected)
        return selected
