"""Headless benchmark: python -m rescuebench.cli --mode both --count 5."""
import argparse
import csv
import json
from pathlib import Path

from .batch import run_series
from .domain import Config


def main():
    parser=argparse.ArgumentParser(description="Воспроизводимая серия Rescue Lab")
    parser.add_argument('--mode',choices=['scout','rescue','both'],default='both')
    parser.add_argument('--count',type=int,default=5)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--config',type=Path,help='JSON с полями Config')
    parser.add_argument('--output',type=Path,default=Path('results'))
    args=parser.parse_args()
    data=json.loads(args.config.read_text(encoding='utf-8')) if args.config else {}
    data['seed']=args.seed
    config=Config.parse(data)
    args.output.mkdir(parents=True,exist_ok=True)
    for mode in (['scout','rescue'] if args.mode=='both' else [args.mode]):
        print(mode,flush=True)
        result=run_series(config,mode,args.count,progress=lambda done,total:print(f'  {done}/{total}',flush=True))
        (args.output/f'{mode}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        fields=['seed','algorithm','label','found','rescued','expired','score','finished_at','all_completed_at',
                'mean_response','seconds_per_person','people_per_minute','energy','energy_ground',
                'energy_drone','energy_per_person','coverage','status',
                'planning.calls','planning.evaluations','planning.mean_ms','planning.max_ms','planning.total_ms']
        with (args.output/f'{mode}.csv').open('w',encoding='utf-8-sig',newline='') as file:
            writer=csv.DictWriter(file,fieldnames=fields,delimiter=';');writer.writeheader()
            for row in result['rows']:
                writer.writerow({k:row['planning'].get(k.split('.')[1]) if k.startswith('planning.') else row.get(k) for k in fields})
        for row in result['summary']:
            k='found' if mode=='scout' else 'rescued'
            print(f"  {row['algorithm']}: {row[k]['mean']:.2f} people; score {row['score']['mean']:.3f}; CPU {row['planning_ms']['mean']:.2f} ms/plan",flush=True)


if __name__=='__main__':main()
