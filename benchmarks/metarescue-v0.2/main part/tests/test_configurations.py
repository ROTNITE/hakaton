"""Regression tests for v0.2 runtime fleet / map configuration."""
import json, sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from world import World
from scout import run_scout
from rescue import run_rescue
from mission import run_mission
from server import run_collection

class TestConfigurableBenchmarks(unittest.TestCase):
    def test_custom_world(self):
        w=World(seed=42,n_people=20,scenario='urban',grid_size=45,n_scouts=6,n_rescuers=7)
        self.assertEqual(len(w.grid),45)
        self.assertEqual(len(w.prior),81)
        self.assertEqual(len(w.people),20)
        self.assertEqual(w.public_map()['scouts'],6)
        self.assertEqual(w.public_map()['rescuers'],7)
        self.assertGreater(w.horizon,480)
        self.assertEqual(w.public_map()['width'],45)

    def test_invalid_ranges(self):
        with self.assertRaises(ValueError):World(grid_size=27)
        with self.assertRaises(ValueError):World(n_scouts=0)
        with self.assertRaises(ValueError):World(n_rescuers=13)
        with self.assertRaises(ValueError):World(n_people=81)

    def test_search_custom_agents(self):
        w=World(180,18,'open',35,5,6)
        r=run_scout(w,'nsga2',small=True)
        self.assertEqual(len(r['routes']),5)
        self.assertEqual(len({v['sector'] for v in r['visits']}),len(r['visits']))
        self.assertTrue(all(v['r']<5 for v in r['visits']))
        self.assertLessEqual(r['final']['finished_at'],w.horizon)

    def test_rescue_custom_agents(self):
        w=World(180,18,'urban',35,5,7)
        r=run_rescue(w,'nsga2',small=True)
        self.assertEqual(len(r['plan']),7)
        self.assertTrue(all('start' in e and e['start']<e['t']<=w.horizon for e in r['rescues']))
        self.assertLessEqual(r['final']['finished_at'],w.horizon)

    def test_mission_custom_and_json(self):
        w=World(180,18,'dynamic',35,5,7)
        r=run_mission(w,'greedy_nsga2')
        self.assertTrue(all(e['r']<7 for e in r['rescues']))
        self.assertLessEqual(r['final']['finished_at'],w.horizon)
        self.assertTrue(all('start' in e for e in r['rescues']))
        json.dumps(r,allow_nan=False)

    def test_same_fleet_replay(self):
        a=run_collection('scout',99,16,'clusters',35,4,6)
        b=run_collection('scout',99,16,'clusters',35,4,6)
        self.assertEqual(a['runs'][0]['discoveries'],b['runs'][0]['discoveries'])
        self.assertEqual(a['scenario']['grid'],b['scenario']['grid'])

if __name__=='__main__':unittest.main()
