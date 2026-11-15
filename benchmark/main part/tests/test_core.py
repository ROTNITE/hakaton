from dataclasses import replace
import itertools
import math
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rescuebench.domain import Config, Terrain
from rescuebench.nsga2 import crowding, dominates, nondominated_fronts, optimize, order_crossover
from rescuebench.planning import Job, ScoutPlanner, schedule
from rescuebench.simulation import Comparison, Drone, Evacuation, Scouting, score
from rescuebench.batch import aggregate, run_series


SMALL = Config(width=20,height=20,people=8,drones=2,robots=3,horizon=120,population=12,generations=2)


class NSGATests(unittest.TestCase):
    def test_known_fronts_and_crowding(self):
        values=[(1,3),(2,2),(3,1),(3,3),(4,4)]
        self.assertEqual(nondominated_fronts(values),[[0,1,2],[3],[4]])
        distances=crowding([0,1,2],values)
        self.assertEqual(distances[0],math.inf)
        self.assertEqual(distances[2],math.inf)
        self.assertEqual(distances[1],2)
        self.assertFalse(dominates((1,1),(1,1)))

    def test_order_crossover_preserves_both_permutations(self):
        a=tuple(range(12));b=tuple(reversed(a))
        for seed in range(50):
            child=order_crossover(a,b,random.Random(seed))
            self.assertEqual(sorted(child),list(a))
        self.assertEqual(a,tuple(range(12)))

    def test_reproducibility_finite_front_and_cache(self):
        def evaluate(p):
            return (sum(i*v for i,v in enumerate(p)),sum(i*(5-v) for i,v in enumerate(p)))
        args=dict(seed=18,population=12,generations=4,seeds=[tuple(range(6))])
        a=optimize(6,evaluate,lambda v: v[0]+v[1]/2,**args)
        b=optimize(6,evaluate,lambda v: v[0]+v[1]/2,**args)
        self.assertEqual(a,b)
        self.assertLessEqual(a.evaluations,12*5)
        self.assertEqual(len(a.trace),5)
        for row in a.trace:
            for p,q in itertools.permutations(row['front'],2):
                self.assertFalse(dominates(p,q))
        self.assertIn(a.objectives,a.trace[-1]['front'])

    def test_single_task_exact_and_nonfinite_rejected(self):
        result=optimize(1,lambda p:(-1,2,3),lambda v:v[0])
        self.assertEqual(result.genes,(0,));self.assertEqual(result.evaluations,1)
        with self.assertRaises(ValueError):
            optimize(3,lambda p:(math.nan,),lambda v:0)


