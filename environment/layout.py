"""Physical city layout generation, in metres. Never imported by controllers.

Presets, scale and fleet ranges follow v0.5.2. This is an explicitly different
3D layout model: road fronts and courtyards replace independent blocked cells.
Only public_map() may be included in a public observation; people are private.
"""
from __future__ import annotations

from collections import deque
from functools import lru_cache
import hashlib
import json
import math
import random
from pathlib import Path

from contracts.protocol import ProtocolError
from environment.competition import attach as attach_competition_annex
from environment.config import Settings
from environment.events import generate_tape
from environment.geometry import Footprint, SpatialIndex, box as _box, overlap as _overlap, segment_clear as _segment_clear
from environment.neighbourhood import VERSION as IRREGULAR_VERSION,DECORATED_VERSION,STREET_PROP_VERSION,build_neighbourhood

VERSION = 'rescue-city-1.1'
CELL_M = 10.0
ROAD_WIDTH_M = 8.5
HOUSE_WIDTH_M = 9.0
PERSON_CLEARANCE_M = 2.2  # circumscribes the 2.05m stretcher in any yaw
BASE_LAYOUT_REVISION = 3
BASE_ASSETS = Path(__file__).resolve().parents[1] / 'unreal/MetaRescue/Content/Scenario/base-assets-r1.json'


def stream_seed(seed: int, name: str, *, version=VERSION) -> int:
    return int.from_bytes(hashlib.sha256(f'{version}:{seed}:{name}'.encode()).digest()[:8], 'little')


