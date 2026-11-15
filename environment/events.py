"""Private, method-independent event tapes for the physical 3D environment.

Nothing here is imported by the controller. Rates/timing derive from the selected
benchmark profile; placement and five-metre physics cells are explicitly 3D.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import math
import random

from contracts.protocol import ProtocolError
from environment.config import Settings,EVENT_DEFAULTS

VERSION='metarescue.events-3d.1.0'
CELL_M=5.
PERSISTENT={'collapse','fire','flood','mud','road_damage'}


def _seed(*parts):
    return int.from_bytes(hashlib.sha256(':'.join(map(str,parts)).encode()).digest()[:8],'little')


class Placement:
    def __init__(self,world):
        self.world=world;self.size=world['size_m'];self.base=world['base'];self.boxes=defaultdict(list)
        for building in [*world['buildings'],*world.get('facilities',[])]:
            box=building['bounds']
            for x in range(math.floor(box['min'][0]/20),math.floor(box['max'][0]/20)+1):
                for y in range(math.floor(box['min'][1]/20),math.floor(box['max'][1]/20)+1):self.boxes[x,y].append(box)
        self.buildings=sorted(world['buildings'],key=lambda b:(tuple(b['bounds']['min']),tuple(b['bounds']['max'])))
        self.axes=sorted(world.get('road_axes_m',()))
        self.shoulders=[]
        if 'road_graph' in world:
            graph=world['road_graph'];nodes={n['id']:n['position'] for n in graph['nodes']};samples=set();shoulders=set()
            for edge in graph['edges']:
                a,b=nodes[edge['from']],nodes[edge['to']];dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
                if length<6:continue
                divisions=max(2,math.ceil(length/8))
                for i in range(1,divisions):
                    x,y=a[0]+dx*i/divisions,a[1]+dy*i/divisions
                    if self.protected(x,y):continue
                    samples.add((round(x,3),round(y,3)))
                    for sign in (-1,1):
                        inset=sign*(edge['width_m']/2-.86)
                        shoulders.add((round(x-dy/length*inset,3),round(y+dx/length*inset,3)))
            self.ground=sorted(samples);self.shoulders=sorted(shoulders)
        else:
            self.ground=sorted({(round(x,3),round(y,3)) for axis in self.axes for along in range(15,math.ceil(self.size)-14,10)
                                for x,y in ((axis,along),(along,axis)) if not self.protected(x,y)})
        self.people=defaultdict(list)
        for p in world['people']:self.add_person(p['position'])

    def protected(self,x,y,padding=8.):
        return self.base['min'][0]-padding<=x<=self.base['max'][0]+padding and self.base['min'][1]-padding<=y<=self.base['max'][1]+padding

    def building_at(self,x,y):
        return any(b['min'][0]<=x<=b['max'][0] and b['min'][1]<=y<=b['max'][1] for b in self.boxes[math.floor(x/20),math.floor(y/20)])

    def cell_eligible(self,cell,kind):
        x,y=(cell[0]+.5)*CELL_M,(cell[1]+.5)*CELL_M
        return (0<x<self.size and 0<y<self.size and not self.protected(x,y,padding=8+CELL_M/2)
                and (kind in ('smoke','low_visibility') or not self.building_at(x,y)))

    def add_person(self,p):
        self.people[math.floor(p[0]/2.2),math.floor(p[1]/2.2)].append(p[:2])

    def person_clear(self,p):
        x,y=math.floor(p[0]/2.2),math.floor(p[1]/2.2)
        return (2<p[0]<self.size-2 and 2<p[1]<self.size-2 and not self.protected(*p[:2]) and not self.building_at(*p[:2])
                and all(math.dist(p[:2],q)>=2.2 for dx in (-1,0,1) for dy in (-1,0,1) for q in self.people[x+dx,y+dy]))

    def source(self,kind,rng,used):
        if kind in ('collapse','fire'):
            candidates=[]
            for house in self.buildings:
                if 'street_source' in house:x,y=house['street_source']
                else:
                    box=house['bounds'];x,y=((box['min'][i]+box['max'][i])/2 for i in (0,1))
                    axis_x=min(self.axes,key=lambda a:abs(a-x));axis_y=min(self.axes,key=lambda a:abs(a-y))
                    if abs(axis_x-x)<=abs(axis_y-y):x=(box['min'][0]-.7) if axis_x<x else (box['max'][0]+.7)
                    else:y=(box['min'][1]-.7) if axis_y<y else (box['max'][1]+.7)
                point=(x,y)
                if not self.protected(x,y) and point not in used:candidates.append((point,house['id']))
            if not candidates:return None,None
            point,source_id=rng.choice(candidates);return [*point,.05],source_id
        candidates=[p for p in self.ground if p not in used]
        return ([*rng.choice(candidates),.05],None) if candidates else (None,None)


def generate_tape(world):
    settings=Settings.parse(world['settings']);profile=settings.event_profile;horizon=settings.horizon
    tape={'format':VERSION,'profile':profile,'probability_window_s':settings.event_window_s,'physics_cell_m':CELL_M,
          'placement_model':'street_sources_and_clipped_five_metre_cells.1','events':[],'late_people':[]}
    if 'road_graph' in world:tape['placement_model']='irregular_street_sources_and_clipped_five_metre_cells.2'
    if not any(settings.probabilities.values()):return tape
    placement=Placement(world);used=defaultdict(set)
    windows=range(1,max(2,int(horizon//80))) if profile=='v052' else range(1,math.ceil(horizon/30))
    next_person=max((p['id'] for p in world['people']),default=0)+1
    for window in windows:
        for requested in EVENT_DEFAULTS[profile]:
            rng=random.Random(_seed(VERSION,settings.seed,profile,requested,window))
            if rng.random()*100>=settings.probabilities[requested]:continue
            kind='new_target' if requested=='appearance' else requested
            at=window*settings.event_window_s
            if profile=='v052':
                at=round(max(1/60,min(horizon-1/60,at+rng.uniform(-23,23))),2)
            if not 0<at<horizon:continue
            eid='event-'+hashlib.sha256(f'{VERSION}:{settings.seed}:{profile}:{requested}:{window}'.encode()).hexdigest()[:20]
            source,source_id=placement.source(kind,rng,used[kind])
            row={'id':eid,'kind':kind,'time':at,'source':source,'source_object_id':source_id,
                 'parent_id':None,'spread':False,'cells':[],'expires_at':None,'visibility_expires_at':None,'rejection':None}
            if source is None:row['rejection']='no_eligible_source';tape['events'].append(row);continue
            if kind=='new_target':
                for _ in range(180):
                    if placement.shoulders:point=[*rng.choice(placement.shoulders),.06]
                    else:
                        x,y=rng.choice(placement.ground)
                        point=[x+3.1,y,.06] if rng.random()<.5 else [x,y+3.1,.06]
                    if placement.person_clear(point):break
                else:row['rejection']='no_safe_late_person_space';tape['events'].append(row);continue
                row.update(source=point,target_id=next_person)
                tape['late_people'].append({'id':next_person,'position':point,'priority':rng.choices((1,2,3),(.6,.3,.1))[0],
                                             'available_at':at,'appearance_event_id':eid})
                placement.add_person(point);next_person+=1
            else:
                cx,cy=(math.floor(v/CELL_M) for v in source[:2]);radius=2 if kind in ('collapse','road_damage','mud') else 3
                for dy in range(-radius,radius+1):
                    for dx in range(-radius,radius+1):
                        cell=(cx+dx,cy+dy)
                        if dx*dx+dy*dy<=radius*radius+1 and placement.cell_eligible(cell,kind) and rng.random()<.84:
                            row['cells'].append(list(cell))
                if not row['cells']:row['rejection']='no_eligible_surface'
                if kind in ('smoke','low_visibility'):
                    duration=(72 if profile=='v052' else 90) if kind=='smoke' else 100
                    row['expires_at']=at+duration;row['visibility_expires_at']=at+duration
                elif kind in ('collapse','fire'):row['visibility_expires_at']=at+(24 if kind=='collapse' else 70)
            tape['events'].append(row)
            if row['rejection']:continue
            if kind in PERSISTENT:used[kind].add(tuple(source[:2]))
            if kind in ('fire','flood'):
                cells={tuple(c) for c in row['cells']};frontier=sorted(cells)
                for step in range(1,2 if profile=='v052' else 3):
                    spread_at=(round(min(horizon-1/60,at+38),2) if profile=='v052'
                               else at+step*settings.event_window_s)
                    if not at<spread_at<horizon or (profile=='v3' and rng.random()>.72):break
                    spread=set()
                    if profile=='v052':
                        for dx,dy in ((-1,0),(1,0),(0,1),(0,-1),(2,0),(0,2)):
                            cell=(cx+dx*rng.randint(1,2),cy+dy*rng.randint(1,2))
                            if cell not in cells and placement.cell_eligible(cell,kind):spread.add(cell)
                    else:
                        for x,y in rng.sample(frontier,min(3,len(frontier))):
                            for dx,dy in ((-1,0),(1,0),(0,1),(0,-1)):
                                cell=(x+dx,y+dy)
                                if cell not in cells and rng.random()<.65 and placement.cell_eligible(cell,kind):spread.add(cell)
                    if not spread:break
                    ordered=[list(c) for c in sorted(spread)]
                    growth={**deepcopy(row),'id':eid+'-spread-'+str(step),'parent_id':eid,'spread':True,
                            'time':spread_at,'cells':ordered,'source':[(ordered[0][i]+.5)*CELL_M for i in (0,1)]+[.05]}
                    if kind=='fire':growth['visibility_expires_at']=spread_at+70
                    tape['events'].append(growth)
                    cells.update(spread);frontier=sorted(spread)
    tape['events'].sort(key=lambda r:(r['time'],r['spread'],r['id']))
    validate_tape(tape,world)
    return tape


def validate_tape(tape,world):
    def invalid(message):raise ProtocolError('INVALID_REQUEST','Private event tape: '+message)
    if not isinstance(tape,dict) or tape.get('format')!=VERSION:invalid('unsupported version')
    settings=Settings.parse(world['settings'])
    if tape.get('profile')!=settings.event_profile or tape.get('probability_window_s')!=settings.event_window_s or tape.get('physics_cell_m')!=CELL_M:
        invalid('profile/window/cell mismatch')
    rows=tape.get('events');people=tape.get('late_people')
    if not isinstance(rows,list) or len(rows)>100000 or not isinstance(people,list):invalid('invalid arrays')
    seen={};previous=0;targets={};placement=Placement(world);appeared=set()
    original_ids={p['id'] for p in world['people']}
    for person in people:
        if not isinstance(person,dict) or type(person.get('id')) is not int or person['id']<=0 or person['id'] in targets or person['id'] in original_ids:invalid('invalid late target id')
        if type(person.get('priority')) is not int or not 1<=person['priority']<=3:invalid('invalid late target priority')
        targets[person['id']]=person
    if len(targets)!=len(people):invalid('duplicate late target')
    allowed={'new_target' if k=='appearance' else k for k in EVENT_DEFAULTS[settings.event_profile]}
    for row in rows:
        if not isinstance(row,dict):invalid('row is not an object')
        eid=row.get('id');at=row.get('time');kind=row.get('kind')
        if not isinstance(eid,str) or not eid or eid in seen:invalid('duplicate/invalid id')
        if type(at) not in (int,float) or not math.isfinite(at) or not 0<at<settings.horizon or at<previous:invalid('invalid time/order')
        if not isinstance(kind,str) or kind not in allowed:invalid('unknown kind for profile')
        parent=row.get('parent_id')
        if parent is not None and (not isinstance(parent,str) or parent not in seen or seen[parent]['kind']!=kind or seen[parent]['time']>=at or seen[parent].get('rejection') or kind not in ('fire','flood')):invalid('missing/future/invalid parent')
        if type(row.get('spread')) is not bool or bool(parent)!=row['spread']:invalid('invalid spread flag')
        seen[eid]=row;previous=at
        rejection=row.get('rejection')
        if rejection is not None:
            if not isinstance(rejection,str) or not rejection:invalid('invalid rejection')
            continue
        source=row.get('source')
        if not isinstance(source,list) or len(source)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in source):invalid('invalid source')
        if not 0<=source[0]<=placement.size or not 0<=source[1]<=placement.size or placement.protected(*source[:2]):invalid('unsafe source')
        cells=row.get('cells')
        if not isinstance(cells,list) or len(cells)>256:invalid('invalid cells')
        for cell in cells:
            if not isinstance(cell,list) or len(cell)!=2 or any(type(v) is not int for v in cell) or not placement.cell_eligible(cell,kind):invalid('unsafe cell')
        if len({tuple(c) for c in cells})!=len(cells):invalid('duplicate cells')
        if kind=='new_target':
            target_id=row.get('target_id')
            if type(target_id) is not int:invalid('invalid target reference')
            person=targets.get(target_id)
            if person is not None and type(person.get('available_at')) not in (int,float):invalid('invalid availability time')
            if person is None or person.get('position')!=source or person.get('available_at')!=at or not placement.person_clear(source) or person.get('appearance_event_id')!=eid:invalid('invalid late target')
            placement.add_person(source);appeared.add(person['id'])
        elif not cells:invalid('empty active surface')
        for key in ('expires_at','visibility_expires_at'):
            value=row.get(key)
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<=at):invalid('invalid expiry')
    if appeared!=set(targets):invalid('unreferenced late target')
    return tape
