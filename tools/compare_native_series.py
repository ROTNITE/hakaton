"""Summarize terminal native outcomes and paired map comparisons."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analytics.metrics import VERSION, distribution, outcome_metrics, paired_interval
from tools.native_archive import IndexedRecords, file_sha256
from tools.run_native_series import read_complete, validate_design
from tools.series_plan import POLICIES, json_bytes


def controller_records(path):
    kinds = ('decision', 'scenario_trace', 'planning_trace')
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            if any(f'"record_type":"{kind}"' in line[:100] for kind in kinds):
                yield json.loads(line)


def measure(row, map_entry):
    path = Path(row['manifest'])
    mission = json.loads(path.read_bytes())
    archive = Path(mission['native_archive'])
    public = IndexedRecords(archive/'public')
    truth = IndexedRecords(archive/'truth')
    # read_complete has already verified the physical archives. Inspect their
    # terminal close and use the same audit rules as the saved-run viewer.
    final = next(truth.json_records(start=len(truth)-1))
    assert final['record_type'] == 'truth_snapshot' and final['payload']['phase'] == 'close', archive
    basic = outcome_metrics(truth.json_records(), public.json_records(),
                            controller_records(path.parent/'controller/controller.jsonl.gz'))
    return {**{key:row[key] for key in ('id','world','optimizer_seed','policy_id','episode_status','wall_elapsed_s')},
            'family': map_entry['family'], 'seed': map_entry['seed'],
            'episode_id': archive.name, 'metrics_version': VERSION, 'M1': basic['M1'], 'rescued': basic['rescued'],
            'available_targets': basic['registered_targets'], 'found': basic['found'],
            'found_50_s': basic['found_50_s'], 'found_90_s': basic['found_90_s'],
            'first_handover_s': basic['first_handover_s'], 'cutoff_s': basic['cutoff_s'],
            **{key:basic[key] for key in ('M2','M3','M4','M6','M7')},
            'vehicle_contacts': basic['M4']['vehicle_contacts']}


def report(plan, *, include_partial):
    worlds, cases = validate_design(plan)
    source = plan.parent/'execution'
    frozen = json.loads((source/'frozen.json').read_bytes())
    if file_sha256(plan) != frozen['plan_sha256']:
        raise ValueError('The plan differs from the execution manifest')
    rows = []
    incomplete = []
    for case in cases:
        world, _ = worlds[case['world']]
        expected = {**case,'layout_sha256':world['layout_sha256'],'external_tape_sha256':world['external_tape_sha256'],
                    'runtime_sha256':frozen['runtime_sha256']}
        finished = read_complete(source/case['id'],expected)
        if finished is None:
            incomplete.append(case['id'])
        else:
            rows.append(measure(finished,world))
    if incomplete and not include_partial:
        raise ValueError(f'Only {len(rows)}/{len(cases)} native results are complete')
    groups = {}
    all_policies = [item[0] for item in POLICIES]
    for policy in all_policies:
        subset = [r for r in rows if r['policy_id']==policy]
        groups[policy] = {'episodes':len(subset),'terminal_statuses':dict(Counter(r['episode_status'] for r in subset)),
            'M1': distribution([r['M1']['value'] for r in subset]),
            'rescued':distribution([r['rescued'] for r in subset]),
            'energy_wh':distribution([r['M3']['energy_wh'] for r in subset]),
            'wall_elapsed_s':distribution([r['wall_elapsed_s'] for r in subset]),
            'vehicle_contacts':sum(r['vehicle_contacts'] for r in subset)
                if subset and all(r['vehicle_contacts'] is not None for r in subset) else None}
    observations = {(r['world'],r['optimizer_seed'],r['policy_id']):r for r in rows}
    comparisons = {}
    for left,right in [*((p,'dual-off') for p in all_policies if p!='dual-off'),('dual-global-local','dual-global')]:
        paired = [(row,observations[(row['world'],row['optimizer_seed'],right)]) for row in rows if row['policy_id']==left
                  and (row['world'],row['optimizer_seed'],right) in observations]
        def interval(field,family=None):
            triples = [(a['world'],field(a),field(b)) for a,b in paired
                       if (family is None or a['family']==family) and field(a) is not None and field(b) is not None]
            return paired_interval(triples)
        comparisons[left+' vs '+right] = {'M1':interval(lambda r:r['M1']['value']),
            'rescued':interval(lambda r:r['rescued']), 'energy_wh':interval(lambda r:r['M3']['energy_wh']),
            'M1_by_family':{family:interval(lambda r:r['M1']['value'],family) for family in ('S1','S2','S3','S4','S5','S6')}}
    result = {'planned':len(cases),'complete':len(rows),'incomplete':incomplete,
              'plan_sha256':frozen['plan_sha256'],'runtime_sha256':frozen['runtime_sha256'],
              'policies':groups,'paired_intervals':comparisons,'episodes':rows,
              'M5':{'status':'not_verified','value':None,'basis':'requires real cross-team implementations'},
              'M7':{'complete_archives':len(rows),'frozen_world_count':len(worlds),
                    'native_protocol_and_visual_evidence':'see separate acceptance matrix'},
              'official_total':None}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--include-partial',action='store_true')
    args = parser.parse_args()
    data = report(args.plan.resolve(strict=True),include_partial=args.include_partial)
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'comparison.json').write_bytes(json_bytes(data))
    with (args.output/'episodes.csv').open('x',encoding='utf-8-sig',newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(('case','world','family','policy','optimizer_seed','status','m1','rescued',
                         'available_targets','energy_wh','vehicle_contacts','wall_elapsed_s','episode_id'))
        for row in data['episodes']:
            writer.writerow((row['id'],row['world'],row['family'],row['policy_id'],row['optimizer_seed'],
                             row['episode_status'],row['M1']['value'],row['rescued'],row['available_targets'],
                             row['M3']['energy_wh'],row['vehicle_contacts'],row['wall_elapsed_s'],row['episode_id']))
    print(json.dumps({'complete':data['complete'],'planned':data['planned'],'output':str(args.output.resolve())}))


if __name__=='__main__':
    main()