def _base_plan(settings):
    dock_cols = min(8, settings.rescuers)
    dock_rows = math.ceil(settings.rescuers / dock_cols)
    pad_cols = min(8, settings.scouts)
    pad_rows = math.ceil(settings.scouts / pad_cols)
    pad_x = 32 + dock_cols * 3.5 + 8
    pad_y = 22 + (dock_rows - 1) * 12 + 12
    base_w = max(65., pad_x + (pad_cols - 1) * 4.5 + 8)
    base_h = max(40., pad_y + (pad_rows - 1) * 4.5 + 8)
    base = _box((0, 0, -.2), (base_w, base_h, .2))
    spawns = []
    for i in range(settings.rescuers):
        x, y = 32 + (i % dock_cols)*3.5, 22 + (i // dock_cols)*12
        spawns.append({'id': f'mobile-{i}', 'kind': 'ground', 'position': [x, y, .95],
                       'yaw': -90, 'exit': [[x, y-4, .95], [base_w-2, y-4, .95], [base_w-2, 10, .95]],
                       'dock': i, 'radius_m': 1.45})
    for i in range(settings.scouts):
        spawns.append({'id': f'mobile-{settings.rescuers+i}', 'kind': 'aerial',
                       'position': [pad_x+(i%pad_cols)*4.5, pad_y+(i//pad_cols)*4.5, .31],
                       'yaw': 0, 'radius_m': 1.65, 'pad': i})
    infrastructure=[
        {'id':'rescue-base','kind':'base_station','position':[20,22,0]},
        {'id':'charge-base','kind':'charging_station','position':[20,13,0]},
        {'id':'compute-base','kind':'compute_node','position':[15,22,0]},
        {'id':'sensor-base','kind':'sensor_node','position':[22,30,2]},
    ]
    if settings.resource_profile=='contest':
        infrastructure[1]['charger']={'kind':'ground','docking_distance_m':4.,'ports':1,
                                      'power_w':1200.,'capacity_wh':10000.}
        for spawn in spawns:
            if spawn['kind']=='aerial':
                infrastructure.append({'id':f"charge-pad-{spawn['pad']}",'kind':'charging_station',
                    'position':spawn['position'],'charger':{'kind':'aerial','agent_id':spawn['id'],
                    'docking_distance_m':1.5,'ports':1,'power_w':600.,'capacity_wh':600.}})
    return base,spawns,infrastructure


@lru_cache(maxsize=1)
def _base_asset_bounds():
    data = json.loads(BASE_ASSETS.read_bytes())
    if data.get('format') != 'metarescue.base-assets.r1':
        raise ValueError('Invalid base asset bounds format')
    return data['assemblies']


def _base_obstacles():
    placements = (
        ('medical-container', 'Medical', (20., 22., .13)),
        ('charge-generator', 'Generator', (15.2, 16.3, .13)),
        ('base-compute-cabinet', 'UtilityBox', (15., 22., .13)),
        ('base-sensor-mast', 'Sensor', (22., 30., .13)),
    )
    assets = _base_asset_bounds()
    result = []
    for identifier, asset, position in placements:
        bounds = assets[asset]
        low = [round(position[i] + bounds['min'][i] - .05, 4) for i in range(3)]
        high = [round(position[i] + bounds['max'][i] + .05, 4) for i in range(3)]
        result.append({'id': identifier, 'asset': asset, 'position': list(position), 'yaw': 0.,
                       'bounds': _box(low, high)})
    return result


def generate(settings: Settings, *, include_events=False) -> dict:
    size = int(settings.map_size * CELL_M)
    base,spawns,infrastructure=_base_plan(settings)
    city_versions={'2.0':IRREGULAR_VERSION,'2.1':DECORATED_VERSION,'2.2':STREET_PROP_VERSION}
    if settings.city_revision in city_versions or settings.layout=='rescue_quarter':
        revision=settings.city_revision if settings.city_revision in city_versions else '2.0'
        fixed_obstacles = _base_obstacles()
        if revision in ('2.1','2.2'):
            fixed_obstacles.extend([
                {'id':'van-service-lane','asset':'Van','position':[3.1,25.7,.08],'yaw':90.,
                 'bounds':_box((1.6,22.5,0),(4.6,35.5,2.8))},
                {'id':'base-lamp-south','asset':'Streetlight','position':[1.,17.5,.08],'yaw':0.,
                 'bounds':_box((.8,17.3,0),(1.2,17.7,5.5))},
                {'id':'base-lamp-north','asset':'Streetlight','position':[1.,35.8,.08],'yaw':0.,
                 'bounds':_box((.8,35.6,0),(1.2,36.,5.5))},
            ])
        def seed(name):return stream_seed(settings.seed,name,version=IRREGULAR_VERSION)
        parts=build_neighbourhood(settings,size,base,seed,person_clearance=PERSON_CLEARANCE_M,
                                  revision=revision,fixed_obstacles=fixed_obstacles)
        infrastructure.extend(parts.pop('relays'))
        data={'format':city_versions[revision],'base_layout_revision':BASE_LAYOUT_REVISION,
              'settings':{**settings.json(),'city_revision':revision},'cell_m':CELL_M,'size_m':size,
              'bounds':_box((0,0,-12),(size,size,90)),'base':base,'base_position':[20,22,0],
              'spawns':spawns,'infrastructure':infrastructure,'fixed_obstacles':fixed_obstacles,**parts}
        if settings.competition:attach_competition_annex(data)
        data['preflight']=preflight(data)
        if include_events:data['event_model']=generate_tape(data)
        return data
    rng = random.Random(stream_seed(settings.seed, 'parcels'))
    blocks=max(1,round((size-20)/46))
    axes=[round(10+i*(size-20)/blocks) for i in range(blocks+1)]
    base_w,base_h=base['max'][:2]
    facilities=[{'id':'unstable-bay','kind':'collapse_fixture','position':[size-35,size-35,.24],
                 'bounds':_box((size-50,size-50,0),(size-15,size-15,10))}]
    reserved=[base,*[f['bounds'] for f in facilities]]
    buildings, parcels, surfaces = [], [], []
    # Four street fronts enclose a usable courtyard. Balanced block widths
    # avoid an enormous empty final block; 9m models keep their physical size.
    density = .22 if settings.preset == 'open' else .91
    for ix in range(len(axes)-1):
        for iy in range(len(axes)-1):
            x0, x1, y0, y1 = axes[ix], axes[ix+1], axes[iy], axes[iy+1]
            xs=[x0+11,(x0+x1)/2,x1-11]
            ys=[y0+11,(y0+y1)/2,y1-11]
            for px,x in enumerate(xs):
                for py,y in enumerate(ys):
                    if px==1 and py==1:continue
                    bounds = _box((x-4.75, y-4.75, 0), (x+4.75, y+4.75, 15))
                    if any(_overlap(bounds,area,3) for area in reserved):
                        continue
                    variant = rng.randrange(6)
                    if rng.random() > density:
                        parcels.append({'position': [x, y, 0], 'use': 'garden' if rng.random()<.7 else 'service',
                                        'variant': rng.randrange(3)})
                        continue
                    floors = rng.randrange(2, 5)
                    bounds['max'][2] = floors * 3 + .7
                    buildings.append({'id': f'building-{len(buildings)}', 'position': [x, y, 0],
                                      'floors': floors, 'variant': variant, 'bounds': bounds,
                                      'yaw': 0 if py==0 else 180 if py==2 else 90 if px==0 else 270})
            parcels.append({'position': [(x0+x1)/2, (y0+y1)/2, 0], 'use': 'courtyard',
                            'variant': rng.randrange(3)})
    parcels=[p for p in parcels if not any(area['min'][0]-3<p['position'][0]<area['max'][0]+3 and
                                          area['min'][1]-3<p['position'][1]<area['max'][1]+3 for area in reserved)]
    # Neighbourhood dirt strips are traversable surfaces, not blocked streets.
    terrain_rng = random.Random(stream_seed(settings.seed, 'terrain'))
    for parcel in parcels:
        if terrain_rng.random() < (.7 if settings.preset == 'scarce' else .18):
            p=parcel['position']
            surfaces.append({'kind':'mud','bounds':_box((p[0]-3,p[1]-2,-.1),(p[0]+3,p[1]+2,.1)),
                             'cost':1.45})
    vegetation_rng=random.Random(stream_seed(settings.seed,'vegetation'))
    features=[]
    for parcel in parcels:
        if parcel['use'] in ('garden','courtyard') and vegetation_rng.random()<.72:
            p=[*parcel['position'][:2],.23];variant=vegetation_rng.randrange(3);height=(5.5,6.5,7.5)[variant]
            features.append({'id':f'tree-{len(features)}','kind':'tree','position':list(p),
                             'height_m':height,'crown_radius_m':2.2,'model':variant,
                             'yaw':vegetation_rng.uniform(0,360),
                             'obstacles':[_box((p[0]-.24,p[1]-.24,p[2]),(p[0]+.24,p[1]+.24,4.23)),
                                          _box((p[0]-2.2,p[1]-2.2,2.2),(p[0]+2.2,p[1]+2.2,height+p[2]))]})
    people_rng=random.Random(stream_seed(settings.seed, 'people'))
    people, occupied = [], set()
    person_cells={};attempts=0
    while len(people)<settings.people:
        attempts+=1
        if attempts>200000:
            raise ProtocolError('CONSTRAINT_VIOLATION','Not enough safe casualty placement space',
                                {'requested':settings.people,'placed':len(people)})
        vertical=people_rng.random()<.5
        cross=people_rng.choice(axes)
        along=round(people_rng.uniform(12,size-12)*2)/2
        # Clustered targets share a bounded neighbourhood, with no truth prior.
        if settings.preset=='clusters' and people_rng.random()<.8:
            cross=axes[min(len(axes)-1,max(1,len(axes)//2))]
            along=round(people_rng.uniform(size*.35,size*.65)*2)/2
        p=(cross+3.1,along) if vertical else (along,cross+3.1)
        if p in occupied or (p[0]<base_w+5 and p[1]<base_h+5):continue
        cell=(math.floor(p[0]/PERSON_CLEARANCE_M),math.floor(p[1]/PERSON_CLEARANCE_M))
        if any(math.dist(p,other)<PERSON_CLEARANCE_M for dx in (-1,0,1) for dy in (-1,0,1)
               for other in person_cells.get((cell[0]+dx,cell[1]+dy),[])):continue
        occupied.add(p)
        person_cells.setdefault(cell,[]).append(p)
        people.append({'id':len(people)+1,'position':[p[0],p[1],.06],
                       'priority':people_rng.randrange(1,4),'available_at':0})
    # Place real relay nodes at road intersections. Multi-hop rather than one
    # magic global base link is required for the far side of large districts.
    for ix,x in enumerate(axes[::2]):
        for iy,y in enumerate(axes[::2]):
            infrastructure.append({'id':f'relay-{ix}-{iy}','kind':'relay','position':[x-5,y-5,3],
                                   'range_m':180})
    data={'format':VERSION,'base_layout_revision':BASE_LAYOUT_REVISION,'settings':settings.json(),'cell_m':CELL_M,'size_m':size,
          'bounds':_box((0,0,-12),(size,size,90)), 'base':base,'base_position':[20,22,0],
          'road_axes_m':axes,'road_width_m':ROAD_WIDTH_M,'buildings':buildings,
          'parcels':parcels,'features':features,'surfaces':surfaces,'spawns':spawns,'people':people,
          'infrastructure':infrastructure,'facilities':facilities,'fixed_obstacles':_base_obstacles(),'preflight':None}
    if settings.competition:attach_competition_annex(data)
    data['preflight']=preflight(data)
    if include_events:data['event_model']=generate_tape(data)
    return data


def preflight(data):
    """Fail closed on unsupported placement and disconnected evacuation roads."""
    issues=[]
    bounds=data['bounds'];areas=[*data['buildings'],*data.get('facilities',[]),*data.get('fixed_obstacles',[])]
    boxes=[b['bounds'] for b in areas]
    footprints=[Footprint.from_area(a) for a in areas] if 'road_graph' in data else None
    for i,box in enumerate(boxes):
        if any(box['min'][d]<bounds['min'][d] or box['max'][d]>bounds['max'][d] for d in range(3)):
            issues.append(f'building {i} outside physical bounds')
    # Sweep by x, avoiding O(n²) work for the largest layout.
    active=[]
    for index,box in sorted(enumerate(boxes),key=lambda item:item[1]['min'][0]):
        active=[item for item in active if item[1]['max'][0]>box['min'][0]]
        for other,previous in active:
            if _overlap(box,previous) and (footprints is None or footprints[other].intersects(footprints[index])):
                issues.append(f'building overlap {other}/{index}')
        active.append((index,box))
    spawns=data['spawns'];parked_exit_checks=0
    if data.get('base_layout_revision',0)>=3:
        x,y,z=data['base_position'];handover=(x,y-3.7,z)
        if not all(_segment_clear(approach,handover,boxes,1.45) for approach in ((x-6,10,z),(x+8,10,z))):
            issues.append('base handover has an obstructed apron approach')
    for i,spawn in enumerate(spawns):
        p=spawn['position']; r=spawn['radius_m']
        if not all(bounds['min'][a]+r<=p[a]<=bounds['max'][a]-r for a in range(2)):
            issues.append(f'spawn outside map {spawn["id"]}')
        if not _segment_clear(p,p,boxes,r):issues.append(f'spawn intersects structure {spawn["id"]}')
        for other in spawns[:i]:
            if math.dist(p[:2],other['position'][:2])<r+other['radius_m']:
                issues.append(f'spawns overlap {spawn["id"]}/{other["id"]}')
        points=[p,*spawn.get('exit',[])]
        if any(not _segment_clear(a,b,boxes,r) for a,b in zip(points,points[1:])):
            issues.append(f'blocked base exit {spawn["id"]}')
        if spawn['kind']=='ground':
            for other in spawns:
                if other['id']==spawn['id']:continue
                q=other['position'];half=.4 if other['kind']=='aerial' else 1.1
                other_box=_box((q[0]-other['radius_m'],q[1]-other['radius_m'],q[2]-half),
                               (q[0]+other['radius_m'],q[1]+other['radius_m'],q[2]+half))
                for a,b in zip(points,points[1:]):
                    if max(a[2],b[2])+1.1<q[2]-half or min(a[2],b[2])-1.1>q[2]+half:continue
                    parked_exit_checks+=1
                    if not _segment_clear(a,b,[other_box],r):
                        issues.append(f'base exit {spawn["id"]} intersects parked agent {other["id"]}');break
    people=data.get('people',[]);person_cells={}
    if len({p['id'] for p in people})!=len(people):issues.append('duplicate casualty IDs')
    for person in people:
        p=person['position']
        if len(p)!=3 or not all(type(x) in (int,float) and math.isfinite(x) for x in p):
            issues.append('invalid casualty pose');continue
        if not all(bounds['min'][a]<=p[a]<=bounds['max'][a] for a in range(3)):
            issues.append('casualty outside map')
        cell=(math.floor(p[0]/PERSON_CLEARANCE_M),math.floor(p[1]/PERSON_CLEARANCE_M))
        if any(math.dist(p[:2],other)<PERSON_CLEARANCE_M for dx in (-1,0,1) for dy in (-1,0,1)
               for other in person_cells.get((cell[0]+dx,cell[1]+dy),[])):
            issues.append('casualty stretchers overlap')
        person_cells.setdefault(cell,[]).append(p[:2])
    if 'road_graph' in data:
        roads=data['road_graph'];positions={n['id']:n['position'] for n in roads['nodes']}
        if data['format'] in (DECORATED_VERSION,STREET_PROP_VERSION):
            for feature in data['features']:
                for obstacle in feature['obstacles']:
                    boxes.append(obstacle)
                    footprints.append(Footprint.from_area({**obstacle,'bounds':obstacle}))
        nodes=list(positions);graph={key:[] for key in nodes};index=SpatialIndex()
        for i,b in enumerate(boxes):index.add(i,b['min'],b['max'])
        if len(nodes)!=len(roads['nodes']) or len({tuple(p) for p in positions.values()})!=len(nodes):issues.append('duplicate street node')
        if len(roads['entrances'])!=4 or any(row['node_id'] not in positions for row in roads['entrances']):issues.append('missing street exits')
        bottom=[]
        for edge in roads['edges']:
            u,v=edge['from'],edge['to'];width=edge['width_m']
            if u not in positions or v not in positions or u==v or not 4.8<=width<=14:
                issues.append('invalid street segment');continue
            a,b=positions[u],positions[v]
            margin=width/2
            low=[min(x,y)-margin for x,y in zip(a,b)];high=[max(x,y)+margin for x,y in zip(a,b)]
            if any(not footprints[i].clear_segment(a,b,margin) for i in index.query(low,high)):
                issues.append(f'structure intersects street {u}/{v}');continue
            graph[u].append(v);graph[v].append(u)
            if a[1]==b[1]==10:bottom.append((min(a[0],b[0]),max(a[0],b[0])))
        for spawn in spawns:
            if spawn.get('exit') and not any(lo<=spawn['exit'][-1][0]<=hi for lo,hi in bottom):issues.append('dock exit does not reach street')
    else:
        axes=data['road_axes_m']; nodes=[(x,y) for x in axes for y in axes]
        graph={p:[] for p in nodes}
        for ix,x in enumerate(axes):
            for iy,y in enumerate(axes):
                for next_point in ([(axes[ix+1],y)] if ix+1<len(axes) else [])+([(x,axes[iy+1])] if iy+1<len(axes) else []):
                    if _segment_clear((x,y),next_point,boxes,1.45):
                        graph[(x,y)].append(next_point);graph[next_point].append((x,y))
    if not nodes:raise ProtocolError('CONSTRAINT_VIOLATION','World has no street nodes')
    seen={nodes[0]};queue=deque(seen)
    while queue:
        for neighbour in graph[queue.popleft()]:
            if neighbour not in seen:seen.add(neighbour);queue.append(neighbour)
    if len(seen)!=len(nodes):issues.append('evacuation road network is disconnected')
    if issues:raise ProtocolError('CONSTRAINT_VIOLATION','World preflight failed',{'issues':issues[:50]})
    return {'passed':True,'buildings':len(data['buildings']),'solid_parcels':len(boxes),'spawns':len(spawns),'road_nodes':len(nodes),
            'connected_nodes':len(seen),'parked_exit_checks':parked_exit_checks,'physical_collision_probe':'pending_native'}


def public_map(data):
    """Announced static map: no hidden people, future disturbances or RNG state."""
    fields=('format','base_layout_revision','cell_m','size_m','bounds','base','base_position','road_axes_m','road_width_m',
            'road_graph','buildings','features','facilities','fixed_obstacles','surfaces','infrastructure')
    result={key:data[key] for key in fields if key in data}
    if 'competition' in data:result['declared_zones']=data['competition']['zones']
    return result


def fingerprint(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
