"""Reproducible CSV runner. This uses the same engine and settings as the site."""
from __future__ import annotations
import argparse,csv
from pathlib import Path
from world import World, DEFAULT_PROB,SCENARIOS
from simulation import run_collection


def main():
    p=argparse.ArgumentParser(description='MetaRescue v0.3 offline benchmark series')
    p.add_argument('--seeds',type=int,default=5,help='Number of independent fixed seeds')
    p.add_argument('--seed-start',type=int,default=2026)
    p.add_argument('--mode',choices=['scout','rescue','mission','all'],default='mission')
    p.add_argument('--scenario',choices=SCENARIOS,default='urban')
    p.add_argument('--map-size',type=int,choices=[25,35,45,55,65],default=25)
    p.add_argument('--people',type=int,default=16)
    p.add_argument('--scouts',type=int,default=3)
    p.add_argument('--rescuers',type=int,default=4)
    p.add_argument('--output',default='results_v03.csv')
    for key in DEFAULT_PROB:
        p.add_argument('--'+key.replace('_','-'),type=float,default=DEFAULT_PROB[key],
                       help='Probability 0..100%% per 30 model seconds')
    args=p.parse_args()
    if not 1<=args.seeds<=200: p.error('--seeds must be in 1..200')
    prob={key:getattr(args,key) for key in DEFAULT_PROB}
    rows=[]
    for offset in range(args.seeds):
        seed=args.seed_start+offset
        w=World(seed,args.people,args.scenario,args.map_size,args.scouts,args.rescuers,prob)
        for mode in (['scout','rescue','mission'] if args.mode=='all' else [args.mode]):
            data=run_collection(mode,w)
            for r in data['runs']:
                f=r['final'];rows.append({'version':'0.3.0','seed':seed,'mode':mode,
                    'scenario':args.scenario,'map_size':args.map_size,'scouts':args.scouts,
                    'rescuers':args.rescuers,'people_initial':args.people,'people_total':len(w.people),
                    'events':len(w.events),'method':r['method'],'found':f['found'],
                    'rescued':f['rescued'],'coverage':f['coverage'],
                    'energy_Wh':f['energy'],'replans':f['replans'],'blocked':f['blocked'],
                    'environment_exposures':f['incidents'],'last_rescue_s':f['last_rescue'],
                    'finished_at_s':f['finished_at'],'planner_ms':f['compute_ms'],
                    'wall_ms':f['wall_ms']})
        print(f'Seed {seed}: {len(rows)} accumulated result rows',flush=True)
    out=Path(args.output).resolve()
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    print('CSV saved:',out)

if __name__=='__main__':main()
