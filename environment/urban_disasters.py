"""Initial geometry for city 2.3; never imported by a controller."""
from __future__ import annotations

import math

from contracts.urban_terrain import FORMAT, Terrain


def attach_elevation(world):
    if world['format'] != 'rescue-city-2.3':
        return
    terrain = {'format': FORMAT, 'base': {'min': world['base']['min'][:2], 'max': world['base']['max'][:2]},
               'base_elevation_m': 3.4, 'grade_width_m': 45., 'pads': [],
               'ramp': {'min': [world['base']['max'][0], 4.], 'max': [world['base']['max'][0]+45., 16.]},
               'depressions': [{'min': [-99., 24.], 'max': [-63., 62.], 'elevation_m': -7.2}]}
    raw = Terrain(terrain)
    for building in world['buildings']:
        x, y, _ = building['position']
        height = raw.raw_height(x, y)
        if height > 0:
            terrain['pads'].append({'min': building['bounds']['min'][:2], 'max': building['bounds']['max'][:2],
                                    'elevation_m': height})
    heights = Terrain(terrain)

    def bounds_up(bounds, height):
        bounds['min'][2] += height
        bounds['max'][2] += height

    def place(row):
        position = row.get('position')
        if position is None:
            return
        height = heights.height(*position[:2])
        # Copies are deliberate: charging-pad positions can alias a spawn.
        row['position'] = [*position[:2], position[2]+height]
        if 'bounds' in row:
            bounds_up(row['bounds'], height)
        for bounds in row.get('obstacles', ()):
            bounds_up(bounds, height)
        if 'exit' in row:
            row['exit'] = [[x, y, z+heights.height(x, y)] for x, y, z in row['exit']]

    for key in ('buildings', 'features', 'facilities', 'fixed_obstacles', 'infrastructure', 'spawns', 'people', 'background', 'parcels'):
        for row in world.get(key, ()):
            place(row)
    for node in world['road_graph']['nodes']:
        x, y, z = node['position']
        node['position'] = [x, y, z+heights.height(x, y)]
    for surface in world['surfaces']:
        bounds = surface['bounds']
        x, y = [(a+b)/2 for a, b in zip(bounds['min'][:2], bounds['max'][:2])]
        bounds_up(bounds, heights.height(x, y))
    bounds_up(world['base'], terrain['base_elevation_m'])
    world['base_position'][2] += terrain['base_elevation_m']
    world['base_layout_revision'] = 4
    world['terrain'] = terrain
    world['hydrology'] = hydrology_blueprint(world)
    world['bounds']['min'][0] = min(world['bounds']['min'][0], -101.)
    count=world['settings'].get('boats',0)
    if count:
        pitch=-math.degrees(math.atan2(1.9,18.))
        keel=1.5-(73.-69.)*1.9/18.
        slips=[{'id':f'boat-slip-{i}','x_m':x,'upper_y_m':73.,'lower_y_m':55.,
                'upper_z_m':1.5,'lower_z_m':-.4,'width_m':3.}
               for i,x in enumerate((-76.,-68.,-84.,-92.)[:count])]
        world['watercraft']={'format':'metarescue.rescue-watercraft.v1',
            'hydrostatics_profile':'watercraft-hydrostatics-r1.json','slipways':slips,
            'load_fixture':{'format':'metarescue.stretcher-cradle.v1','anchor_x_m':.6,'deck_raise_m':.12,'mass_kg':8.},
            'spawns':[{'id':f'watercraft-{i}','position':[slip['x_m'],69.,keel+.45],
                       'yaw':-90.,'pitch':pitch,'slipway_id':slip['id']} for i,slip in enumerate(slips)],
            'shore_station':{'id':'rescue-pier-west','deck_z_m':3.47,'hoist_height_m':6.47,'width_m':6.,
                'platforms':[{'kind':'box','min':[-79.,7.,3.15],'max':[0.,13.,3.47]},
                             {'kind':'box','min':[-79.,7.,3.15],'max':[-73.,27.,3.47]}],
                'ground_route':[[10.,10.,3.47],[-76.,10.,3.47],[-76.,22.5,3.47]],
                'ground_pickup':[-76.,22.5,3.47],'patient_position':[-76.,26.,3.47],
                'boat_position_xy':[-76.,30.5],'boat_yaw_degrees':-90.,'patient_capacity':1}}
    if 'competition' in world:
        for row in world['competition']['units']:
            if row['kind'] in ('infrastructure', 'digital', 'operator'):
                place(row)
        for zone in world['competition']['zones']:
            if zone['type'] == 'land':
                zone['geometry']['max'][2] = 6.


def hydrology_blueprint(world):
    """The existing basin is a river-fed retention source for this profile.

    The explicitly modelled boundary supplies water; it is not a finite-volume
    claim about the visible basin alone. Every supplied/removed m3 is logged.
    """
    origin = [-105., 0.]
    return {'format': 'metarescue.hydrology.v1', 'cell_m': 5., 'origin_m': origin,
            'width': math.ceil((world['size_m']-origin[0])/5), 'height': math.ceil(world['size_m']/5),
            'basin': {'min': [-99., 24., -7.2], 'max': [-63., 62., .05]},
            'boundary': 'river_fed_retention_basin', 'initial_stage_m': .05,
            'outlet_edges': ['east', 'north', 'south'], 'tailwater_stage_m': 0.,
            'storm_stage_m': 2.8, 'rise_seconds': 70., 'drain_capacity_m3_s': .025}
