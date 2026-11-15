"""A* over announced/observed geometry only. Coordinates and costs use metres.

The current city ground is one flat layer. Layered terrain must supply its
own surface graph; this module does not invent unseen slopes or tunnels.
Flight uses full 3D clearance, with a cruise route before bounded voxel A*.
"""
from __future__ import annotations

from dataclasses import dataclass
import heapq
import itertools
import math
import time


class RouteFailure(ValueError):
    pass


# MRAgentSafety adds 65 cm to the ground pair's physical radii. Allow
# another 25 cm for tracking error at bends and the folded ramp.
GROUND_PEER_NATIVE_MARGIN_M = .65
GROUND_PEER_MARGIN_M = GROUND_PEER_NATIVE_MARGIN_M + .25


def handover_xy(announced_map):
    """The vehicle service point is on the apron south of the base node."""
    x, y, _ = announced_map['base_position']
    return x, y - 3.7


def point(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 3 or
        any(type(v) not in (int, float) or not math.isfinite(v) for v in value)):
        raise ValueError('Expected three finite spatial numbers')
    return tuple(float(v) for v in value)


@dataclass(frozen=True)
class Box:
    minimum: tuple
    maximum: tuple

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict) or data.get('kind') != 'box':
            raise ValueError('Only declared box geometry is supported')
        lo, hi = point(data['min']), point(data['max'])
        if any(lo[i] > hi[i] for i in range(3)):
            raise ValueError('Inverted spatial bounds')
        return cls(lo, hi)

    def interval(self, a, b, radius=0, half_height=None):
        """Exact slab intersection, including touching, without sampling gaps."""
        low, high = 0., 1.
        for axis in range(3):
            extent = radius if axis < 2 or half_height is None else half_height
            lower, upper = self.minimum[axis]-extent, self.maximum[axis]+extent
            delta = b[axis]-a[axis]
            if abs(delta) < 1e-12:
                if a[axis] < lower or a[axis] > upper:
                    return None
            else:
                t1, t2 = (lower-a[axis])/delta, (upper-a[axis])/delta
                low, high = max(low, min(t1, t2)), min(high, max(t1, t2))
                if low > high:
                    return None
        return low, high


@dataclass(frozen=True)
class StreetBuilding:
    """Declared rotated footprint with a vertical envelope."""
    minimum: tuple
    maximum: tuple
    center: tuple
    axes: tuple
    local_bounds: Box

    @classmethod
    def parse(cls,building):
        envelope=Box.parse(building['bounds']);form=building['footprint']
        center,half,angle=form['center'],form['half'],form['yaw']
        if (len(center)!=2 or len(half)!=2 or any(type(v) not in (int,float) or not math.isfinite(v)
                for v in [*center,*half,angle]) or min(half)<=0):raise ValueError('Invalid rotated footprint')
        yaw=math.radians(angle);c,s=math.cos(yaw),math.sin(yaw)
        return cls(envelope.minimum,envelope.maximum,tuple(center),((c,s),(-s,c)),
                   Box((-half[0],-half[1],envelope.minimum[2]),(half[0],half[1],envelope.maximum[2])))

    def interval(self,a,b,radius=0,half_height=None):
        def local(p):
            x,y=p[0]-self.center[0],p[1]-self.center[1]
            return (*(x*u+y*v for u,v in self.axes),p[2])
        return self.local_bounds.interval(local(a),local(b),radius,half_height)


@dataclass(frozen=True)
class Route:
    points: tuple
    distance_m: float
    weighted_distance_m: float
    expanded: int
    wall_s: float


@dataclass(frozen=True)
class ObservedSurface:
    bounds: Box
    ground_blocked: bool
    cost: float
    visibility: float
    aerial_blocked: bool = False
    restriction: bool = False


