"""Evaluate Pareto fronts on identical scouting and rescue problems."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analytics.metrics import hypervolume, igd_plus, nondominated, normalize
from controller.navigation import observed_surfaces
from controller.optimization import optimize_rescue, optimize_scout
from controller.policy import PAIRS, heuristic_rescue
from controller.problem_builder import ProblemBuilder
from tools.native_archive import IndexedRecords
from tools.series_plan import OPTIMIZER_SEEDS, digest, json_bytes


def cases_from(archive):
    cases = {}
    for record in IndexedRecords(archive/'public').json_records():
        if record['record_type'] != 'observation':
            continue
        observation = record['payload']
        announced = observation.get('metaevolution',{}).get('announced_map')
        if not announced:
            continue
        builder = None
        if 'scout' not in cases:
            builder = ProblemBuilder(announced,surfaces=observed_surfaces(observation))
            problem = builder.scout(observation).problem
            if problem.n and problem.m:
                cases['scout'] = (problem,record)
        waiting = [t for t in observation['targets'] if t.get('status')=='confirmed' and
                   t.get('evacuation_state','waiting')=='waiting']
        if 'rescue' not in cases and len(waiting)>=2:
            builder = builder or ProblemBuilder(announced,surfaces=observed_surfaces(observation))
            jobs = {a['id']:{'target_id':a['physical']['cargo_target_id'],'phase':'return'}
                    for a in observation['agents'] if a.get('physical',{}).get('cargo_target_id')}
            problem = builder.rescue(observation,jobs)
            if problem.n>=2 and problem.m:
                cases['rescue'] = (problem,record)
        if len(cases)==2:
            break
    return cases


def physical_bounds(kind,problem):
    if kind == 'rescue':
        priority = sum(t.priority for t in problem.targets)
        worst_energy = max((trip.energy_wh for matrix in (problem.trips,problem.first)
                            for row in matrix for trip in row if trip is not None),default=0.)
        return [0.,0.,0.],[max(1.,priority),max(1.,priority*problem.horizon),max(1.,worst_energy*problem.n)]
    longest = max((x for matrix in (problem.distances,problem.initial) for row in matrix
                   for x in row if x is not None),default=0.)
    initial_seconds = max((x for row in (problem.initial_seconds or ()) for x in row if x is not None),default=0.)
    initial_energy = max((x for row in (problem.initial_wh or ()) for x in row if x is not None),default=0.)
    slowest = min(crew.speed for crew in problem.crew)
    leg = max(initial_seconds,longest/slowest)+problem.scan_s
    time_bound = max(problem.now,*(c.ready_at for c in problem.crew))+problem.n*leg
    penalty = 2*problem.m*max(0.,time_bound-problem.horizon)
    energy = problem.n*(max(initial_energy,longest*problem.wh_per_m)+problem.scan_wh+leg*problem.idle_power_w/3600)
    return [-max(1.,sum(s.prior for s in problem.sectors)),0.,0.],[
        max(1.,penalty),max(1.,time_bound+penalty),max(1.,energy+penalty)]


def problem_data(kind,problem):
    data = {'crew':[asdict(c) for c in problem.crew],'now':problem.now,'horizon':problem.horizon}
    if kind == 'scout':
        data['sectors'] = [asdict(s) for s in problem.sectors]
        for name in ('distances','initial','initial_seconds','initial_wh','returns','scan_s',
                     'scan_wh','wh_per_m','idle_power_w'):
            data[name] = getattr(problem,name)
    else:
        data['targets'] = [asdict(t) for t in problem.targets]
        for name in ('trips','first'):
            data[name] = [[asdict(trip) if trip is not None else None for trip in row] for row in getattr(problem,name)]
    return data


def singleton_scout(problem,method):
    routes = problem.heuristic(method)
    assignment = [0]*problem.n
    for r,route in enumerate(routes):
        for i in route:
            assignment[i] = r
    order = [i for route in routes for i in route]
    values,_ = problem.simulate((order,assignment))
    return {'selected_objectives': values, 'pareto': [], 'stats': {'evaluations':1}}


def score(kind,problem,low,high):
    normalizer = lambda points: normalize(points,low,high)
    optimize = optimize_scout if kind=='scout' else optimize_rescue
    budget = (40,32) if kind=='scout' else (26,17)
    methods = sorted({algorithms[0 if kind=='scout' else 1] for algorithms in PAIRS.values()})
    plans = {}
    def points(plan):
        return [r['objectives'] for r in plan['pareto']] or [plan['selected_objectives']]
    for method in methods:
        for seed in OPTIMIZER_SEEDS:
            plan = (optimize(problem,seed,population=budget[0],generations=budget[1]) if method=='nsga2' else
                    singleton_scout(problem,method) if kind=='scout' else heuristic_rescue(problem,method))
            plans[(method,seed)] = {'points': points(plan),'stats':plan['stats']}
    reference = nondominated([p for plan in plans.values() for p in plan['points']]+
                             [p for seed in OPTIMIZER_SEEDS for p in points(optimize(problem,seed,population=80,generations=64))])
    reference_point = [1.05,1.05,1.05]
    normalized_reference = normalizer(reference)
    rows = []
    for (method,seed),plan in plans.items():
        normalized = normalizer(plan['points'])
        if any(v < -1e-9 or v > 1.+1e-9 for point in normalized for v in point):
            raise ValueError('Objective outside predeclared physical bounds')
        rows.append({'algorithm':method,'optimizer_seed':seed,**plan,
                     'HV':hypervolume(normalized,reference_point),'IGD_plus':igd_plus(normalized,normalized_reference)})
    return {'optimization_budget':budget,'HV_reference_point':reference_point,
            'IGD_plus_reference':'empirical non-dominated union including 80×64 reference runs',
            'reference_front':reference,'methods':rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('archives',type=Path,nargs='+')
    args = parser.parse_args()
    cases = {}
    frozen = {}
    for archive in args.archives:
        archive = archive.resolve(strict=True)
        for kind,(problem,record) in cases_from(archive).items():
            case_id = archive.name+'-'+kind
            bounds = physical_bounds(kind,problem)
            source = {'episode_id':archive.name,'trace_id':record['trace_id'],'time_s':record['time'],
                      'observation_sha256':digest(record['payload'])}
            data = problem_data(kind,problem)
            frozen[case_id] = {'source':source,'kind':kind,'normalization_bounds':bounds,
                               'problem_sha256':digest(data),'problem':data}
            cases[case_id] = (kind,problem,bounds)
    if {case[0] for case in cases.values()} != {'scout','rescue'}:
        raise ValueError('Both scouting and rescue problems require matching saved public observations')
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'common-problems.json').write_bytes(json_bytes(frozen))
    results = {identifier:score(kind,problem,*bounds) for identifier,(kind,problem,bounds) in cases.items()}
    (args.output/'pareto-comparison.json').write_bytes(json_bytes(
        {'format':'metarescue.common-pareto.v1','common_problems_sha256':digest(frozen),'results':results}))
    print(json.dumps({'problems':len(cases),'results':str((args.output/'pareto-comparison.json').resolve())}))


if __name__ == '__main__':
    main()
