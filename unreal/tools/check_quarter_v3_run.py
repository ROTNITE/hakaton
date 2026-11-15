"""Verify one archived native run. A pass covers these checks, not visual acceptance."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import struct

EVENTS={'collapse','fire','flood','mud','road_damage','smoke','low_visibility','new_target'}
LIFE={'smoke':90,'low_visibility':100}
FORBIDDEN_PUBLIC={'event_tape','probabilities_pct','hidden_targets','conservative_building_boxes','initial_ground_grid'}


def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def read_rows(path):return [json.loads(s) for s in Path(path).read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def close(a,b,tolerance=.002):return abs(a-b)<=tolerance

def check_png(path):
    with Path(path).open('rb') as stream:header=stream.read(24)
    assert header[:8]==b'\x89PNG\r\n\x1a\n','not a PNG: '+str(path)
    dimensions=struct.unpack('>II',header[16:24])
    assert dimensions==(1600,1000),('unexpected render dimensions',dimensions,path)


def check_tape(truth,events,seconds):
    tape=truth['event_tape'];ids=[e['id'] for e in tape]
    assert len(ids)==len(set(ids)),'duplicate tape event IDs'
    assert tape==sorted(tape,key=lambda e:(e['time_s'],e['id'])),'unsorted tape'
    assert truth['window_s']==30
    indexed={e['id']:e for e in tape}
    observed=[e for e in events if e['type'] in {'environment_event','environment_attempt_rejected'}]
    due=[e for e in tape if e['time_s']<=seconds]
    assert [e['event_id'] for e in observed]==[e['id'] for e in due],'applied/rejected events differ from due tape'
    primary=set();propagation=0
    for e in tape:
        assert e['type'] in EVENTS
        assert 0<e['time_s']<truth['horizon_s']
        if truth['mode']!='showcase':assert close(e['time_s']%30,0),'not a 30s event window'
        if e['parent_id']:
            propagation+=1
            assert e['type'] in {'fire','flood'},'non-spreading kind propagated'
            parent=indexed[e['parent_id']]
            assert parent['type']==e['type'] and not parent['parent_id']
            assert e['site']==parent['site']
            assert any(close(e['time_s']-parent['time_s'],d) for d in [30,60]),'propagation outside two windows'
        else:
            pair=(e['type'],e['time_s'])
            assert pair not in primary,'more than one primary attempt per kind/window'
            primary.add(pair)
        for x,y in e['cells']:
            size=truth['dynamic_cell_size_m']*100
            assert not ((x+.5)*size<650 and (y+.5)*size<4200),'event entered protected base'
    for expected,actual in zip(due,observed):
        assert expected['type']==actual['event_type'] and close(expected['time_s'],actual['time_s'])
        assert expected['parent_id']==actual['parent_id'] and expected['cells']==actual['cells']
        assert expected['site']==actual['site_id'] and expected['rejected']==actual['reason']
        assert actual['type']==('environment_attempt_rejected' if expected['rejected'] else 'environment_event')
    probabilities=truth['probabilities_pct']
    assert set(probabilities)==EVENTS and all(0<=p<=100 and math.isfinite(p) for p in probabilities.values())
    if truth['mode']=='static' or truth['mode']=='random' and not any(probabilities.values()):
        assert not tape and not observed,'zero/static created an event or secondary consequence'
    if truth['mode']=='random':
        for kind,pct in probabilities.items():
            if pct==0:assert not any(e['type']==kind for e in tape),('zero probability kind occurred',kind)
            if pct==100:
                expected_windows=range(30,int(truth['horizon_s']),30)
                assert {t for k,t in primary if k==kind}==set(expected_windows),('100% missed primary attempts',kind)
    return {'tape_events':len(tape),'due_events':len(due),'propagations':propagation}


def check_trajectories(frames):
    histories={a['key']:[] for a in frames[-1]['agents']}
    previous_time=-1
    for frame in frames:
        assert frame['time_s']>previous_time,'non-increasing frame times'
        previous_time=frame['time_s']
        for a in frame['agents']:
            assert a['vehicle_contacts']==0,('vehicle collision',a['key'],a['vehicle_contacts'],frame['time_s'])
            assert all(math.isfinite(a[k]) for k in ['energy','distance_cm','x_cm','y_cm','z_cm','speed_cm_s'])
            assert a['energy']>=0 and a['distance_cm']>=0
            assert a['state']!='overturned',('vehicle overturned',a['key'],frame['time_s'])
            rows=histories[a['key']]
            if rows:
                prior=rows[-1]
                assert a['distance_cm']>=prior['distance_cm']-.01,'distance went backwards'
                assert a['energy']<=prior['energy']+.002,'energy increased without reset'
                movement=a['distance_cm']-prior['distance_cm']
                position_delta=math.dist([a[k] for k in ['x_cm','y_cm','z_cm']],[prior[k] for k in ['x_cm','y_cm','z_cm']])
                assert position_delta<=movement+2,('pose changed without executed distance',a['key'])
                if movement<.1:assert prior['energy']-a['energy']<.003,('stationary agent consumed fictitious movement energy',a['key'])
            rows.append(a)
    return histories


def check_traffic(probe,frames,histories,final):
    def end(key):return histories[key][-1]
    g0=end('ground_0');g1=end('ground_1');d0=end('aerial_0');d1=end('aerial_1')
    if probe=='following':
        assert g0['y_cm']>10500 and g1['y_cm']>11250,'following fixture did not finish'
        assert g0['state']=='idle' and g1['state']=='idle','following vehicles did not complete their commands'
    elif probe=='crossing':assert g0['y_cm']>11000 and g1['x_cm']>6500,'crossing fixture deadlocked or missed destination'
    elif probe=='meeting':assert g0['y_cm']>10200 and g1['y_cm']<7600,'meeting fixture did not finish'
    elif probe=='reverse':
        assert g0['x_cm']>300 and g0['y_cm']<-500,'reverse exit did not finish'
        assert min(a['y_cm'] for a in histories['ground_0'])<-600,'no actual reverse clearance'
    elif probe=='flight':
        assert d0['x_cm']>6800 and d1['x_cm']<4200,'flight crossing did not finish'
        assert end('aerial_2')['y_cm']>6800,'same-altitude flight crossing did not finish'
        assert min(abs(next(a for a in f['agents'] if a['key']=='aerial_0')['z_cm']-
                           next(a for a in f['agents'] if a['key']=='aerial_1')['z_cm']) for f in frames)>110,'flight altitude separation lost'
    elif probe=='landing':assert d0['state']=='landed' and d0['z_cm']<80 and d0['rotor_rpm']<1,'landing did not finish with stopped rotors'
    elif probe=='obstacle_replace':
        history=histories['ground_0']
        stopped=[a for f in frames if 15<f['time_s']<38 for a in f['agents'] if a['key']=='ground_0']
        assert len(stopped)>=5 and all(a['stop_reason']=='obstacle_on_route' and a['speed_cm_s']<15 for a in stopped),'not held safely before replacement'
        assert math.dist([stopped[0]['x_cm'],stopped[0]['y_cm']],[stopped[-1]['x_cm'],stopped[-1]['y_cm']])<25,'blocked agent drifted'
        assert all(a['carrying'] and 319<a['mass_kg']<321 for a in history),'cargo/mass lost on route replacement'
        assert all(a['command_id']=='blocked_route' for f in frames if f['time_s']<39 for a in f['agents'] if a['key']=='ground_0')
        assert g0['y_cm']>10000 and g0['command_id']=='replacement_route','replacement route did not execute'
        assert final['delivered']==0,'external route arrival silently unloaded cargo'
    else:raise AssertionError('Unknown traffic fixture '+probe)
    for a in (a for f in frames for a in f['agents']):
        if a['stop_reason']=='yield_to_vehicle':assert not a['route_blocked'],'temporary yield misclassified as permanent route block'


def expected_visibility(cell,time,tape):
    smoke=fog=False
    for e in tape:
        if e['rejected'] or e['time_s']>time:continue
        age=time-e['time_s'];kind=e['type'];cells=e['cells']
        if kind=='low_visibility' and age<100 and list(cell) in cells:fog=True
        if kind=='smoke' and age<90 and list(cell) in cells:smoke=True
        if kind=='collapse' and age<24 and list(cell) in cells:smoke=True
        if kind=='fire' and age<70 and any(abs(x-cell[0])+abs(y-cell[1])<=1 for x,y in cells):smoke=True
    return (.52 if smoke else 1)*(.62 if fog else 1)


def check_effects(truth,frames,applied):
    tape={e['id']:e for e in truth['event_tape']}
    samples={e['event_id']:[] for e in applied}
    for f in frames:
        for s in f['event_effect_samples']:
            e=tape[s['event_id']];samples[s['event_id']].append((f['time_s'],s))
            assert close(s['age_s'],f['time_s']-e['time_s'],.01),'wrong hazard sample age'
            active=e['type'] not in LIFE or s['age_s']<LIFE[e['type']]
            assert s['active']==active,'temporary hazard active after expiry'
            if e['cells']:
                expected=min(expected_visibility(c,f['time_s'],truth['event_tape']) for c in e['cells'])
                assert close(s['min_visibility'],expected),('visibility differs from overlapping active events',s['event_id'],s['min_visibility'],expected)
                assert {(c['x'],c['y']) for c in s['cells']}=={tuple(c) for c in e['cells']},'native sample footprint differs from tape'
                for cell in s['cells']:
                    expected=expected_visibility((cell['x'],cell['y']),f['time_s'],truth['event_tape'])
                    assert close(cell['visibility'],expected),('per-cell visibility mismatch',e['id'],cell)
                    assert cell['depth_cm']>=0 and cell['cost']>=1
                    if cell['depth_cm']>25:assert cell['blocked'],'deep water is passable'
                    if cell['depth_cm']>4:assert cell['cost']>=2-.002,'shallow water cost missing'
            if not active:
                assert s['visible_components']==0,('temporary effect still visible after expiry',s['event_id'])
            smoke_life=70 if e['type']=='fire' else 90
            for visual in s['visual_components']:
                if visual['kind']=='HeavySmoke' and s['age_s']>=smoke_life:
                    assert not visual['visible'] and not visual['active'],('smoke did not visually expire',e['id'])
    for e in applied:
        rows=samples[e['event_id']];assert rows,('missing native hazard samples',e['event_id'])
        kind=e['event_type'];values=[s for _,s in rows]
        if kind=='new_target':
            assert all(s['target_visual_exists'] and s['target_mesh_components']>0 for s in values),'late target has no real mesh'
        else:
            assert any(s['visible_components']>0 for s in values),('event has no visible runtime component',e['event_id'])
        if kind in {'collapse','fire'}:assert any(s['blocked_cells']>0 for s in values),('hazard never blocks ground',kind)
        if kind=='mud':assert any(close(s['max_cost'],2.25) for s in values),'mud cost not applied'
        if kind=='road_damage':assert any(s['max_cost']>=1.90-.002 for s in values),'road cost not applied'
        if kind=='flood':
            if max(s['age_s'] for s in values)>45:
                assert any(s['max_depth_cm']>25 and s['blocked_cells']>0 for s in values),'mature flood never reached unsafe depth'
            if max(s['age_s'] for s in values)>6:
                assert any(0<s['max_depth_cm']<25 for s in values),'no measured shallow water phase'
        if kind in LIFE:
            if frames[-1]['time_s']>=e['time_s']+LIFE[kind]+2:
                assert any(not s['active'] and s['visible_components']==0 for s in values),'expiry not observed'
        if kind=='new_target':
            assert all(not s['target_visual_hidden'] for s in values),'late target stayed hidden after event'
            assert all(s['target_observed_at']<0 or s['target_observed_at']>=e['time_s'] for s in values),'late person observed before availability'
    return {'sampled_events':len(samples),'temporaries_expired':sum(any(not s['active'] for _,s in rows) for rows in samples.values())}


def check_public(folder,truth,events,final):
    public=read_json(folder/'Telemetry/public-observation.json')
    assert not FORBIDDEN_PUBLIC.intersection(public),'private state in public snapshot'
    assert len(public['targets'])==final['discovered'],'public discovered target count differs'
    detected={}
    for e in events:
        if e['type']=='person_report_received':detected.setdefault(e['target_id'],e['time_s'])
    # This explicitly named fixture begins with an already known carried patient.
    request=read_json(folder/'Automation/smoke-run.json')
    if request.get('traffic_probe')=='obstacle_replace':detected[1]=0
    for row in public['targets']:assert row['id'] in detected,'public target without a real observation'
    history=folder/'Telemetry/public-frames.jsonl'
    assert history.exists(),'missing public observation history; hidden-target gate is not proven'
    times={e.get('target_id'):e['time_s'] for e in truth['event_tape'] if e['type']=='new_target' and not e['rejected']}
    rows=read_rows(history)
    for row in rows:
        assert not FORBIDDEN_PUBLIC.intersection(row)
        for target in row['targets']:
            ident=target['id']
            assert ident in detected and detected[ident]<=row['time_s']+.01,'target leaked before observation'
            if ident in times:assert times[ident]<=row['time_s']+.01,'latent target leaked before availability'
    return {'public_final_checked':True,'public_history_checked':True,'public_history_frames':len(rows)}


def check_clock_profile(request,final,probe=None,capture=False):
    fixed=request.get('time_step_mode','real_time')=='fixed_functional'
    assert final['time_step_mode']==request.get('time_step_mode','real_time'),'clock profile mismatch'
    # UE parses FPS as float and computes its reciprocal in that precision.
    # 1/(float(1/30)) is ~29.9999984, not exactly the integer request30.
    assert close(final['requested_fixed_fps'],request.get('requested_fixed_fps',0),.00001),'fixed rate metadata mismatch'
    if fixed:
        assert request['requested_fixed_fps']==30 and request['environment']=='random' and not probe and not capture
        assert close(final['model_delta_s_min'],1/30,.00001) and close(final['model_delta_s_max'],1/30,.00001),'actual model tick differs from requested fixed rate'
        assert request['wall_elapsed_s']>0 and final['wall_elapsed_s']>0
    return fixed


def verify(folder):
    folder=Path(folder)
    request=read_json(folder/'Automation/smoke-run.json')
    files=['Telemetry/frames.jsonl','Telemetry/events.jsonl','Telemetry/environment-truth.json','Telemetry/latest.json',
           'Telemetry/public-observation.json','Automation/physics-smoke.log','Screenshots/physics-smoke.png']
    for name in files:assert (folder/name).stat().st_mtime>=request['started_at'],'stale evidence: '+name
    check_png(folder/'Screenshots/physics-smoke.png')
    frames=read_rows(folder/'Telemetry/frames.jsonl');events=read_rows(folder/'Telemetry/events.jsonl')
    truth=read_json(folder/'Telemetry/environment-truth.json');final=read_json(folder/'Telemetry/latest.json')
    assert frames and frames[-1]['time_s']>=request['requested_seconds']-2.2,'history ended early'
    assert final['time_s']>=request['requested_seconds']-.1
    assert final['kind']=='rescue_quarter_environment_demo'
    assert final['event_seed']==truth['seed'] and final['environment_mode']==truth['mode']==request['environment'],'profile/seed mismatch'
    log=(folder/'Automation/physics-smoke.log').read_text(encoding='utf-8',errors='replace')
    for bad in ['Failed to compile Material','Default Material will be used in game','Fatal error:','Ensure condition failed','MR probe route idempotency/cargo invariant failed','MR missing v3 effect']:
        assert bad not in log,bad
    # Check contacts before scenario-specific assertions so a real collision can
    # never be masked by an unrelated missing sensor in a controlled fixture.
    histories=check_trajectories(frames)
    for a in final['agents']:assert a['vehicle_contacts']==0,('vehicle collision',a['key'],a['vehicle_contacts'])
    applied=[e for e in events if e['type']=='environment_event']
    tape_checks=check_tape(truth,events,final['time_s'])
    assert final['events_applied']==len(applied)
    if request['environment']=='static':
        assert not final['collapse_released'] and not final['flood_active'] and not final['dust_active']
    if request['environment']=='showcase':assert {e['event_type'] for e in applied}==EVENTS,'showcase missing an event type'
    probe=request.get('traffic_probe')
    if probe:check_traffic(probe,frames,histories,final)
    if probe=='obstacle_replace':
        assert any(e['type']=='traffic_probe_command_invariants_verified' for e in events),'adapter command/cargo invariants were not verified in engine'
    samples=check_effects(truth,frames,applied) if applied else {'sampled_events':0}
    if any(e['event_type']=='flood' for e in applied):
        flood=final['flood_geometry_audit']
        assert flood['sample_count']>0 and flood['inside_building_samples']==0,'invalid flood geometry clipping'
        assert -100<=flood['min_ground_cm']<=flood['max_ground_cm']<=55,'flood appeared on roof or missing ground'
    public_checks=check_public(folder,truth,events,final)
    archive=folder/'evidence-run.json'
    if archive.exists():
        snapshot=read_json(archive)
        for name,record in snapshot['files'].items():
            assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==record['sha256'],'archived evidence changed: '+name
    capture=(folder/'Screenshots/Capture').exists()
    fixed=check_clock_profile(request,final,probe,capture)
    performance={'fps':None if fixed else final['average_game_fps'],
                 'p95_frame_ms':None if fixed else final['p95_frame_ms'],'memory_mb':final['process_memory_mb'],
                 'time_step_mode':request.get('time_step_mode','real_time'),'requested_fixed_fps':request.get('requested_fixed_fps',0),
                 'wall_elapsed_s':final['wall_elapsed_s'],'launcher_wall_elapsed_s':request.get('wall_elapsed_s'),
                 'render_wall_fps':final['render_wall_fps'],'model_tick_fps':final['average_game_fps'],'model_step_p95_ms':final['p95_frame_ms'],
                 'capture_overhead_included':capture,
                 'performance_evaluation':'not_evaluated_fixed_functional' if fixed else 'native_real_time',
                 'target_60fps_met':None if fixed else final['average_game_fps']>=60 and final['p95_frame_ms']<=17}
    result={'passed':True,'scope':'native state, tape, traffic and evidence checks; visual review remains separate',
            'seconds':final['time_s'],'environment':truth['mode'],'seed':truth['seed'],
            'event_types':sorted({e['event_type'] for e in applied}),'applied':len(applied),
            'found':final['discovered'],'delivered':final['delivered'],'traffic_probe':probe,
            **performance,**tape_checks,**samples,**public_checks,
            'not_proven_by_this_verifier':['visual quality and support geometry','frame-by-frame collision sweep coverage','same-seed replay across runs','physical surface speed/energy comparison']}
    (folder/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result));return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path)
    args=parser.parse_args()
    try:verify(args.folder)
    except (AssertionError,KeyError,FileNotFoundError,ValueError) as error:
        result={'passed':False,'error':str(error),'scope':'native evidence verification'}
        (args.folder/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        raise


if __name__=='__main__':main()
