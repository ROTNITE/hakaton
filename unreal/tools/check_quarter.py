"""Validate actual quarter histories, beyond the shared physics smoke gate."""
from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[2]
SAVED = ROOT / 'unreal/MetaRescue/Saved'
request = json.loads((SAVED / 'Automation/smoke-run.json').read_text(encoding='utf-8'))
started = request['started_at']
for relative in ['Telemetry/latest.json', 'Telemetry/frames.jsonl', 'Telemetry/events.jsonl',
                 'Screenshots/quarter-base.png', 'Screenshots/quarter-overview.png',
                 'Screenshots/quarter-collapse.png', 'Screenshots/quarter-water.png', 'Screenshots/quarter-tunnel.png']:
    assert (SAVED / relative).stat().st_mtime >= started, 'Stale evidence: ' + relative
state = json.loads((SAVED / 'Telemetry/latest.json').read_text(encoding='utf-8-sig'))
assert state['kind'] == 'rescue_quarter_environment_demo'
assert state['time_s'] >= request['requested_seconds'] - .1
# Normalize legacy pretty-writer CR separators; later runs use a condensed JSON writer.
raw = (SAVED / 'Telemetry/frames.jsonl').read_bytes().decode('utf-8-sig').replace('\r', '')
frames = [json.loads(line) for line in raw.split('\n') if line.strip()]
events = [json.loads(line) for line in (SAVED / 'Telemetry/events.jsonl').read_text(encoding='utf-8-sig').splitlines() if line]
assert len(frames) >= 30
assert {e['agent_id'] for e in events if e['type'] == 'agent_takeoff_started'} == {0, 1, 2}
assert {e['agent_id'] for e in events if e['type'] == 'agent_landed'} == {0, 1, 2}
for ident in range(3):
    trajectory = [a for frame in frames for a in frame['agents'] if a['aerial'] and a['id'] == ident]
    assert max(a['z_cm'] for a in trajectory) > 1500, ('No real climb', ident)
    assert any(a['state'] == 'landed' and a['z_cm'] < 80 for a in trajectory), ('No ground landing', ident)
for ident in range(4):
    trajectory = [a for frame in frames for a in frame['agents'] if not a['aerial'] and a['id'] == ident]
    assert max(a['distance_cm'] for a in trajectory) > 1000, ('Ground agent did not travel', ident)
    assert any(a['support_contacts'] >= 4 for a in trajectory), ('No suspension support', ident)
    assert any(a['state']=='loading' and a['ramp_deployment']>.98 for a in trajectory), ('No actual pickup mechanism cycle',ident)
    assert any(a['state']=='inbound' and a['mass_kg']>300 for a in trajectory), ('Never carried a patient',ident)
    assert not any(a['state']=='overturned' for a in trajectory), ('Vehicle overturned',ident)
assert any(a['state'] == 'inbound' and abs(a['mass_kg'] - 320) < 1
           for frame in frames for a in frame['agents'] if not a['aerial']), 'Loaded mass not observed'
delivered = [e for e in events if e['type'] == 'person_delivered']
assert delivered and len({e['target_id'] for e in delivered}) == len(delivered)
assert len(delivered) == state['delivered']
assert any(f.get('dust_effect_active') for f in frames if 18<f['time_s']<42), 'No running collapse particles'
assert any(f.get('leak_effect_active') for f in frames if f['time_s']>55), 'No running leak particles'
assert any(f.get('fire_effect_active') for f in frames), 'No running fire particles'
assert any(f['pending_reports']>0 and not f['relay_online'] for f in frames), 'No real queued observation during relay outage'
assert state['pending_reports']==0 and state['relay_online'], 'Queued observations were not delivered after restoration'
departed_again=[]
for ident in range(4):
    samples=[(f['time_s'],a) for f in frames for a in f['agents'] if not a['aerial'] and a['id']==ident]
    unloading=[time for time,a in samples if a['state']=='unloading']
    if unloading and any(time>unloading[0] and a['state']=='outbound' and
                         abs(a['x_cm']-(-1100+ident*330))+abs(a['y_cm']-200)>1300
                         for time,a in samples):departed_again.append(ident)
assert departed_again, 'No successful repeat departure from a dock after delivery'
for event in delivered:
    loaded = [e for e in events if e['type'] == 'person_loaded' and e['target_id'] == event['target_id']]
    assert len(loaded) == 1 and loaded[0]['time_s'] < event['time_s']
result = {'passed': True, 'time_s': state['time_s'], 'observed_frames': len(frames),
          'found': state['discovered'], 'delivered': len(delivered),
          'first_delivery_s': delivered[0]['time_s'], 'takeoffs': 3, 'landings': 3,
          'average_game_fps': state.get('average_game_fps'), 'worst_frame_ms': state.get('worst_frame_ms'),
          'repeat_departure_agents':departed_again,'all_four_rovers_loaded':True,'runtime_effects_observed':True,
          'blocked_agents': sorted({e['agent_id'] for e in events if e['type'] == 'agent_route_blocked'})}
out = ROOT / 'artifacts/3d-world/quarter-verification.json'
out.write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
