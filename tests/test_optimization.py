import importlib
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

from contracts.protocol import encode
from controller.optimization import Crew,RescueProblem,ScoutProblem,Sector,Target,Trip,optimize_rescue,optimize_scout
from controller.strategies import continuation_forecast,propose,worthwhile


class PublicOptimizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reference=Path(__file__).parents[1]/'benchmarks/MetaRescue_Benchmark_v0_5_2/main part'
        names=('world','nsga2','scout','rescue','strategy_engine')
        saved={name:sys.modules.pop(name,None) for name in names}
        sys.path.insert(0,str(reference))
        try:
            cls.scout=importlib.import_module('scout')
            cls.rescue=importlib.import_module('rescue')
            cls.strategy=importlib.import_module('strategy_engine')
        finally:
            sys.path.remove(str(reference))
            for name in names:
                sys.modules.pop(name,None)
                if saved[name] is not None:sys.modules[name]=saved[name]

    def scouting(self):
        positions=[(2.5,2.5),(7.5,2.5),(2.5,7.5),(7.5,7.5)]
        prior=[.7,1.,1.2,.8]
        world=SimpleNamespace(n_scouts=2,sector_count=2,horizon=100,prior=prior,
                              center=lambda i:positions[i],scout_speed=lambda i:(2.1,1.95)[i])
        distances=[[math.hypot(a[0]-b[0],a[1]-b[1]) for b in positions] for a in positions]
        initial=[[math.hypot(x-1,y-1) for x,y in positions] for _ in range(2)]
        problem=ScoutProblem([Sector('sector-'+str(i),prior[i],i%2,i//2) for i in range(4)],
            [Crew('opaque-wing',2.1),Crew('without-prefix',1.95)],distances,initial,
            horizon=100,wh_per_m=.69)
        return world,problem

    def test_scout_metrics_heuristics_and_optimization_match_upstream(self):
        world,problem=self.scouting()
        for method in ('greedy','sweep','frontier'):
            self.assertEqual(problem.heuristic(method),self.scout.heuristic_routes(world,method,7))
        for seed in (7,42,2026):
            original,stats=self.scout.optimize_routes(world,seed,population=12,generations=4)
            adapted=optimize_scout(problem,seed,population=12,generations=4)
            self.assertEqual(list(adapted['routes'].values()),[[problem.sectors[i].id for i in route] for route in original])
            self.assertEqual([round(x,3) for x in adapted['selected_objectives']],stats['selected_objectives'])
            self.assertEqual(adapted['stats']['evaluations'],stats['evaluations'])
            self.assertEqual([[round(x,2) for x in row['objectives']] for row in adapted['pareto']],stats['pareto'])
            encode(adapted)  # infinite crowding becomes an explicit boundary flag

    def test_rescue_evaluation_and_winner_match_upstream_for_three_seeds(self):
        people=[SimpleNamespace(id=i,priority=p) for i,p in enumerate((1,3,2,1))]
        raw=[[{'duration':d,'energy':e} for d,e in row] for row in (
            ((12,10),(8,20),(20,8),(30,12)),((10,12),(9,18),(18,9),(25,10)))]
        problem=RescueProblem([Target('opaque-'+str(p.id),p.priority) for p in people],
            [Crew('carrier-A'),Crew('carrier-B',ready_at=3)],
            [[Trip(t['duration'],t['energy']) for t in row] for row in raw],horizon=50)
        world=SimpleNamespace(ground_battery=220,horizon=50)
        for seed in (7,42,2026):
            original,stats=self.rescue.optimize_rescue(world,people,raw,seed,available=[0,3],population=12,generations=4)
            adapted=optimize_rescue(problem,seed,population=12,generations=4)
            self.assertEqual(adapted['genome'],original)
            self.assertEqual(adapted['selected_objectives'],list(self.rescue.eval_plan(original,people,raw,available=[0,3],horizon=50)[0]))
            self.assertEqual(adapted['stats']['evaluations'],stats['evaluations'])
            self.assertEqual([[round(x,2) for x in row['objectives']] for row in adapted['pareto']],stats['pareto'])

    def test_rescue_busy_deadline_and_finite_energy_are_constraints(self):
        problem=RescueProblem([Target('critical',3,deadline=8),Target('later',1)],
            [Crew('busy',ready_at=10),Crew('limited',usable_wh=5)],
            [[Trip(4,2),Trip(4,2)],[Trip(4,6),Trip(4,3)]],horizon=30)
        fitness,tasks=problem.simulate(([0,1],[0,1]))
        self.assertEqual(fitness[0],3)
        self.assertEqual(tasks[0],[])
        self.assertEqual(tasks[1][0][0],1)
        with self.assertRaises(ValueError):problem.simulate(([0,0],[0,1]))

    def test_first_trip_uses_actual_pose_and_scanning_has_a_return_reserve(self):
        problem=RescueProblem([Target('a',1),Target('b',1)],[Crew('x')],
            [[Trip(20,2),Trip(20,2)]],first_trips=[[Trip(4,1),Trip(7,1)]],horizon=100)
        fitness,tasks=problem.simulate(([0,1],[0,0]))
        self.assertEqual([row[2] for row in tasks[0]],[4,24])
        scout=ScoutProblem([Sector('far')],[Crew('a',usable_wh=1)],[[0]],[[10]],horizon=100,
                           wh_per_m=.1,scan_wh=0,return_distances=[[10]])
        self.assertEqual(scout.simulate(([0],[0]))[1],[[]])

    def test_empty_and_singleton_do_not_invent_a_pareto_run(self):
        empty=RescueProblem([],[],[],horizon=100)
        self.assertEqual(optimize_rescue(empty,7)['stats']['evaluations'],0)
        singleton=RescueProblem([Target('one',1)],[Crew('only')],[[Trip(3,1)]],horizon=10)
        plan=optimize_rescue(singleton,7,population=4,generations=1)
        self.assertEqual(plan['routes'],{'only':['one']})

    def test_three_continuations_and_forecast_gate_match_reference(self):
        targets=[Target('a',3),Target('b',2),Target('c',1)]
        tasks=[[(0,8,20,Trip(12,4)),(1,20,29,Trip(9,6))],[(2,20,34,Trip(14,3))]]
        reference=[[(j,start,finish,{'duration':t.duration_s,'energy':t.energy_wh}) for j,start,finish,t in row] for row in tasks]
        self.assertEqual(continuation_forecast(tasks,targets,7,33),self.strategy.continuation_forecast(reference,targets,7,33))
        scenarios,forecast=continuation_forecast(tasks,targets,7,33)
        baseline={'id':'balanced','forecast':forecast,'continuations':scenarios}
        candidate={'id':'urgent','forecast':dict(forecast,saved=forecast['saved']-.1),
                   'continuations':scenarios}
        self.assertEqual(worthwhile(candidate,baseline),self.strategy.worthwhile(candidate,baseline))
        self.assertEqual(worthwhile(candidate,baseline),(False,'EXPECTED_RESCUE_LOSS'))
        candidate={'id':'energy_saver','forecast':forecast,'continuations':scenarios}
        self.assertEqual(worthwhile(candidate,baseline),(False,'NO_MEASURABLE_GAIN'))

    def test_five_proposals_use_real_searches_and_keep_actual_priorities(self):
        targets=[Target('first',3),Target('second',1)]
        problem=RescueProblem(targets,[Crew('opaque')],[[Trip(4,2),Trip(7,1)]],horizon=50)
        candidates=propose(problem,42,population=8,generations=2)
        self.assertEqual([c['id'] for c in candidates],['balanced','urgent','throughput','energy_saver','cooperative'])
        self.assertEqual([t.priority for t in problem.targets],[3,1])
        self.assertEqual(len({c['stats']['effective_seed'] for c in candidates}),5)
        for candidate in candidates:
            self.assertGreater(candidate['stats']['evaluations'],0)
            self.assertEqual(len(candidate['continuations']),3)
            self.assertTrue(candidate['pareto'])
            encode(candidate)


if __name__=='__main__':unittest.main()