def observed_surfaces(observation):
    """Extract measured geometry from delivered zones, independent of ID/order."""
    surfaces = set()
    now = observation['time']
    for zone in observation.get('zones', ()):
        measured = zone.get('surface')
        geometry = zone.get('geometry')
        if zone.get('type') == 'restricted' and isinstance(geometry, dict) and geometry.get('type') == 'box':
            access = zone.get('access', {})
            allowed = access.get('allowed_kinds') if isinstance(access, dict) else None
            if isinstance(allowed, list):
                try:
                    bounds = Box.parse({'kind': 'box', 'min': geometry.get('min'), 'max': geometry.get('max')})
                except ValueError:
                    continue
                if 'ground' not in allowed or 'aerial' not in allowed:
                    surfaces.add(ObservedSurface(bounds, 'ground' not in allowed, 1., 1., 'aerial' not in allowed, True))
            continue
        received = zone.get('received_at')
        if not isinstance(measured, dict) or not isinstance(geometry, dict):
            continue
        if type(received) not in (int, float) or not math.isfinite(received) or not 0 <= received <= now:
            continue
        if measured.get('active') is not True or geometry.get('type') != 'box':
            continue
        blocked = measured.get('ground_blocked')
        cost = measured.get('surface_multiplier')
        visibility = measured.get('visibility')
        if (type(blocked) is not bool or type(cost) not in (int, float) or not math.isfinite(cost) or cost < 1
                or type(visibility) not in (int, float) or not 0 <= visibility <= 1):
            continue
        try:
            bounds = Box.parse({'kind': 'box', 'min': geometry.get('min'), 'max': geometry.get('max')})
        except ValueError:
            continue
        if any(not 0 < bounds.maximum[i]-bounds.minimum[i] <= 5.000001 for i in range(2)):
            continue
        surfaces.add(ObservedSurface(bounds, blocked, float(cost), float(visibility)))
    orbital=observation.get('metaevolution',{}).get('orbital_observation')
    if isinstance(orbital,dict):
        measured=orbital.get('observed_at');received=orbital.get('received_at')
        if (type(measured) in (int,float) and type(received) in (int,float) and
            0<=measured<=received<=now and now-measured<=10):
            for sample in orbital.get('visible_surface_samples',()):
                if not isinstance(sample,dict):continue
                try:x,y,_=point(sample.get('position_m'))
                except ValueError:continue
                water=sample.get('water_depth_m');visibility=sample.get('visibility')
                if (type(water) not in (int,float) or not 0<=water<=20 or
                    type(visibility) not in (int,float) or not 0<=visibility<=1):continue
                bounds=Box((x-2.5,y-2.5,0),(x+2.5,y+2.5,3))
                surfaces.add(ObservedSurface(bounds,water>.24,1.+min(1.,2.*water),visibility))
    return tuple(sorted(surfaces, key=lambda s: (s.bounds.minimum, s.bounds.maximum, s.ground_blocked,
                                                s.aerial_blocked, s.restriction, s.cost, s.visibility)))


