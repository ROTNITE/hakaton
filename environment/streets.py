"""Reproducible planar street geometry for city revision 2.0."""
from __future__ import annotations

from collections import defaultdict
import heapq
import math
import random

FORMAT = 'metarescue.street-graph.v2'
EDGE_MARGIN_M = 10.
ACCESS_WIDTH_M = 5.2


def clip_halfplane(polygon, normal, cutoff):
    """Keep n·p ≤ cutoff for a convex polygon in either winding."""
    if not polygon:
        return []
    nx, ny = normal
    clipped = []
    previous = polygon[-1]
    last = previous[0]*nx+previous[1]*ny-cutoff
    for current in polygon:
        distance = current[0]*nx+current[1]*ny-cutoff
        if (distance <= 0) != (last <= 0):
            fraction = last/(last-distance)
            clipped.append(tuple(a+fraction*(b-a) for a,b in zip(previous,current)))
        if distance <= 0:
            clipped.append(current)
        previous,last = current,distance
    return clipped


def _clip(polygon, site, other):
    nx, ny = other[0]-site[0], other[1]-site[1]
    cutoff = (nx*(site[0]+other[0])+ny*(site[1]+other[1]))/2
    return clip_halfplane(polygon, (nx, ny), cutoff)


def _edge(a,b):
    return (a,b) if a<b else (b,a)


def _blocks(size, rng):
    low,high = EDGE_MARGIN_M,size-EDGE_MARGIN_M
    count = max(3,round((high-low)/48))
    pitch = (high-low)/count
    sites = [(low+(x+.5+rng.uniform(-.36,.36))*pitch,
              low+(y+.5+rng.uniform(-.36,.36))*pitch) for y in range(count) for x in range(count)]
    boundary = [(low,low),(high,low),(high,high),(low,high)]
    polygons = []
    for index,site in enumerate(sites):
        x,y = index%count,index//count
        polygon = boundary
        # Nearby bisectors bound the cell first, avoiding far-away clips.
        neighbours = [i for yy in range(max(0,y-2),min(count,y+3))
                      for xx in range(max(0,x-2),min(count,x+3)) if (i:=yy*count+xx)!=index]
        for i in neighbours:
            polygon = _clip(polygon,site,sites[i])
        radius = max(math.dist(point,site) for point in polygon)
        nearby = set(neighbours)
        for i,other in enumerate(sites):
            if i!=index and i not in nearby and math.dist(other,site)<2*radius:
                polygon = _clip(polygon,site,other)
        outline = list(dict.fromkeys((round(p[0],3),round(p[1],3)) for p in polygon))
        if len(outline)<3:raise ValueError('Street blocks collapsed under coordinate precision')
        polygons.append(outline)
    return polygons


def _arterial(graph, start, end, high):
    low=EDGE_MARGIN_M
    best={start:0.};previous={};queue=[(0.,start)]
    while queue:
        cost,node=heapq.heappop(queue)
        if cost!=best[node]:continue
        if node==end:break
        for other in sorted(graph[node]):
            outer=any(node[axis]==other[axis] and node[axis] in (low,high) for axis in (0,1))
            candidate=cost+math.dist(node,other)*(1.8 if outer else 1.)
            if candidate<best.get(other,math.inf):
                best[other]=candidate;previous[other]=node;heapq.heappush(queue,(candidate,other))
    path=set()
    node=end
    while node!=start:
        other=previous[node];path.add(_edge(node,other));node=other
    return path


def build_streets(size, seed, *, access_obstacles=()):
    rng=random.Random(seed)
    polygons=_blocks(size,rng)
    low,high=EDGE_MARGIN_M,size-EDGE_MARGIN_M
    graph=defaultdict(set)
    block_edges=[]
    for polygon in polygons:
        edges=[]
        for a,b in zip(polygon,polygon[1:]+polygon[:1]):
            graph[a].add(b);graph[b].add(a);edges.append(_edge(a,b))
        block_edges.append(edges)
    def gate(axis,value,position):
        return min((p for p in graph if p[axis]==value),key=lambda p:(abs(p[1-axis]-position),p))
    west=gate(0,low,.44*size);east=gate(0,high,.62*size)
    south=gate(1,low,.62*size);north=gate(1,high,.48*size)
    arterial=_arterial(graph,west,east,high)|_arterial(graph,south,north,high)
    widths={edge:10. for edge in arterial}
    for edge in sorted({_edge(a,b) for a,neighbours in graph.items() for b in neighbours}):
        widths.setdefault(edge,round(rng.uniform(6.9,8.2),2))
    accesses={};access_points={}
    for index,(polygon,edges) in enumerate(zip(polygons,block_edges)):
        if rng.random()>.45:continue
        center=tuple(sum(p[axis] for p in polygon)/len(polygon) for axis in (0,1))
        candidates=[edge for edge in edges if edge not in accesses and math.dist(*edge)>29]
        if not candidates:continue
        edge=max(candidates,key=lambda item:(math.dist(*item),item))
        entrance=tuple(round((a+b)/2,3) for a,b in zip(*edge))
        if math.dist(entrance,center)<17:continue
        end=tuple(round(a+.76*(b-a),3) for a,b in zip(entrance,center))
        # A cul-de-sac may enter the base apron. Reserve the whole road
        # corridor before adding its junction and dead end to the graph.
        if any(not obstacle.clear_segment(entrance, end, ACCESS_WIDTH_M / 2) for obstacle in access_obstacles):
            continue
        accesses[edge]=(entrance,end);access_points[index]=end
    segments=[]
    for edge,width in sorted(widths.items()):
        a,b=edge;kind='avenue' if edge in arterial else 'street'
        if edge in accesses:
            entrance,end=accesses[edge]
            segments.extend(((a,entrance,width,kind),(entrance,b,width,kind),(entrance,end,ACCESS_WIDTH_M,'access')))
        elif math.dist(a,b)>30 and all(low<p[0]<high and low<p[1]<high for p in edge) and rng.random()<.28:
            length=math.dist(a,b);delta=rng.uniform(-1.65,1.65)
            normal=(-(b[1]-a[1])/length,(b[0]-a[0])/length)
            bend=tuple(round((x+y)/2+delta*n,3) for x,y,n in zip(a,b,normal))
            segments.extend(((a,bend,width,kind),(bend,b,width,kind)))
        else:
            segments.append((a,b,width,kind))
    nodes=sorted({p for a,b,_,_ in segments for p in (a,b)})
    names={p:f'junction-{i}' for i,p in enumerate(nodes)}
    road_graph={'format':FORMAT,'nodes':[{'id':names[p],'position':[p[0],p[1],0.]} for p in nodes],
                'edges':[{'from':names[a],'to':names[b],'width_m':w,'street_class':kind} for a,b,w,kind in segments],
                'entrances':[{'node_id':names[p],'outward':direction} for p,direction in
                             ((west,[-1,0]),(east,[1,0]),(south,[0,-1]),(north,[0,1]))]}
    blocks=[{'outline':polygon,'fronts':[(a,b,widths[_edge(a,b)]) for a,b in zip(polygon,polygon[1:]+polygon[:1])],
             'access_end':access_points.get(index)} for index,polygon in enumerate(polygons)]
    return road_graph,blocks