class ModelTests(unittest.TestCase):
    def test_config_validation(self):
        for data in [{'width':True},{'people':0},{'density':float('nan')},{'robot_energy':39},{'unknown':1},{'generations':25}]:
            with self.subTest(data=data),self.assertRaises(ValueError):Config.parse(data)
        self.assertEqual(Config.parse(SMALL.json()),SMALL)

    def test_ground_paths_avoid_buildings_and_match_decoder_cost(self):
        t=Terrain(SMALL)
        for p in t.people:
            path=t.base_path((p.x,p.y));self.assertEqual(path[0],t.base);self.assertEqual(path[-1],(p.x,p.y))
            actual=0
            for a,b in zip(path,path[1:]):
                self.assertEqual(math.dist(a,b),1)
                self.assertGreater(t.cells[b[1]][b[0]],0)
                self.assertEqual(t.edge_cost(a,b),t.edge_cost(b,a))
                actual+=t.edge_cost(a,b)
            self.assertAlmostEqual(actual,t.distances[(p.x,p.y)])

    def test_decoder_respects_battery_deadline_and_unavailable_robot(self):
        jobs=[Job(0,10,30,2),Job(1,30,15,2),Job(2,100,500,2)]
        objective,queues=schedule((0,1,2),jobs,[(0,0),(math.inf,0)],0,120,100)
        self.assertEqual(objective[0],-1)
        self.assertEqual(queues,[[0],[]])
        self.assertTrue(all(math.isfinite(v) for v in objective))
        self.assertAlmostEqual(objective[2],23.82)

    def test_scout_planners_do_not_use_hidden_people(self):
        t=Terrain(SMALL);drones=[Drone(i,*t.base,SMALL.drone_energy) for i in range(2)]
        coverage=t.footprint(t.base)
        for method in ['sweep','nearest','coverage','nsga2']:
            before=ScoutPlanner(method,t).plan(drones,coverage,[],0)
            old=t.people;t.people=[]
            after=ScoutPlanner(method,t).plan(drones,coverage,[],0)
            t.people=old;self.assertEqual(before,after)

    def test_scout_low_battery_can_stop_without_deadlock(self):
        c=replace(SMALL,width=60,height=60,people=20,drone_energy=40,horizon=180)
        comparison=Comparison(c,'scout');comparison.finish()
        self.assertTrue(comparison.done)
        for r in comparison.runs:
            self.assertIsNone(r.metrics(comparison.time)['all_completed_at'])
            self.assertTrue(all(d.energy>=0 for d in r.drones))
            self.assertGreaterEqual(r.finished_at,1)

    def test_one_more_person_always_beats_secondary_bonuses(self):
        good=score(4,20,[0]*4,0,500,120)
        worse=score(5,20,[120]*5,99999,500,120)
        self.assertGreater(worse,good)
        self.assertEqual(score(0,20,[],0,500,120),0)

    def test_same_information_and_no_delivery_before_discovery(self):
        c=Comparison(SMALL,'rescue');c.step(65,snapshot=False)
        self.assertTrue(all(r.scouting is c.shared_scout for r in c.runs))
        for r in c.runs:
            self.assertEqual([d.json() for d in r.scouting.drones],[d.json() for d in c.shared_scout.drones])
            for p in r.people:
                if p['assigned_at'] is not None:self.assertGreaterEqual(p['assigned_at'],p['discovered_at'])
                if p['rescued_at'] is not None:
                    self.assertGreater(p['rescued_at'],p['assigned_at'])
                    self.assertLessEqual(p['rescued_at'],c.terrain.people[p['id']].deadline)
            self.assertTrue(all(robot.energy>=-1e-8 for robot in r.robots))

    def test_future_detection_does_not_leak_into_previous_tick(self):
        t=Terrain(SMALL);s=Scouting(t,'coverage');s.discovered={0:.75}
        r=Evacuation(t,'nearest',s);r.people[0].update(status='hidden',discovered_at=None)
        r._discover(0)
        self.assertEqual(r.people[0]['status'],'hidden')
        r._discover(1)
        self.assertEqual(r.people[0]['status'],'waiting')

    def test_full_episode_reproducible_and_partial_time_explicit(self):
        a=Comparison(SMALL,'rescue');b=Comparison(SMALL,'rescue');a.finish();b.finish()
        self.assertEqual(a.time,b.time)
        for x,y in zip(a.results(),b.results()):
            x.pop('planning');y.pop('planning');self.assertEqual(x,y)
            self.assertIsNotNone(x['finished_at'])
            if x['rescued']<SMALL.people:self.assertIsNone(x['all_completed_at'])

    def test_ground_robot_actual_roundtrip_matches_decoder(self):
        t=Terrain(SMALL);p=t.people[0];t.people[0]=replace(p,deadline=120)
        s=Scouting(t,'coverage');s.discovered={0:0}
        r=Evacuation(t,'nearest',s)
        distance=t.distances[(p.x,p.y)]
        _,queues=schedule((0,),[Job(0,distance,120,p.extraction)],[(0,SMALL.robot_energy)],0,120,SMALL.robot_energy)
        self.assertEqual(queues,[[0]])
        r._assign(0)
        for now in range(1,121):
            for robot in r.robots:r._advance(robot,1,now-1)
            if r.people[0]['rescued_at'] is not None:break
        expected=distance/1.25+distance/1.05+p.extraction+2
        self.assertAlmostEqual(r.people[0]['rescued_at'],expected,places=7)
        self.assertAlmostEqual(r.energy_used,distance*2.35+.08*(p.extraction+2),places=7)

    def test_series_aggregates_paired_seeds_and_ties(self):
        result=run_series(SMALL,'scout',3)
        self.assertEqual(result['completed'],3)
        self.assertEqual(len(result['rows']),12)
        self.assertEqual({r['seed'] for r in result['rows']},{42,43,44})
        self.assertEqual(len(result['paired_nsga2']),3)
        self.assertTrue(all(p['bootstrap_95'] is not None for p in result['paired_nsga2']))
        self.assertAlmostEqual(sum(s['wins'] for s in result['summary']),3)


if __name__=='__main__':unittest.main()