class NavigationMap:
    def __init__(self, announced_map, *, observed_obstacles=(), surfaces=(), parked_ground_peers=(), step_m=2.):
        if type(step_m) not in (int, float) or not math.isfinite(step_m) or step_m <= 0:
            raise ValueError('step_m must be finite and positive')
        self.bounds = Box.parse(announced_map['bounds'])
        self.announced=announced_map
        self.step = float(step_m)
        self.parked_ground_peers = tuple(parked_ground_peers)
        self.obstacles = []
        for key in ('buildings', 'facilities', 'fixed_obstacles'):
            self.obstacles.extend(StreetBuilding.parse(item) if 'footprint' in item else Box.parse(item['bounds'])
                                  for item in announced_map.get(key, ()))
        for item in announced_map.get('features', ()):
            self.obstacles.extend(StreetBuilding.parse({'bounds':box,'footprint':box['footprint']})
                                  if 'footprint' in box else Box.parse(box) for box in item.get('obstacles', ()))
        self.obstacles.extend(Box.parse(box) for box in observed_obstacles)
        self.ground_only = set();self.air_only = set();self.restrictions = set()
        for surface in surfaces:
            if not (surface.ground_blocked or surface.aerial_blocked):continue
            bounds=surface.bounds
            if surface.restriction:
                low=tuple(max(a,b) for a,b in zip(bounds.minimum,self.bounds.minimum))
                high=tuple(min(a,b) for a,b in zip(bounds.maximum,self.bounds.maximum))
                if any(a>=b for a,b in zip(low,high)):continue
                bounds=Box(low,high)
            index=len(self.obstacles)
            if not surface.aerial_blocked:self.ground_only.add(index)
            if not surface.ground_blocked:self.air_only.add(index)
            if surface.restriction:self.restrictions.add(index)
            self.obstacles.append(bounds)
        self.surfaces = []
        for surface in announced_map.get('surfaces', ()):
            cost = surface.get('cost', 1.)
            if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 1:
                raise ValueError('Surface cost must be finite and at least one')
            bounds = Box.parse(surface['bounds'])
            self.surfaces.append((bounds, float(cost), False))
        self.surfaces.extend((surface.bounds, surface.cost, True) for surface in surfaces if surface.cost > 1)
        self.visibility_surfaces = [surface for surface in surfaces if surface.visibility < 1]
        self.bin_size = 20.
        self.index = self._spatial_index(self.obstacles)
        self.cost_index = self._spatial_index(box for box, _, _ in self.surfaces)
        self.visibility_index = self._spatial_index(surface.bounds for surface in self.visibility_surfaces)
        self.street_nodes={};self.street_edges=[];self.street_links={};self.street_index={}
        if 'road_graph' in announced_map:
            graph=announced_map['road_graph']
            self.street_nodes={n['id']:(*n['position'][:2],self.ground_z(*n['position'][:2])) for n in graph['nodes']}
            self.street_links={key:[] for key in self.street_nodes}
            envelopes=[]
            for edge in graph['edges']:
                u,v=edge['from'],edge['to'];a,b=self.street_nodes[u],self.street_nodes[v]
                width=edge['width_m'];self.street_edges.append((u,v,width))
                self.street_links[u].append((v,width));self.street_links[v].append((u,width))
                envelopes.append(Box(tuple(min(x,y) for x,y in zip(a,b)),tuple(max(x,y) for x,y in zip(a,b))))
            self.street_index=self._spatial_index(envelopes)

    def _bins(self, low, high):
        for x in range(math.floor(low[0]/self.bin_size), math.floor(high[0]/self.bin_size)+1):
            for y in range(math.floor(low[1]/self.bin_size), math.floor(high[1]/self.bin_size)+1):
                yield (x, y)

    def _spatial_index(self, boxes):
        index = {}
        for i, box in enumerate(boxes):
            for cell in self._bins(box.minimum, box.maximum):
                index.setdefault(cell, []).append(i)
        return index

    def _nearby(self, index, a, b, padding=0):
        if not index:
            return set()
        low = tuple(min(a[i], b[i])-padding for i in range(2))
        high = tuple(max(a[i], b[i])+padding for i in range(2))
        return {i for cell in self._bins(low, high) for i in index.get(cell, ())}

    def clear(self, a, b, radius, half_height, *, aerial=False):
        for p in (a, b):
            if any(not self.bounds.minimum[i] <= p[i] <= self.bounds.maximum[i] for i in range(3)):
                return False
        candidates = self._nearby(self.index, a, b, radius)
        for i in candidates:
            if i in (self.ground_only if aerial else self.air_only):continue
            overlap=self.obstacles[i].interval(a,b,radius,half_height)
            if overlap is None:continue
            if i in self.restrictions and overlap[0]==0 and overlap[1]<1:continue
            return False
        return True

    def _ground_clear(self, a, b, radius, height, *, precise_arrival=False):
        if not self.clear(a, b, radius, height):
            return False
        dx, dy = b[0] - a[0], b[1] - a[1]
        length_sq = dx * dx + dy * dy
        for (x, y), peer_radius in self.parked_ground_peers:
            ax, ay = a[0] - x, a[1] - y
            dot = ax * dx + ay * dy
            fraction = min(1., max(0., -dot / length_sq)) if length_sq else 0.
            gap = math.hypot(ax + dx * fraction, ay + dy * fraction)
            hard_radius = radius + peer_radius
            margin = GROUND_PEER_NATIVE_MARGIN_M + .02 if precise_arrival else GROUND_PEER_MARGIN_M
            if gap >= hard_radius + margin:
                continue
            # The rover can start inside the extra margin at its own dock.
            # A straight departure is safe when its distance only increases.
            if gap >= hard_radius and dot >= 0 and length_sq:
                continue
            return False
        return True

    def sector_visibility(self, center, half_width=25.):
        low = tuple(v-half_width for v in center)
        high = tuple(v+half_width for v in center)
        if not self.visibility_surfaces:
            return 1.
        attenuation = 0.
        for i in sorted(self._nearby(self.visibility_index, low, high)):
            surface = self.visibility_surfaces[i]
            bounds = surface.bounds
            width, height = (max(0., min(high[d], bounds.maximum[d])-max(low[d], bounds.minimum[d])) for d in range(2))
            attenuation += width*height*(1-surface.visibility)
        return max(0., 1.-attenuation/(4*half_width**2))

    def cost(self, a, b, *, aerial=False):
        distance = math.dist(a, b)
        if aerial or not self.surfaces:
            return distance
        # Surface boxes describe ground footprint, independently of body-centre Z.
        ground_a, ground_b = (*a[:2], 0.), (*b[:2], 0.)
        cuts, intervals = {0., 1.}, []
        for i in self._nearby(self.cost_index, a, b):
            box, weight, dynamic = self.surfaces[i]
            slab = Box((box.minimum[0], box.minimum[1], -math.inf),
                       (box.maximum[0], box.maximum[1], math.inf)).interval(ground_a, ground_b)
            if slab is not None:
                cuts.update(slab)
                intervals.append((*slab, weight, dynamic))
        cuts = sorted(cuts)
        weighted = 0.
        for lo, hi in zip(cuts, cuts[1:]):
            mid = (lo+hi)/2
            fixed = max((w for lower, upper, w, dynamic in intervals if not dynamic and lower <= mid <= upper), default=1.)
            measured = max((w for lower, upper, w, dynamic in intervals if dynamic and lower <= mid <= upper), default=1.)
            weighted += (hi-lo)*fixed*measured
        return distance*weighted

    def ground_z(self,x,y):
        data=self.announced.get('navigation',{})
        if data.get('kind') not in ('road_surface_graph.v1','street_surface_graph.v2'):
            raise RouteFailure('ground_surface_graph_not_announced')
        base=self.announced['base']
        at_base=base['min'][0]<=x<=base['max'][0] and base['min'][1]<=y<=base['max'][1]
        return data['ground_clearance_m']+data['base_surface_z_m' if at_base else 'road_surface_z_m']

    def road_route(self,start,goal,*,radius_m=1.45,half_height_m=1.1,precise_stop=False):
        """Use actual declared streets/base instead of crossing raised curbs.

        Road graph heights describe the support surface. The suspension owns
        the body's realised Z; the exact current body pose remains the start.
        """
        start,goal=point(start),point(goal)
        if start == goal:
            if not self.clear(start, goal, radius_m, half_height_m):
                raise RouteFailure('endpoint_blocked_or_outside_announced_map')
            return Route((start,), 0., 0., 0, 0.)
        if self.street_nodes:return self._street_route(start,goal,radius_m,half_height_m,precise_stop)
        began=time.perf_counter();axes=self.announced['road_axes_m']
        if not axes:raise RouteFailure('empty_road_graph')
        half=self.announced['road_width_m']/2-radius_m
        if half<=0:raise RouteFailure('vehicle_does_not_fit_street')
        base=Box.parse(self.announced['base'])
        areas=[Box((base.minimum[0]+radius_m,base.minimum[1]+radius_m,-math.inf),
                   (base.maximum[0]-radius_m,base.maximum[1]-radius_m,math.inf))]
        lo,hi=self.bounds.minimum,self.bounds.maximum
        for axis in axes:
            areas.extend([Box((axis-half,lo[1],-math.inf),(axis+half,hi[1],math.inf)),
                          Box((lo[0],axis-half,-math.inf),(hi[0],axis+half,math.inf))])
        def allowed(a,b):
            intervals=sorted(slab for area in areas if (slab:=area.interval(a,b)) is not None)
            end=0.
            for lower,upper in intervals:
                if lower>end+1e-9:return False
                end=max(end,upper)
                if end>=1-1e-9:return True
            return False
        nodes={(i,j):(x,y,self.ground_z(x,y)) for i,x in enumerate(axes) for j,y in enumerate(axes)}
        nodes['start'],nodes['goal']=start,goal
        grid=[n for n in nodes if isinstance(n,tuple)]
        def connectors(p, *, arriving=False):
            return [n for n in sorted(grid,key=lambda n:math.dist(nodes[n],p))[:16]
                    if allowed(p,nodes[n]) and (self._ground_clear(nodes[n],p,radius_m,half_height_m,precise_arrival=precise_stop)
                    if arriving else self._ground_clear(p,nodes[n],radius_m,half_height_m))]
        start_links=connectors(start);goal_links=set(connectors(goal,arriving=True))
        if not start_links or not goal_links:raise RouteFailure('no_known_ground_access_port')
        serial=itertools.count();queue=[(math.dist(start,goal),next(serial),'start')]
        costs={'start':0.};parents={};visited=set()
        while queue:
            _,_,node=heapq.heappop(queue)
            if node in visited:continue
            if node=='goal':
                path=[goal]
                while node!='start':node=parents[node];path.append(nodes[node])
                path.reverse()
                # Keep street corners: smoothing across a raised sidewalk is
                # precisely the unsafe shortcut this graph excludes.
                return Route(tuple(path),sum(math.dist(a,b) for a,b in zip(path,path[1:])),costs['goal'],
                             len(visited),time.perf_counter()-began)
            visited.add(node)
            if node=='start':neighbours=start_links
            else:
                x,y=node
                neighbours=[(x+dx,y+dy) for dx,dy in ((-1,0),(1,0),(0,-1),(0,1))
                            if 0<=x+dx<len(axes) and 0<=y+dy<len(axes)]
                if node in goal_links:neighbours.append('goal')
            for other in neighbours:
                if other in visited:continue
                a,b=nodes[node],nodes[other]
                if not self._ground_clear(a,b,radius_m,half_height_m,precise_arrival=precise_stop and other=='goal'):continue
                total=costs[node]+self.cost(a,b)
                if total+1e-10<costs.get(other,math.inf):
                    costs[other],parents[other]=total,node
                    heapq.heappush(queue,(total+math.dist(b,goal),next(serial),other))
        raise RouteFailure('no_known_road_path')

    def _street_route(self,start,goal,radius,height,precise_stop):
        began=time.perf_counter()
        source,target=object(),object()
        nodes={**self.street_nodes,source:start,target:goal}
        base = Box.parse(self.announced['base'])
        sidestep = radius + max((r for _, r in self.parked_ground_peers), default=0.) + GROUND_PEER_MARGIN_M

        def on_apron(p):
            return all(base.minimum[axis] <= p[axis] <= base.maximum[axis] for axis in range(2))

        def links(p, *, arriving=False):
            def passable(a, b):
                if arriving:
                    return self._ground_clear(b, a, radius, height, precise_arrival=precise_stop and a == goal)
                return self._ground_clear(a, b, radius, height)

            nearest=[]
            for i in self._nearby(self.street_index,p,p,36):
                u,v,width=self.street_edges[i]
                if width<=2*radius:continue
                a,b=nodes[u],nodes[v];dx,dy=b[0]-a[0],b[1]-a[1];length=dx*dx+dy*dy
                if length<=1.e-10:continue
                fraction=max(0.,min(1.,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length))
                q=tuple(x+fraction*(y-x) for x,y in zip(a,b))
                nearest.append((math.dist(p,q),u,v,q))
            result={}
            for distance,u,v,q in sorted(nearest)[:12]:
                if distance > 36:
                    continue
                anchors = [q] if passable(p, q) else []
                if not anchors and self.parked_ground_peers and on_apron(p) and on_apron(q):
                    # A perpendicular projection can enter a parked vehicle's
                    # braking envelope. Try both directions on the same road.
                    for key in (u, v):
                        end = nodes[key]
                        span = math.dist(q, end)
                        if span == 0:
                            continue
                        t = min(1., sidestep / span)
                        shifted = tuple(a + t * (b - a) for a, b in zip(q, end))
                        if on_apron(shifted) and math.dist(p, shifted) <= 36 and passable(p, shifted):
                            anchors.append(shifted)
                for anchor in anchors:
                    for key in (u, v):
                        if not passable(anchor,nodes[key]):continue
                        cost=self.cost(p,anchor)+self.cost(anchor,nodes[key])
                        if key not in result or cost<result[key][0]:result[key]=(cost,anchor)
            return result

        start_links,goal_links=links(start),links(goal,arriving=True)
        direct=math.dist(start,goal)<12 and self._ground_clear(start,goal,radius,height,precise_arrival=precise_stop)
        if not direct and (not start_links or not goal_links):raise RouteFailure('no_known_street_access')
        serial=itertools.count();queue=[(math.dist(start,goal),next(serial),source)]
        costs={source:0.};parents={};visited=set()
        while queue:
            _,_,node=heapq.heappop(queue)
            if node in visited:continue
            if node is target:
                path=[goal]
                while node is not source:
                    node,via=parents[node]
                    if via is not None:path.append(via)
                    path.append(nodes[node])
                path.reverse()
                path=tuple(p for i,p in enumerate(path) if i==0 or p!=path[i-1])
                return Route(path,sum(math.dist(a,b) for a,b in zip(path,path[1:])),costs[target],len(visited),time.perf_counter()-began)
            visited.add(node)
            if node is source:
                neighbours=[(key,cost,via) for key,(cost,via) in start_links.items()]
                if direct:neighbours.append((target,self.cost(start,goal),None))
            else:
                a=nodes[node]
                neighbours=[(key,self.cost(a,nodes[key]),None) for key,width in self.street_links[node]
                            if width>2*radius and key not in visited and self._ground_clear(a,nodes[key],radius,height)]
                if node in goal_links:neighbours.append((target,*goal_links[node]))
            for other,edge_cost,via in neighbours:
                total=costs[node]+edge_cost
                if total+1.e-10<costs.get(other,math.inf):
                    costs[other],parents[other]=total,(node,via)
                    heapq.heappush(queue,(total+math.dist(nodes[other],goal),next(serial),other))
        raise RouteFailure('no_known_street_path')

    def route(self, start, goal, *, aerial=False, radius_m=1.45, half_height_m=1.1,
              cruise_altitude_m=25., max_expanded=100000):
        start, goal = point(start), point(goal)
        for name, value in (('radius_m', radius_m), ('half_height_m', half_height_m)):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(name+' must be finite and positive')
        if type(max_expanded) is not int or max_expanded < 1:
            raise ValueError('max_expanded must be a positive integer')
        began = time.perf_counter()
        def finish(path, expanded):
            return Route(tuple(path), sum(math.dist(a, b) for a, b in zip(path, path[1:])),
                         sum(self.cost(a, b, aerial=aerial) for a, b in zip(path, path[1:])),
                         expanded, time.perf_counter()-began)
        if not self.clear(start, start, radius_m, half_height_m, aerial=aerial) or not self.clear(goal, goal, radius_m, half_height_m, aerial=aerial):
            raise RouteFailure('endpoint_blocked_or_outside_announced_map')
        if start == goal:
            return finish([start], 0)
        if not aerial and abs(start[2]-goal[2]) > .01:
            raise RouteFailure('layered_ground_requires_a_declared_surface_graph')
        if aerial:
            if type(cruise_altitude_m) not in (int, float) or not math.isfinite(cruise_altitude_m):
                raise ValueError('cruise_altitude_m must be finite')
            altitude = max(start[2], goal[2], cruise_altitude_m)
            path = [start, (*start[:2], altitude), (*goal[:2], altitude), goal]
            path = [p for i, p in enumerate(path) if i == 0 or p != path[i-1]]
            if all(self.clear(a, b, radius_m, half_height_m, aerial=True) for a, b in zip(path, path[1:])):
                return finish(path, 0)
        elif not self.surfaces and self.clear(start, goal, radius_m, half_height_m):
            return finish([start, goal], 0)

        layers = sorted(set([start[2], goal[2], cruise_altitude_m])) if aerial else [start[2]]
        positions = {'start': start, 'goal': goal}
        def position(node):
            if node not in positions:
                positions[node] = (node[0]*self.step, node[1]*self.step, layers[node[2]])
            return positions[node]
        def near(p):
            x, y = math.floor(p[0]/self.step), math.floor(p[1]/self.step)
            k = layers.index(p[2])
            return [(x+dx, y+dy, k) for dx in (-1, 0, 1, 2) for dy in (-1, 0, 1, 2)]
        goal_neighbours = set(near(goal))
        def neighbours(node):
            if node == 'start':
                return near(start)
            x, y, k = node
            nodes = [(x+dx, y+dy, k) for dx, dy in itertools.product((-1, 0, 1), repeat=2) if dx or dy]
            if aerial:
                nodes += [(x, y, other) for other in (k-1, k+1) if 0 <= other < len(layers)]
            if node in goal_neighbours:
                nodes.append('goal')
            return nodes
        serial = itertools.count()
        queue = [(math.dist(start, goal), next(serial), 'start')]
        costs, parent, closed = {'start': 0.}, {}, set()
        expanded = 0
        while queue:
            _, _, node = heapq.heappop(queue)
            if node in closed:
                continue
            if node == 'goal':
                path = [goal]
                while node != 'start':
                    node = parent[node]
                    path.append(position(node))
                path.reverse()
                # Smoothing may not cut a corner or shortcut an expensive surface.
                result, i = [path[0]], 0
                while i < len(path)-1:
                    j = len(path)-1
                    while j > i+1:
                        if (self.clear(path[i], path[j], radius_m, half_height_m, aerial=aerial) and
                            self.cost(path[i], path[j], aerial=aerial) <=
                            sum(self.cost(a, b, aerial=aerial) for a, b in zip(path[i:j], path[i+1:j+1]))+1e-8):
                            break
                        j -= 1
                    result.append(path[j])
                    i = j
                return finish(result, expanded)
            closed.add(node)
            expanded += 1
            if expanded > max_expanded:
                raise RouteFailure('search_budget_exhausted')
            a = position(node)
            for nxt in neighbours(node):
                if nxt in closed:
                    continue
                b = position(nxt)
                if not self.clear(a, b, radius_m, half_height_m, aerial=aerial):
                    continue
                total = costs[node]+self.cost(a, b, aerial=aerial)
                if total+1e-10 < costs.get(nxt, math.inf):
                    costs[nxt], parent[nxt] = total, node
                    heapq.heappush(queue, (total+math.dist(b, goal), next(serial), nxt))
        raise RouteFailure('no_known_path')
