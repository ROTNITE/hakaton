"""Metre geometry used by the private layout generator."""
from collections import defaultdict
from dataclasses import dataclass
import math


def box(minimum, maximum):
    return {'kind': 'box', 'min': list(minimum), 'max': list(maximum)}


def overlap(a, b, margin=0):
    return all(a['min'][i] - margin < b['max'][i] and b['min'][i] < a['max'][i] + margin for i in range(2))


def segment_clear(a, b, boxes, radius=.9):
    for bounds in boxes:
        low, high = 0., 1.
        for axis in range(2):
            lower, upper = bounds['min'][axis] - radius, bounds['max'][axis] + radius
            delta = b[axis] - a[axis]
            if abs(delta) < 1e-12:
                if a[axis] < lower or a[axis] > upper:
                    low, high = 1., 0.
                    break
            else:
                t1, t2 = (lower - a[axis]) / delta, (upper - a[axis]) / delta
                low, high = max(low, min(t1, t2)), min(high, max(t1, t2))
        if low <= high:
            return False
    return True


@dataclass(frozen=True)
class Footprint:
    center: tuple
    half: tuple
    axes: tuple = ((1.,0.),(0.,1.))

    @classmethod
    def from_area(cls, area):
        bounds=area['bounds'];form=area.get('footprint')
        if form is None:
            center=tuple((a+b)/2 for a,b in zip(bounds['min'][:2],bounds['max'][:2]))
            half=tuple((b-a)/2 for a,b in zip(bounds['min'][:2],bounds['max'][:2]))
            return cls(center,half)
        angle=math.radians(form['yaw']);x,y=math.cos(angle),math.sin(angle)
        return cls(tuple(form['center']),tuple(form['half']),((x,y),(-y,x)))

    def intersects(self, other, margin=0):
        offset=tuple(b-a for a,b in zip(self.center,other.center))
        for axis in (*self.axes,*other.axes):
            def radius(form):return sum(h*abs(u[0]*axis[0]+u[1]*axis[1]) for h,u in zip(form.half,form.axes))
            if abs(offset[0]*axis[0]+offset[1]*axis[1])>=radius(self)+radius(other)+margin:return False
        return True

    def clear_segment(self,a,b,radius):
        def local(p):
            x,y=p[0]-self.center[0],p[1]-self.center[1]
            return tuple(x*u+y*v for u,v in self.axes)
        limits={'min':[-v for v in self.half],'max':self.half}
        return segment_clear(local(a),local(b),[limits],radius)


class SpatialIndex:
    """Index planar envelopes. Exact overlap checks remain with the caller."""

    def __init__(self, cell_m=20):
        self.cell_m = cell_m
        self.cells = defaultdict(list)

    def _cells(self, low, high):
        first = [math.floor(n/self.cell_m) for n in low[:2]]
        last = [math.floor(n/self.cell_m) for n in high[:2]]
        for x in range(first[0], last[0]+1):
            for y in range(first[1], last[1]+1):
                yield x, y

    def add(self, key, low, high):
        for cell in self._cells(low, high):
            self.cells[cell].append(key)

    def query(self, low, high):
        return {key for cell in self._cells(low, high) for key in self.cells.get(cell, ())}
