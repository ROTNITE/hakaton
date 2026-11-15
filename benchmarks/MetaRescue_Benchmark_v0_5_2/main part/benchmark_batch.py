"""CLI reproducible benchmark sweep. Saves raw results to CSV (stdlib only).
Usage: python 'main part/benchmark_batch.py' --seeds 30 --mode all
"""
from __future__ import annotations
import argparse,csv,statistics,time
from pathlib import Path
from world import World, DEFAULT_PROBABILITIES
from scout import run_scout
from rescue import run_rescue
from mission import run_mission

SCOUT=['random','sweep','greedy','frontier','nsga2']
RESCUE=['nearest','greedy','local','nsga2']
MISSION=['greedy_greedy','frontier_local','nsga2_greedy','greedy_nsga2','nsga2_nsga2']

def main():
    ap=argparse.ArgumentParser(description='MetaRescue multi-seed benchmarks')
    ap.add_argument('--seeds',type=int,default=10,help='Number of different maps / seeds')
    ap.add_argument('--start-seed',type=int,default=2026)
    ap.add_argument('--people',type=int,default=16)
    ap.add_argument('--scenario',choices=['open','urban','clusters','scarce','uncertain','dynamic'],default='urban')
    ap.add_argument('--mode',choices=['scout','rescue','mission','all'],default='all')
    ap.add_argument('--map-size',type=int,choices=[25,35,45,55,65],default=25)
    ap.add_argument('--scouts',type=int,default=3)
    ap.add_argument('--rescuers',type=int,default=4)
    for key in DEFAULT_PROBABILITIES:
        ap.add_argument('--p-'+key.replace('_','-'),type=int,default=0)
    ap.add_argument('--output',default='benchmark_results.csv')
    a=ap.parse_args()
    if a.seeds<1:ap.error('--seeds must be >= 1')
    probs={key:getattr(a,'p_'+key) for key in DEFAULT_PROBABILITIES}
    if any(v<0 or v>100 for v in probs.values()):ap.error('probabilities must be 0..100')
    modes=['scout','rescue','mission'] if a.mode=='all' else [a.mode]
    rows=[]
    for i in range(a.seeds):
        seed=a.start_seed+i
        world=World(seed,a.people,a.scenario,a.map_size,a.scouts,a.rescuers,probs)
        cache={}
        for mode in modes:
            methods={'scout':SCOUT,'rescue':RESCUE,'mission':MISSION}[mode]
            for method in methods:
                if mode=='scout':run=run_scout(world,method)
                elif mode=='rescue':run=run_rescue(world,method)
                else:
                    from mission import CONFIGS
                    scout_method=CONFIGS[method][0]
                    if scout_method not in cache:cache[scout_method]=run_scout(world,scout_method,small=True)
                    run=run_mission(world,method,cache)
                f=run['final']
                row={'seed':seed,'people':world.n_people,'scenario':a.scenario,'mode':mode,'method':method,
                     'new_people':len(world.appearances),'terrain_events':len(world.landscape_events),
                     'interrupted':len(run.get('incidents',[])),
                     'found':f.get('found',''),'rescued':f.get('rescued',''),
                     'coverage':f.get('coverage',''),'first_detection_s':f.get('first',''),
                     'last_rescue_s':f.get('last_rescue',''),
                     'finish_time_s':f.get('finished_at',''),
                     'energy_Wh':f.get('energy',''),
                     'plan_ms':run.get('opt',{}).get('wall_ms',''),
                     'replans':run.get('opt',{}).get('replans','')}
                rows.append(row)
        print(f'Прогон {i+1}/{a.seeds}: seed={seed}, строк={len(rows)}',flush=True)
    out=Path(a.output)
    with out.open('w',newline='',encoding='utf-8-sig') as fh:
        w=csv.DictWriter(fh,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print('Готово:',out.resolve(),'-',len(rows),'измерений')
    print('\nСредние показатели по алгоритмам:')
    for mode in modes:
        methods={'scout':SCOUT,'rescue':RESCUE,'mission':MISSION}[mode]
        for method in methods:
            sub=[r for r in rows if r['mode']==mode and r['method']==method]
            key='found' if mode=='scout' else 'rescued'
            avg=statistics.mean(float(x[key]) for x in sub)
            energy=statistics.mean(float(x['energy_Wh']) for x in sub)
            ms=statistics.mean(float(x['plan_ms']) for x in sub)
            print(f' {mode:7s} {method:17s} {key}: {avg:5.2f}  Wh: {energy:7.1f}  compute-ms: {ms:8.1f}')

if __name__=='__main__':main()
