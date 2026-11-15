"""Public geometry and spawn plan for the optional competition annex."""
from __future__ import annotations


FORMAT='metarescue.competition-annex.v1'


def box(low,high):
    return {'kind':'box','min':list(low),'max':list(high)}


def zone(identifier,kind,geometry,allowed,*,risk=0.,movement=1.,radio=1.):
    return {'id':identifier,'type':kind,'geometry':geometry,'access':{'allowed_kinds':list(allowed)},
            'risk':risk,'cost':{'movement_multiplier':movement},'communication':{'quality_multiplier':radio},
            'constraints':[]}


def attach(world):
    size=world['size_m']
    basin=box((-99,24,-7.2),(-63,62,.05))
    tunnel=box((7,40,-7.5),(36,53,-3.2))
    water_air=box((-99,24,.2),(-63,62,.65))
    submerged=box((-99,24,-7.2),(-63,62,-1.15))
    ground=box((0,0,0),(size,size,2))
    world['bounds']['min'][0]=-101
    zones=[
        zone('urban-land','land',ground,('ground',)),
        zone('city-airspace','air',box((-101,0,.1),(size,size,90)),('aerial',)),
        zone('training-basin','water',basin,('surface_water','underwater'),movement=1.3),
        zone('utility-tunnel','underground',tunnel,('underground',),movement=1.2),
        zone('dispatch-compound','infrastructure',world['base'],('ground','aerial','infrastructure','digital','operator')),
        zone('basin-shadow','low_connectivity',box((-99,24,-7.2),(-87,62,.65)),
             ('surface_water','underwater','aerial'),radio=.55)
    ]
    if world['buildings']:
        zones.append(zone('structure-envelope','obstacle',world['buildings'][0]['bounds'],(),risk=1.))
    units=[
        {'id':'tunnel-rover','kind':'underground','position':[12,44,-6.9],'limits':tunnel,'yaw':0.},
        {'id':'surface-craft','kind':'surface_water','position':[-91,32,.38],'limits':water_air,'yaw':0.},
        {'id':'submersible','kind':'underwater','position':[-91,46,-2.2],'limits':submerged,'yaw':0.},
        {'id':'site-observer','kind':'infrastructure','position':[22,30,2.],'site':'sensor-base'},
        {'id':'dispatch-compute','kind':'digital','position':[15,22,1.],'site':'compute-base'},
        {'id':'incident-operator','kind':'operator','position':[20,22,1.],'site':'rescue-base'}
    ]
    world['competition']={'format':FORMAT,'basin':basin,'tunnel':tunnel,'units':units,'zones':zones,
        'orbital_sensor':{'id':'orbital-sensor','period_s':150,'altitude_km':480,'swath_m':42}}
    return world
