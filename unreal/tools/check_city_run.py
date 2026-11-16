"""Acceptance of generated-city construction and parked physical vehicles only."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

SAVED=Path(__file__).resolve().parents[1]/'MetaRescue/Saved'


def verify(folder=SAVED,layout=None):
    folder=Path(folder)
    layout_path=Path(layout) if layout else folder/'layout.private.json'
    data=json.loads(layout_path.read_text(encoding='utf-8'))
    request=json.loads((folder/'Automation/smoke-run.json').read_text(encoding='utf-8'))
    assert request['city_layout_sha256']==hashlib.sha256(layout_path.read_bytes()).hexdigest(),'wrong layout evidence'
    for name in ('Telemetry/latest.json','Automation/physics-smoke.log','Screenshots/physics-smoke.png'):
        assert (folder/name).stat().st_mtime>=request['started_at'],'stale evidence: '+name
    log=(folder/'Automation/physics-smoke.log').read_text(encoding='utf-8',errors='replace')
    assert 'MR_CITY_BUILT' in log,'city geometry did not execute'
    if request.get('glass_reflection_test'):
        assert 'r.Lumen.TranslucencyReflections.FrontLayer.Allow = "0"' in log,'reflection cvar was not applied'
    for error in ('Fatal error:','Ensure condition failed','Failed to compile Material',
                  'Default Material will be used in game',"has to be 'Movable'",'MR_CITY missing','MR_CITY prepare_city_assets'):
        assert error not in log,'engine error: '+error
    state=json.loads((folder/'Telemetry/latest.json').read_text(encoding='utf-8-sig'))
    summary=state['city_layout']
    assert state['time_s']>=request['requested_seconds']-.1,'native episode ended early'
    assert summary['size_m']==data['size_m']
    assert summary['buildings']==len(data['buildings'])
    assert summary['initial_people']==len(data['people'])
    assert summary['features']==len(data['features'])
    assert summary['nanite_instances']>0,'derived Nanite meshes are not in the real scene'
    assert summary['mesh_instances']>summary['mesh_components'],'city was not instanced'
    if data['format'] in ('rescue-city-2.1','rescue-city-2.2','rescue-city-2.3'):
        expected_vegetation=Counter(item['asset_id'] for item in data['features'] if item['kind']=='vegetation')
        expected_props=Counter(item['asset_id'] for item in data['features'] if item['kind']=='parked_vehicle')
        assert summary['vegetation_instances']==expected_vegetation,'wrong live vegetation instance counts'
        assert summary.get('prop_instances',{})==expected_props,'wrong live prop instance counts'
        assert summary['cover_batches']>0 and 'MR_CITY_YARDS lots='+str(len(data['lot_covers']))+' ' in log
        assert summary['yard_colliders']==sum(len(item['obstacles']) for item in data['features']),'missing yard collision'
        if request.get('visual_probe')=='city-assets':
            for item in ('city-service-van',*(f'city-asset-{name}' for name in expected_vegetation|expected_props)):
                assert (folder/'Screenshots'/f'{item}.png').stat().st_mtime>=request['started_at'],item
            assert summary['van_travel_m']>=6.4 and summary['van_distance_to_parking_m']<=.05,'van did not park'
    if request.get('visual_probe')=='city-buildings':
        variants={row['variant'] for row in data['buildings']}
        expected_views=[*(f'city-building-{variant}' for variant in variants),*(f'city-boundary-{side}' for side in range(4))]
        if 0 in variants:expected_views+=['city-window-exterior','city-interior','city-window-oblique']
        for name in expected_views:
            assert (folder/'Screenshots'/f'{name}.png').stat().st_mtime>=request['started_at'],name
    if request.get('visual_probe')=='city-lumen':
        expected_views=('lit-exterior','surface-cache-exterior','mesh-fields-exterior','surface-cache-interior',
                        'mesh-fields-interior','indirect-interior','lit-interior')
        for name in expected_views:
            assert 'MR_CITY_LIGHT_VIEW city-'+name in log,name
            assert (folder/'Screenshots'/f'city-{name}.png').stat().st_mtime>=request['started_at'],name
    if request.get('visual_probe')=='city-glazing':
        for style in ('clean','dirty','cracked','broken','empty'):
            for view in ('exterior','interior','oblique'):
                name=f'city-glazing-{style}-{view}'
                assert (folder/'Screenshots'/f'{name}.png').stat().st_mtime>=request['started_at'],name
    if request.get('visual_probe')=='city-competition':
        assert 'competition' in data,'competition annex missing'
        for name in ('city-basin-overview','city-surface-agent','city-underwater-agent','city-tunnel-agent',
                     'city-site-sensor','city-services-base','city-annex-context'):
            assert (folder/'Screenshots'/f'{name}.png').stat().st_mtime>=request['started_at'],name
    expected={a['id']:a for a in data['spawns']}
    expected.update({a['id']:a for a in data.get('competition',{}).get('units',[])})
    actual={a['key']:a for a in state['agents']}
    assert len(actual)==len(state['agents']) and actual.keys()==expected.keys(),'wrong physical fleet'
    max_drift=0
    for key,a in actual.items():
        spawn=expected[key]
        kind=spawn['kind'];physical=kind in ('ground','aerial','underground','surface_water','underwater')
        assert bool(a['simulating'])==physical and a['energy']>=0,(key,'invalid physical agent')
        assert all(math.isfinite(a[k]) for k in ('x_cm','y_cm','z_cm','distance_cm'))
        assert a['vehicle_contacts']==0,(key,'vehicle collision',a['vehicle_contacts'])
        drift=math.dist([a['x_cm']/100,a['y_cm']/100],spawn['position'][:2]);max_drift=max(max_drift,drift)
        assert drift<=.5,(key,'parked vehicle drift exceeds 0.5m',drift)
        if 'limits' in spawn:
            assert spawn['limits']['min'][2]*100-5<=a['z_cm']<=spawn['limits']['max'][2]*100+5,(key,'body outside medium')
        else:assert -20<a['z_cm']<500,(key,'parked body left its support')
    bodies=state['physics_bodies']
    assert len(bodies)==23*len(data['facilities']),'missing real Chaos fixtures'
    free=[b for b in bodies if not b['collapse_piece']];held=[b for b in bodies if b['collapse_piece']]
    assert len(free)==18*len(data['facilities']) and len(held)==5*len(data['facilities'])
    assert all(b['simulating'] and b['z_cm']>-100 for b in free),'free rubble lost support'
    assert all(not b['simulating'] and abs(b['initial_z_cm']-b['z_cm'])<1 for b in held),'supported slabs moved'
    result={'passed':True,'scope':'native city geometry, parked fleet and instancing; no mission/controller verdict',
            'seconds':state['time_s'],'size_m':summary['size_m'],'buildings':summary['buildings'],
            'agents':len(actual),'people':summary['initial_people'],'max_parked_drift_m':max_drift,
            'mesh_instances':summary['mesh_instances'],'mesh_components':summary['mesh_components'],
            'nanite_instances':summary['nanite_instances'],'fps':state.get('average_game_fps'),
            'construction_wall_s':summary.get('construction_wall_s'),
            'p50_frame_ms':state.get('p50_frame_ms'),'p95_frame_ms':state.get('p95_frame_ms'),
            'visual_probe':request.get('visual_probe'),'glass_reflection_test':request.get('glass_reflection_test',False),
            'render_wall_fps':state.get('render_wall_fps'),'memory_mb':state.get('process_memory_mb'),
            'not_verified':['route execution','mission delivery','events and resources',
                            'all interiors and facade variants','maximum fleet performance']}
    if data['format'] in ('rescue-city-2.1','rescue-city-2.2','rescue-city-2.3'):
        result.update(vegetation_instances=summary['vegetation_instances'],cover_batches=summary['cover_batches'],
                      prop_instances=summary.get('prop_instances',{}),yard_colliders=summary['yard_colliders'])
        if 'van_travel_m' in summary:
            result.update(van_travel_m=summary['van_travel_m'],
                          van_distance_to_parking_m=summary['van_distance_to_parking_m'])
    (folder/'city-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--saved',type=Path,default=SAVED)
    parser.add_argument('--layout',type=Path,required=True)
    args=parser.parse_args();verify(args.saved,args.layout)
