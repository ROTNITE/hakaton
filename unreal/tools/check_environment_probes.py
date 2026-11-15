"""Check measured physical slow-down and safe stop from a real probe run."""
from pathlib import Path
import json
import statistics

root=Path(__file__).resolve().parents[2]
saved=root/'unreal/MetaRescue/Saved'
request=json.loads((saved/'Automation/smoke-run.json').read_text())
assert (saved/'Telemetry/frames.jsonl').stat().st_mtime>=request['started_at']
frames=[json.loads(line) for line in (saved/'Telemetry/frames.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip()]
rows=[p for f in frames for p in f.get('mechanics_probes',[])]
water=[p for p in rows if p['id']==100]
mud=[p for p in rows if p['id']==101]
assert water and mud,'No actual physical probe samples'
assert all(0<p['z_cm']<200 for p in rows),'Probe lost ground support'
assert max(p['distance_cm'] for p in water)>200,'Water probe never approached hazard'
assert any(p['blocked'] for p in water),'No physical safe stop before deep water'
assert max(p['y_cm'] for p in water)<12050,'Non-amphibious rover entered deep water'
assert water[-1]['speed_cm_s']<15,'Water rover did not stay stopped'
fast=[p['speed_cm_s'] for p in mud if p['y_cm']<7600 and p['speed_cm_s']>100]
slow=[p['speed_cm_s'] for p in mud if 7900<p['y_cm']<8700 and p['surface_factor']<.6]
assert fast and slow,(fast,slow)
road_speed=statistics.median(fast);mud_speed=statistics.median(slow)
assert mud_speed<road_speed*.7,(road_speed,mud_speed)
assert max(p['y_cm'] for p in mud)>9000,'Mud traversal did not finish'
result={'passed':True,'road_speed_cm_s':road_speed,'mud_speed_cm_s':mud_speed,
        'water_stop_y_cm':water[-1]['y_cm'],'water_distance_cm':water[-1]['distance_cm'],
        'probe_samples':len(rows),'mission_agents':7,'additional_validation_vehicles':2}
(root/'artifacts/3d-world/environment-probe-verification.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
