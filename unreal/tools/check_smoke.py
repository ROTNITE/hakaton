"""Assert common physical outcomes from one actual engine run, never fixture data."""
import argparse
import json
import math
from pathlib import Path

SAVED=Path(__file__).resolve().parents[1]/'MetaRescue'/'Saved'


def verify(saved=SAVED):
    saved=Path(saved)
    request=json.loads((saved/'Automation/smoke-run.json').read_text(encoding='utf-8'))
    started=request['started_at']
    for file in ['Automation/physics-smoke.log','Telemetry/latest.json','Telemetry/events.jsonl','Screenshots/physics-smoke.png']:
        assert (saved/file).stat().st_mtime>=started,'stale evidence: '+file
    engine_log=(saved/'Automation/physics-smoke.log').read_text(encoding='utf-8',errors='replace')
    for error in ['Failed to compile Material','Default Material will be used in game','Fatal error:','Ensure condition failed']:
        assert error not in engine_log,'Engine error: '+error
    state=json.loads((saved/'Telemetry/latest.json').read_text(encoding='utf-8-sig'))
    events=[json.loads(s) for s in (saved/'Telemetry/events.jsonl').read_text(encoding='utf-8-sig').splitlines() if s]
    required_seconds=request.get('requested_seconds',90)
    assert state['time_s']>=required_seconds-.1,'run ended early'
    assert state['time_s']>=26
    quarter=state['kind']=='rescue_quarter_environment_demo'
    assert bool(request.get('quarter'))==quarter,'wrong scene evidence'
    if not quarter:assert state['collapse_released']
    assert state['contacts']>0,'no rigid-body contacts recorded'
    bodies=state['physics_bodies']
    assert len(bodies)>=23 if quarter else len(bodies)==23
    if quarter:
        assert all('collapse_piece' in b for b in bodies),'missing explicit quarter collapse classification'
        free=[b for b in bodies if not b['collapse_piece']]
        held=[b for b in bodies if b['collapse_piece']]
    else:
        # The unchanged legacy saved map has 18 free then 5 collapse bodies.
        # Historical telemetry predates the explicit collapse_piece flag.
        free=bodies[:18];held=bodies[18:]
    assert len(free)>=18 and len(held)==5
    assert all(b['simulating'] for b in free)
    if state['collapse_released']:
        assert all(b['simulating'] for b in bodies)
        assert any(b['initial_z_cm']-b['z_cm']>300 for b in held),'collapse did not fall'
    else:
        assert all(not b['simulating'] and abs(b['initial_z_cm']-b['z_cm'])<1 for b in held),'supported slabs moved before their event'
    assert all(b['z_cm']>-100 for b in bodies),'debris fell through ground'
    assert len(state['agents'])==7
    for a in state['agents']:
        assert a['simulating']
        assert a['energy']>=0
        assert all(math.isfinite(a[k]) for k in ['x_cm','y_cm','z_cm','distance_cm'])
        if quarter:assert a['vehicle_contacts']==0,('vehicle collision',a['key'],a['vehicle_contacts'])
        if not a['aerial']:assert -20<a['z_cm']<500,'ground agent left the surface'
    mission_enabled=not request.get('external_control') and not request.get('traffic_probe')
    if mission_enabled:
        assert state['discovered']>0,'no actual sensor detection'
        assert any(a['distance_cm']>1000 for a in state['agents'] if a['aerial']),'no drone movement'
        assert any(a['distance_cm']>1000 for a in state['agents'] if not a['aerial']),'no ground movement'
    if state['collapse_released']:assert any(e['type']=='demo_collapse_released' for e in events)
    if (not quarter and required_seconds>=90) or (quarter and request.get('environment')=='static' and required_seconds>=270 and mission_enabled):
        assert state['delivered']>=1,'no completed physical rescue in the long smoke'
    result={'passed':True,'scope':'common native smoke checks, not full plan acceptance','time_s':state['time_s'],
            'contacts':state['contacts'],'discovered':state['discovered'],'delivered':state['delivered'],
            'physics_bodies':len(bodies),'agents':len(state['agents'])}
    print(json.dumps(result,ensure_ascii=False))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--saved',type=Path,default=SAVED)
    verify(parser.parse_args().saved)
