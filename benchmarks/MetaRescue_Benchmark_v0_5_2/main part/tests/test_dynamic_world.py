"""v0.3 event fairness, causality and physical route invalidation tests."""
import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from world import World, DEFAULT_PROBABILITIES
from mission import run_mission, CONFIGS
from scout import run_scout
from rescue import run_rescue
from server import run_collection

class DynamicWorldTests(unittest.TestCase):
    def world(self, seed=2026, **opts):
        p=dict(DEFAULT_PROBABILITIES)
        p.update(opts)
        return World(seed,16,'urban',25,3,4,p)

    def test_events_seed_reproducibility(self):
        a=self.world();b=self.world()
        self.assertEqual(a.dynamic_events,b.dynamic_events)
        self.assertEqual(a.grid,b.grid)
        self.assertEqual(a.people,b.people)
        self.assertEqual(a.terrain_at(290).hazard,b.terrain_at(290).hazard)
        self.assertGreater(len(a.landscape_events),0)

    def test_zero_events_reproduces_static_version(self):
        p={k:0 for k in DEFAULT_PROBABILITIES}
        a=World(2026,16,'urban',25,3,4,p)
        b=World(2026,16,'urban',25,3,4)
        self.assertEqual(a.people,b.people)
        self.assertEqual(a.dynamic_events,[])
        self.assertEqual(run_scout(a,'greedy')['discoveries'],run_scout(b,'greedy')['discoveries'])

    def test_route_changes_when_road_collapses(self):
        w=self.world(7,collapse=100,fire=0,flood=0,mud=0,road_damage=0,smoke=0,appearance=0)
        path_before,_=w.route((1,1),(w.grid_size-4,w.grid_size-4))
        self.assertTrue(path_before)
        x,y=map(int,path_before[len(path_before)//2])
        # Deterministic targeted collapse, away from the origin.
        w.landscape_events=[{'t':50.,'type':'collapse','cells':[[x,y]]}]
        w._terrain_times=[50.]
        w._terrain_snapshots.clear()
        path_after,_=w.route((1,1),(w.grid_size-4,w.grid_size-4),w.terrain_at(51))
        self.assertNotIn((float(x),float(y)),path_after)
        self.assertEqual(w.terrain_at(49).walkable(x,y),True)
        self.assertEqual(w.terrain_at(51).walkable(x,y),False)

    def test_new_person_not_discovered_before_appearance(self):
        w=self.world(2026,collapse=0,fire=0,flood=0,mud=0,road_damage=0,smoke=0,appearance=100)
        self.assertGreater(len(w.appearances),0)
        for method in ('greedy','frontier','nsga2'):
            r=run_scout(w,method,small=True)
            by_id={p['id']:p for p in r['discoveries']}
            for event in w.appearances:
                if event['id'] in by_id:
                    self.assertGreaterEqual(by_id[event['id']]['t'],event['t'])
            self.assertTrue(all(e['id']<=w.initial_people or e['new'] for e in r['discoveries']))

    def test_all_five_have_same_world_events(self):
        w=self.world(2026)
        cache={}
        for config,(sc,_,_) in CONFIGS.items():
            if sc not in cache:cache[sc]=run_scout(w,sc,small=True)
            result=run_mission(w,config,cache)
            self.assertEqual(result['terrain_events'],w.landscape_events)
            found={d['id']:d['t'] for d in result['discoveries']}
            for rescue in result['rescues']:
                self.assertGreater(rescue['t'],found[rescue['id']])
            self.assertGreaterEqual(result['final']['total'],w.initial_people)
            json.dumps(result,allow_nan=False)

    def test_high_hazard_frequency_triggers_abort(self):
        w=self.world(2026,**{k:100 for k in DEFAULT_PROBABILITIES})
        r=run_mission(w,'greedy_greedy')
        self.assertTrue(r['incidents'])
        self.assertEqual(len(r['incidents']),r['opt']['aborted_trips'])
        self.assertEqual(r['opt']['stranded'],len(r['stranding']))
        self.assertTrue(all(e['t']<=w.horizon for e in r['rescues']))

    def test_collection_params_and_offline(self):
        probs=tuple(sorted(DEFAULT_PROBABILITIES.items()))
        for mode in ('mission',):
            data=run_collection(mode,2026,16,'urban',25,3,4,probs)
            self.assertEqual(data['version'],'0.5.2')
            self.assertEqual(data['scenario']['probabilities'],dict(probs))
            self.assertEqual(data['scenario']['n_people'],18)
            self.assertEqual(len(data['runs']),3)
            self.assertEqual([r['method'] for r in data['runs']],['base','global_ai','global_local_ai'])

if __name__=='__main__':unittest.main()
