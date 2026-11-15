"""Reproduce boundary defects in the untouched imported v0.3; exits 1 if found.

These probes complement the supplied 30 tests. They do not patch vendor files.
"""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'benchmarks/metarescue-v0.3/main part'))
from world import World,DEFAULT_PROB
from simulation import Simulation

w=World(7,3,'open',25,1,1,{k:0 for k in DEFAULT_PROB})
s=Simulation(w,'rescue','greedy');r=s.robots[0];person=w.people[0]
r.update(battery=.1,target=person.id,carry=person.id,state='to_base',trip_started=0)
s.on_robot_done(r,0,'to_base')
s.advance(r,3)
s.on_robot_done(r,3,'dropoff')
energy={'name':'service_energy_guard','passed':s.energy<=.1+1e-9,
        'available':.1,'charged_consumption':s.energy,'remaining':r['battery'],
        'rescued_after_action':person.id in s.rescued}
s=Simulation(w,'rescue','greedy');r=s.robots[0]
r.update(pos=[1.4,1.0],target=person.id,state='waiting')
s.robot_leg(r,0,'to_person')
planned=r['current']['path'][0] if r['current'] else None
continuous={'name':'continuous_replan_origin','passed':planned==[1.4,1.0],
            'actual_origin':[1.4,1.0],'new_path_origin':planned}
report={'source_version':'untouched user v0.3.0','scope':'direct boundary-method probes, not full benchmark outcomes',
        'checks':[energy,continuous]}
out=ROOT/'artifacts/metarescue-v03';out.mkdir(parents=True,exist_ok=True)
(out/'boundary-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(int(any(not c['passed'] for c in report['checks'])))
