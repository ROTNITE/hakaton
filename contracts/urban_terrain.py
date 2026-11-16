"""Public, immutable terrain blueprint shared by environment and navigation.

This module contains no people, event tape, runtime water or private knowledge.
All distances are metres. Native geometry implements the same height function.
"""
from __future__ import annotations

import math

FORMAT = 'metarescue.graded-terrain.v1'


def _smooth(value):
    value = min(1., max(0., value))
    return value * value * (3. - 2. * value)


def _distance(x, y, low, high):
    return math.hypot(max(low[0]-x, 0., x-high[0]), max(low[1]-y, 0., y-high[1]))


class Terrain:
    def __init__(self, data=None):
        self.data = data
        self.pads = {}
        if data is None:
            return
        if not isinstance(data, dict) or data.get('format') != FORMAT:
            raise ValueError('Unsupported terrain blueprint')
        self.low = data['base']['min']
        self.high = data['base']['max']
        self.elevation = data['base_elevation_m']
        self.grade = data['grade_width_m']
        self.ramp = data['ramp']
        if len(self.low)!=2 or len(self.high)!=2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in (*self.low, *self.high, self.elevation, self.grade)) or \
                any(a >= b for a, b in zip(self.low, self.high)) or not 0 <= self.elevation <= 10 or not 20 <= self.grade <= 100:
            raise ValueError('Terrain grade or elevation is outside its physical profile')
        low, high = self.ramp['min'], self.ramp['max']
        if len(low)!=2 or len(high)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in (*low,*high)) or \
                any(a>=b for a,b in zip(low,high)) or low[0]!=self.high[0] or abs(high[0]-low[0]-self.grade)>1.e-8:
            raise ValueError('Invalid raised-base access ramp')
        self.depressions = data.get('depressions', ())
        for area in self.depressions:
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in (*area['min'], *area['max'], area['elevation_m'])) or \
                    len(area['min']) != 2 or len(area['max']) != 2 or any(a >= b for a, b in zip(area['min'], area['max'])) or not -20 <= area['elevation_m'] <= 0:
                raise ValueError('Invalid terrain depression')
        if len(data['pads']) > 20000:
            raise ValueError('Too many level foundations')
        for pad in data['pads']:
            if type(pad['elevation_m']) not in (int, float) or not math.isfinite(pad['elevation_m']) or not -10 <= pad['elevation_m'] <= 10:
                raise ValueError('Invalid level foundation elevation')
            low, high = pad['min'], pad['max']
            if len(low) != 2 or len(high) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v)>20000 for v in (*low, *high)) or any(a >= b for a, b in zip(low, high)):
                raise ValueError('Invalid level foundation footprint')
            for x in range(math.floor((low[0]-1)/32), math.floor((high[0]+1)/32)+1):
                for y in range(math.floor((low[1]-1)/32), math.floor((high[1]+1)/32)+1):
                    self.pads.setdefault((x, y), []).append(pad)

    def raw_height(self, x, y):
        if self.data is None:
            return 0.
        # A compacted earth platform grades into the existing street network.
        # Its surrounding slopes preserve all old street connections; the
        # eastern ramp describes the fleet's primary exit through this grade.
        return self.elevation*max(0., 1.-_distance(x, y, self.low, self.high)/self.grade)

    def height(self, x, y):
        height = self.raw_height(x, y)
        if self.data is None:
            return height
        for area in self.depressions:
            if area['min'][0] <= x <= area['max'][0] and area['min'][1] <= y <= area['max'][1]:
                return area['elevation_m']
        nearby = self.pads.get((math.floor(x/32), math.floor(y/32)), ())
        closest = min(nearby, key=lambda p: _distance(x, y, p['min'], p['max']), default=None)
        if closest is not None:
            distance = _distance(x, y, closest['min'], closest['max'])
            blend = 1. - _smooth(distance)
            height += (closest['elevation_m']-height)*blend
        return height
