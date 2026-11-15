"""Export a user-supplied benchmark world for Unreal; environment truth only."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
def main():
    p=argparse.ArgumentParser();p.add_argument('--seed',type=int,default=2026)
    p.add_argument('--people',type=int,default=16);p.add_argument('--size',type=int,default=25)
    p.add_argument('--drones',type=int,default=3);p.add_argument('--robots',type=int,default=4)
    p.add_argument('--source-version',choices=['0.2','0.3'],default='0.3')
    a=p.parse_args()
    baseline=ROOT/'benchmarks'/('metarescue-v'+a.source_version)/'main part'
    sys.path.insert(0,str(baseline))
    if a.source_version=='0.3':
        from world import World, TerrainState, DEFAULT_PROB
        from simulation import Simulation
        # Static snapshot for the first physics environment; dynamic v0.3 rules
        # remain in the 2D benchmark until the public event adapter is implemented.
        world=World(a.seed,a.people,'urban',a.size,a.drones,a.robots,{k:0 for k in DEFAULT_PROB})
        terrain=TerrainState(world)
        scout=Simulation(world,'scout','nsga2').run()
        waypoints=[[s['path'][-1] for s in scout['segments']
                    if s['r']==r and s['action']=='scout_move'] for r in range(world.scouts)]
        path=lambda person:terrain.route((1,1),(person.x,person.y))[0]
    else:
        from world import World
        from scout import run_scout
        world=World(a.seed,a.people,'urban',a.size,a.drones,a.robots)
        scout=run_scout(world,'nsga2',small=True)
        waypoints=[[world.center(s) for s in route] for route in scout['routes']]
        path=lambda person:world.route((1,1),(person.x,person.y))[0]
    data=world.public_map();data['source']='MetaRescue Benchmark v'+a.source_version+' user import'
    data['source_version']=a.source_version
    data['dynamics_note']='Static benchmark snapshot. Only the separate Chaos collapse demo runs in 3D.'
    data['kind']='environment_truth_not_controller_observation'
    data['centimetres_per_cell']=1000
    data['source_world_sha256']=hashlib.sha256((baseline/'world.py').read_bytes()).hexdigest()
    data['people']=[{'id':v.id,'x':v.x,'y':v.y,'priority':v.priority,
                     'path':path(v)} for v in world.people]
    data['scout_policy']='nsga2'
    data['scout_waypoints']=waypoints
    out=ROOT/'unreal'/'MetaRescue'/'Content'/'Scenario'/'scenario.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Exported',out,'targets',len(world.people),'grid',a.size,'source',a.source_version)


if __name__=='__main__':main()
