import unittest,sys,math,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from world import World,HORIZON,SECTORS,RESCUERS,GROUND_BATTERY,ENERGY_RESERVE
from scout import run_scout
from rescue import run_rescue,prepare,trip
from mission import run_mission
from nsga2 import run_nsga2,dominates

class TestMetaRescue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world=World(2026,16)
    def test_world_same_seed(self):
        other=World(2026,16)
        self.assertEqual(other.grid,self.world.grid)
        self.assertEqual(other.people,self.world.people)
    def test_ground_paths_are_walkable(self):
        w=self.world
        for p in w.people:
            path,cost=w.route((1,1),(p.x,p.y))
            for x,y in path:self.assertTrue(w.walkable(int(x),int(y)))
            self.assertTrue(cost>0 or math.isinf(cost))
    def test_preset_variants(self):
        from world import SCENARIOS
        self.assertEqual(len(SCENARIOS),6)
        for kind in SCENARIOS:
            w=World(42,8,kind)
            self.assertEqual(len(w.people),8)
            a=run_scout(w,'greedy')
            self.assertLessEqual(sum(s['e'] for s in a['segments'] if s['r']==0),
                                 w.scout_battery*(1-ENERGY_RESERVE)+.0001)
        w=World(42,8,'uncertain')
        self.assertLess(w.sensor_reliability,1.0)

    def test_dynamic_failure_cancels_a_trip(self):
        w=World(2026,16,'dynamic')
        r=run_mission(w,'greedy_greedy')
        self.assertEqual(len(r['failures']),1)
        fail=r['failures'][0]
        self.assertEqual(fail['robot'],1)
        self.assertEqual(fail['t'],95.0)
        for rescue in r['rescues']:
            self.assertFalse(rescue['r']==1 and rescue['t']>95.0)

    def test_search_complete_nonduplicated(self):
        for method in ['random','sweep','greedy','frontier','nsga2']:
            run=run_scout(self.world,method,small=True)
            ids=[v['sector'] for v in run['visits']]
            self.assertEqual(len(ids),SECTORS*SECTORS)
            self.assertEqual(len(set(ids)),len(ids))
            self.assertEqual(run['final']['found'],len(self.world.people))
            self.assertEqual(sorted(v['id'] for v in run['discoveries']),
                             sorted(p.id for p in self.world.people))
    def test_search_no_secret_coordinates(self):
        a=World(13,16); b=World(13,16)
        b.people=[] # world geometry and satellite prior stay unchanged
        self.assertEqual(run_scout(a,'nsga2',small=True)['routes'],
                         run_scout(b,'nsga2',small=True)['routes'])
    def test_rescue_unique_and_energy_safe(self):
        w=self.world
        for method in ('nearest','greedy','local','nsga2'):
            run=run_rescue(w,method,small=True)
            ids=[e['id'] for e in run['rescues']]
            self.assertEqual(len(ids),len(set(ids)))
            self.assertTrue(all(e['t']<=HORIZON+0.001 for e in run['rescues']))
            self.assertEqual(sum(len(v) for v in run['plan']),len(ids))
            for r in range(RESCUERS):
                energy=sum(trip(w,next(p for p in w.people if p.id==pid),r)['energy']
                           for pid in run['plan'][r])
                self.assertLessEqual(energy,GROUND_BATTERY*(1-ENERGY_RESERVE)+.0001)
    def test_online_not_oracle(self):
        w=self.world
        run=run_mission(w,'nsga2_nsga2')
        discovered={e['id']:e['t'] for e in run['discoveries']}
        for rescued in run['rescues']:
            self.assertGreater(rescued['t'],discovered[rescued['id']])
        assigned={assignment['person'] for d in run['decisions'] for assignment in d['assignments']}
        self.assertEqual(assigned,{r['id'] for r in run['rescues']})
        self.assertEqual(len(assigned),len(run['rescues']))
    def test_nondominated_front(self):
        def init(rng):return rng.uniform(-3,3)
        def mate(a,b,rng):return ((a+b)/2,rng.choice([a,b]))
        def mutate(a,rng):return a+rng.uniform(-.2,.2)
        front,stats=run_nsga2(init,lambda x:((x-1)**2,(x+1)**2),mate,mutate,
                              pop_size=16,generations=10,seed=9)
        self.assertTrue(front)
        self.assertTrue(all(not dominates(q.f,p.f) for i,p in enumerate(front)
                            for j,q in enumerate(front) if i!=j))
        self.assertGreater(stats['evaluations'],0)
    def test_json_serialization(self):
        run=run_rescue(self.world,'nsga2',small=True)
        self.assertGreater(len(json.dumps(run,allow_nan=False)),100)

if __name__=='__main__':unittest.main()
