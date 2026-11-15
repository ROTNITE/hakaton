"""Irregular street fronts, service yards and mission placements."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import random

from contracts.protocol import ProtocolError
from environment.geometry import Footprint, SpatialIndex, box
from environment.streets import build_streets, clip_halfplane

VERSION = 'rescue-city-2.0'
DECORATED_VERSION = 'rescue-city-2.1'
STREET_PROP_VERSION = 'rescue-city-2.2'
HOUSE_HALF_M = 4.75
VEGETATION_REVISION = 3
CONTENT = Path(__file__).resolve().parents[1] / 'unreal/MetaRescue/Content'
VEGETATION_MANIFEST = CONTENT / 'Scenario/city-vegetation-v2-r3.json'
PROP_MANIFEST = CONTENT / 'Scenario/city-props-v1.json'


def _rect(x,y,hx,hy,height=1):
    return box((x-hx,y-hy,0),(x+hx,y+hy,height))


def _streets(graph):
    positions={node['id']:node['position'] for node in graph['nodes']}
    return [(positions[e['from']],positions[e['to']],e['width_m'],e['street_class']) for e in graph['edges']]


def _street_index(streets):
    index=SpatialIndex()
    for i,(a,b,width,_) in enumerate(streets):
        margin=width/2+1
        index.add(i,[min(x,y)-margin for x,y in zip(a,b)],[max(x,y)+margin for x,y in zip(a,b)])
    return index


def _center(outline):
    return tuple(sum(p[axis] for p in outline)/len(outline) for axis in (0,1))


def _background(graph,size,rng):
    # Four inhabited edges. The avenue axes continue through the outer ring.
    nodes={n['id']:n['position'] for n in graph['nodes']}
    areas=[]
    for entry in graph['entrances']:
        p=nodes[entry['node_id']];dx,dy=entry['outward']
        for row in (0,1):
            along=12+rng.uniform(0,4)
            while along<size-5:
                if abs(along-(p[1] if dx else p[0]))>12:
                    outside=19+row*15+rng.uniform(-1.7,1.7)
                    x=(0 if dx<0 else size)+dx*outside if dx else along
                    y=(0 if dy<0 else size)+dy*outside if dy else along
                    areas.append({'position':[x,y,0.],'yaw':90. if dx else 0.,'floors':rng.choice((2,3,3,4,5)),
                                  'variant':rng.choice((0,0,0,1,4))})
                along+=rng.uniform(10.7,15.3)
    return areas


def _outskirts(graph, size, rng):
    """Decorative lots outside the four mission edges, with clear gate approaches."""
    nodes = {node['id']: node['position'] for node in graph['nodes']}
    areas = []

    def add(x, y, yaw, kind, floors=0):
        areas.append({'position': [round(x, 3), round(y, 3), 0.], 'yaw': yaw,
                      'kind': kind, 'floors': floors, 'variant': rng.randrange(4)})

    for entry in graph['entrances']:
        x, y, _ = nodes[entry['node_id']]
        dx, dy = entry['outward']
        gate = y if dx else x
        for depth, density, heights in ((18, .85, (2, 2, 3, 4)),
                                         (47, .55, (1, 2, 2, 3)),
                                         (82, .25, (1, 1, 2))):
            start = rng.uniform(12, 19)
            while start < size - 11:
                lots = rng.choice((2, 2, 3, 4))
                use = rng.choices(('housing', 'green', 'service'),
                                  weights=(density, (1-density)*.75, (1-density)*.25))[0]
                block_depth = depth + rng.uniform(-min(depth*.27, 9), min(depth*.27, 9))
                yaw = (90. if dx else 0.) + rng.choice((-12., -7., 0., 7., 12.))
                for i in range(lots if use == 'housing' else 1):
                    along = start + i*13 + rng.uniform(-.65, .65)
                    if along >= size - 10 or abs(along - gate) < 15:
                        continue
                    if depth > 60 and abs(along - gate) > 75 and use != 'green':
                        continue
                    setback = block_depth + rng.uniform(-.8, .8)
                    px = (size if dx > 0 else 0) + dx*setback if dx else along
                    py = (size if dy > 0 else 0) + dy*setback if dy else along
                    add(px, py, yaw, use, rng.choice(heights) if use == 'housing' else 0)
                start += lots*13 + rng.uniform(5, 19)

    for x, dx in ((0, -1), (size, 1)):
        for y, dy in ((0, -1), (size, 1)):
            add(x + dx*rng.uniform(15, 25), y + dy*rng.uniform(19, 30),
                rng.choice((0., 90.)), 'green')
    return areas


def _lot_cover(block):
    polygon = block['outline']
    for a, b, width in block['fronts']:
        length = math.dist(a, b)
        nx, ny = (b[1]-a[1])/length, (a[0]-b[0])/length
        polygon = clip_halfplane(polygon, (nx, ny), nx*a[0]+ny*a[1] - width/2 - .9)
    return list(dict.fromkeys((round(x, 3), round(y, 3)) for x, y in polygon))


def _asset_catalog(path, expected_format):
    try:
        raw = path.read_bytes()
        manifest = json.loads(raw)
    except (OSError, ValueError) as error:
        raise ProtocolError('CONSTRAINT_VIOLATION', f'Missing verified city asset catalog {path.name}') from error
    if manifest.get('format') != expected_format:
        raise ProtocolError('CONSTRAINT_VIOLATION', f'Unsupported city asset catalog {path.name}')
    return {row['id']: row['bounds_m'] for row in manifest['models']}, hashlib.sha256(raw).hexdigest()


def _decorated_yards(lots, seed, open_lot, reserve, *, street_props):
    models, manifest_sha = _asset_catalog(VEGETATION_MANIFEST, f'metarescue.city-vegetation.v2.r{VEGETATION_REVISION}')
    detailing={'vegetation_revision':VEGETATION_REVISION,'vegetation_manifest_sha256':manifest_sha}
    if street_props:
        props,prop_sha=_asset_catalog(PROP_MANIFEST,'metarescue.city-props.v1')
        models.update(props)
        detailing['city_props_manifest_sha256']=prop_sha
    rng = random.Random(seed)
    covers, features = [], []

    def place(kind, model, x, y, yaw):
        dimensions = {'min': [-3, -2, 0], 'max': [3, 2, 2.9]} if kind == 'shelter' else models[model]
        low, high = dimensions['min'], dimensions['max']
        angle = math.radians(yaw)
        c, s = math.cos(angle), math.sin(angle)
        rotation = lambda dx,dy:(x+c*dx-s*dy, y+s*dx+c*dy)
        corners = [rotation(dx,dy) for dx in (low[0],high[0]) for dy in (low[1],high[1])]
        envelope = box([min(p[0] for p in corners), min(p[1] for p in corners), 0],
                       [max(p[0] for p in corners), max(p[1] for p in corners), high[2]])
        # The living tree has a physical trunk. Its leaf cards remain permeable.
        if model == 'street_linden':
            obstacle = _rect(x, y, .16, .16, 2.05)
        else:
            obstacle = envelope
            obstacle['footprint'] = {
                'center': list(rotation((low[0]+high[0])/2, (low[1]+high[1])/2)),
                'half': [(high[0]-low[0])/2, (high[1]-low[1])/2],
                'yaw': yaw,
            }
        if not open_lot(envelope, .55):
            return False
        # Use the same oriented clearance as final preflight. Expanding an
        # oriented box in its local frame is stricter at oblique corners.
        if 'footprint' in obstacle and not open_lot(
                envelope,.55,Footprint.from_area({**obstacle,'bounds':obstacle})):
            return False
        features.append({'id':f'yard-{len(features)}','kind':kind,'asset_id':model,
                         'position':[x,y,0.],'yaw':yaw,'obstacles':[obstacle]})
        reserve(envelope)
        return True

    for lot_index,(block, center, use) in enumerate(lots):
        outline = _lot_cover(block)
        if len(outline) < 3:
            continue
        cover='garden' if street_props and use=='housing' and lot_index%4 in (0,3) else use
        covers.append({'kind':cover,'vertices':outline})
        a, b, _ = max(block['fronts'], key=lambda f:math.dist(*f[:2]))
        yaw = round(math.degrees(math.atan2(b[1]-a[1], b[0]-a[0])), 3)
        places = [tuple(round(p+fraction*(q-p),3) for p,q in zip(center,vertex))
                  for fraction in (.30,.65,.81) for vertex in outline]
        rng.shuffle(places)
        if use == 'service':
            for x, y in [center, *places]:
                if place('shelter', 'utility_shelter', x, y, yaw):
                    break
        elif use == 'housing' and rng.random() < .30:
            for x, y in places:
                if place('shelter', 'utility_shelter', x, y, yaw):
                    break
        if street_props and (use=='service' or use=='housing' and lot_index%5==1):
            for x,y in places:
                if place('parked_vehicle','covered_car',x,y,yaw-90):
                    break
        if use == 'park':
            choices = ('street_linden','street_linden','pine_sapling','pine_sapling','pine_sapling','fallen_crown','dry_branches')
        elif use == 'service':
            choices = ('street_linden','stump_low','fallen_trunk','dry_branches')
        else:
            choices = ('street_linden','street_linden',rng.choice(('stump_split','fallen_crown','dry_branches','pine_sapling')))
        candidates = iter(places)
        for model in choices:
            for x,y in candidates:
                if place('vegetation', model, x, y, round(rng.uniform(-180,180),3)):
                    break
    return {**detailing,'lot_covers':covers}, features


def build_neighbourhood(settings,size,base,seed,*,person_clearance,revision='2.0',fixed_obstacles=()):
    decorated=revision in ('2.1','2.2')
    rng=random.Random(seed('fronts'))
    graph,blocks=build_streets(size,seed('roads'),
                              access_obstacles=tuple(Footprint.from_area(area) for area in fixed_obstacles))
    streets=_streets(graph);road_index=_street_index(streets)
    solids=[Footprint.from_area({'bounds':base})];solid_index=SpatialIndex()
    solid_index.add(0,base['min'],base['max'])

    def open_lot(bounds,margin=.35,footprint=None):
        if any(bounds['min'][i]<1 or bounds['max'][i]>size-1 for i in range(2)):return False
        indices=solid_index.query([n-margin for n in bounds['min']],[n+margin for n in bounds['max']])
        shape=footprint or Footprint.from_area({'bounds':bounds})
        if any(shape.intersects(solids[i],margin) for i in indices):return False
        padding=3. if decorated and footprint is not None else 0.
        low=[v-padding for v in bounds['min']];high=[v+padding for v in bounds['max']]
        for i in road_index.query(low,high):
            a,b,width,_=streets[i]
            if not shape.clear_segment(a,b,width/2+.65):return False
        return True

    def reserve(bounds,footprint=None):
        solid_index.add(len(solids),bounds['min'],bounds['max'])
        solids.append(footprint or Footprint.from_area({'bounds':bounds}))

    centers=[_center(b['outline']) for b in blocks]
    facility_position=None
    for x,y in sorted(centers,key=lambda p:math.dist(p,(size*.82,size*.8))):
        bounds=_rect(x,y,9.2,9.2,10)
        if open_lot(bounds,2.5):
            facility_position=[x,y,0.]
            facilities=[{'id':'unstable-bay','kind':'collapse_fixture','position':facility_position,'bounds':bounds}]
            reserve(bounds)
            break
    if facility_position is None:raise ProtocolError('CONSTRAINT_VIOLATION','No suitable collapse yard in generated district')

    houses=[];parcels=[];surfaces=[];features=[];lots=[]
    garden_rng=random.Random(seed('vegetation'))
    detail=settings.layout=='rescue_quarter'
    for index,(block,center) in enumerate(zip(blocks,centers)):
        # Separate residential, green and service blocks to break repeating lots.
        roll=rng.random()
        use='park' if roll<(.28 if settings.preset=='open' else .09) else 'service' if roll<.17 else 'housing'
        if block['access_end'] is not None:use='housing' if use=='housing' else 'service'
        if decorated:lots.append((block,center,use))
        density={'park':.15,'service':.66,'housing':1.}[use]
        if settings.preset=='open' and not detail:density*=.35
        damaged=rng.random()<(.66 if detail or settings.preset=='dynamic' else .44)
        direction=rng.randrange(len(block['fronts']))
        fronts=block['fronts'][direction:]+block['fronts'][:direction]
        def add_house(x,y,tx,ty,frontage):
            x,y=round(x,3),round(y,3)
            yaw=round(math.degrees(math.atan2(ty,tx)),3)
            half=HOUSE_HALF_M*(abs(tx)+abs(ty))
            floors=rng.choice((2,3,3,4,4,5)) if use=='housing' else rng.choice((1,2,3))
            bounds=_rect(x,y,half,half,floors*3+.7)
            form={'center':[x,y],'half':[HOUSE_HALF_M,HOUSE_HALF_M],'yaw':yaw}
            footprint=Footprint.from_area({'bounds':bounds,'footprint':form})
            if not open_lot(bounds,footprint=footprint):return False
            variant=rng.choices((0,1,2,3,4,5),weights=(3,2,2,2,2,2) if damaged else (8,2,1,1,2,1),k=1)[0]
            houses.append({'id':f'building-{len(houses)}','position':[x,y,0.],'floors':floors,'variant':variant,
                           'bounds':bounds,'footprint':form,'yaw':yaw,'block':index,'street_source':list(frontage)})
            reserve(bounds,footprint)
            return True
        for a,b,width in fronts:
            length=math.dist(a,b)
            if length<15:continue
            tx,ty=(b[0]-a[0])/length,(b[1]-a[1])/length
            setback=width/2+HOUSE_HALF_M+1.55
            count=max(1,math.floor((length-5)/12.4))
            for j in range(count):
                if rng.random()>density:continue
                along=(j+.5)*length/count+rng.uniform(-.35,.35)
                x=a[0]+tx*along-ty*setback;y=a[1]+ty*along+tx*setback
                frontage=[round(a[0]+tx*along-ty*(width/2+.8),3),round(a[1]+ty*along+tx*(width/2+.8),3)]
                add_house(x,y,tx,ty,frontage)
        if use=='housing' and (settings.preset!='open' or detail):
            # Rear wings share the direction of the longest frontage and leave
            # a gap through the block center and around the courtyard entrance.
            a,b,_=max(fronts,key=lambda f:math.dist(*f[:2]));length=math.dist(a,b)
            tx,ty=(b[0]-a[0])/length,(b[1]-a[1])/length
            extra=0
            for along,depth in ((-12,-8),(12,-8),(-12,8),(12,8),(-9,12),(9,12)):
                x=center[0]+tx*along-ty*depth;y=center[1]+ty*along+tx*depth
                if block['access_end'] is not None and math.dist((x,y),block['access_end'])<9:continue
                if any((b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0])<=0 for a,b,_ in fronts):continue
                frontage=[round(x+ty*5.6,3),round(y-tx*5.6,3)]
                if add_house(x,y,tx,ty,frontage):extra+=1
                if extra>=3:break
        # The center remains a place rather than a vacant intersection.
        x,y=center
        for span in (7.,5.,3.):
            bounds=_rect(x,y,span,span,.08)
            if not open_lot(bounds):continue
            parcels.append({'position':[x,y,0.],'use':use if use!='housing' else 'courtyard','extent_m':span})
            surface='grass' if use=='park' else 'paving' if use=='housing' else 'gravel'
            surfaces.append({'kind':surface,'bounds':bounds,'cost':1.18 if surface!='paving' else 1.})
            if decorated:
                break
            for dx,dy in ((-.58,-.35),(.52,.42)):
                tree_x,tree_y=x+span*dx,y+span*dy
                if garden_rng.random()>.85:continue
                variant=garden_rng.randrange(3);height=(5.5,6.5,7.5)[variant]
                envelope=_rect(tree_x,tree_y,2.2,2.2,height)
                if not open_lot(envelope):continue
                trunk=_rect(tree_x,tree_y,.24,.24,4.23)
                crown=box((tree_x-2.2,tree_y-2.2,2.2),(tree_x+2.2,tree_y+2.2,height))
                features.append({'id':f'tree-{len(features)}','kind':'tree','position':[tree_x,tree_y,0.],
                                 'height_m':height,'crown_radius_m':2.2,'model':variant,'yaw':garden_rng.uniform(0,360),
                                 'obstacles':[trunk,crown]})
                reserve(envelope)
            break

    detailing={}
    if decorated:
        detailing,features=_decorated_yards(lots,seed('yard-detail-2.1'),open_lot,reserve,street_props=revision=='2.2')
    people_rng=random.Random(seed('people'))
    choices=[(a,b,w) for a,b,w,_ in streets if math.dist(a,b)>7]
    clustered=sorted(choices,key=lambda edge:math.dist(edge[0][:2],(size*.52,size*.55)))[:max(18,len(choices)//12)]
    people=[];occupancy=SpatialIndex(person_clearance)
    for attempt in range(200000):
        if len(people)==settings.people:break
        pool=clustered if settings.preset=='clusters' and attempt<settings.people*20 and people_rng.random()<.8 else choices
        a,b,width=people_rng.choice(pool);length=math.dist(a,b)
        fraction=people_rng.uniform(.17,.83);side=people_rng.choice((-1,1));offset=side*(width/2-.86)
        x=round(a[0]+(b[0]-a[0])*fraction-(b[1]-a[1])*offset/length,3)
        y=round(a[1]+(b[1]-a[1])*fraction+(b[0]-a[0])*offset/length,3)
        if x<base['max'][0]+6 and y<base['max'][1]+6:continue
        low=(x-person_clearance,y-person_clearance);high=(x+person_clearance,y+person_clearance)
        if any(math.dist((x,y),people[i]['position'][:2])<person_clearance for i in occupancy.query(low,high)):continue
        candidate=_rect(x,y,1.1,1.1)
        footprint=Footprint.from_area({'bounds':candidate})
        if any(footprint.intersects(solids[i]) for i in solid_index.query(candidate['min'],candidate['max'])):continue
        occupancy.add(len(people),(x,y),(x,y))
        people.append({'id':len(people)+1,'position':[x,y,.06],'priority':people_rng.randrange(1,4),'available_at':0})
    if len(people)!=settings.people:raise ProtocolError('CONSTRAINT_VIOLATION','Insufficient irregular road shoulder space')

    relays=[];bins=defaultdict(list)
    for node in graph['nodes']:
        x,y,_=node['position'];bins[(int(x//90),int(y//90))].append((x,y))
    for (bx,by),points in sorted(bins.items()):
        x,y=min(points,key=lambda p:math.dist(p,(bx*90+45,by*90+45)))
        for dx,dy in ((7,7),(-7,7),(7,-7),(-7,-7)):
            rx,ry=x+dx,y+dy
            if open_lot(_rect(rx,ry,.8,.8)):
                relays.append({'id':f'relay-{bx}-{by}','kind':'relay','position':[rx,ry,3.],'range_m':180})
                break
    if decorated:
        detailing['background_revision'] = 2
        background = _outskirts(graph, size, random.Random(seed('edge')))
    else:
        background = _background(graph, size, random.Random(seed('edge')))
    return {'road_graph':graph,'buildings':houses,'people':people,'relays':relays,'facilities':facilities,**detailing,
            'features':features,'parcels':parcels,'surfaces':surfaces,'background':background}
