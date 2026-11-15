import json
import math
import sys
import unittest
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from world import World,TerrainState,SCENARIOS,DEFAULT_PROB,BASE
from simulation import Simulation,run_collection,MISSION_METHODS,SCOUT_METHODS,RESCUE_METHODS
from optimizer import fronts,dominates,ga

class TestWorld(unittest.TestCase):
    def test_world_settings(self):
        for n,ns,nr,p in ((25,1,1,3),(35,5,7,20),(65,10,12,80)):
            w=World(7,p,'urban',n,ns,nr)
            self.assertEqual(len(w.grid),n)
            self.assertEqual(w.scouts,ns)
            self.assertEqual(w.rescuers,nr)
            self.assertEqual(len(w.people),p+sum(e['type']=='new_target' for e in w.events))
            self.assertEqual(len(w.prior),(n//5)**2)
    def test_invalid(self):
        for opts in ({'map_size':26},{'people':81},{'people':2},{'scouts':0},
                     {'rescuers':13},{'probabilities':{'fire':101}},
                     {'probabilities':{'fire':-1}},
                     {'probabilities':{'wrong':10}}):
            with self.assertRaises(ValueError):World(**opts)
    def test_deterministic_initial_conditions(self):
        a=World(88,19,'clusters',35,4,5,{'fire':0})
        b=World(88,19,'clusters',35,4,5,{'fire':100})
        self.assertEqual(a.grid,b.grid)
        self.assertEqual(a.people[:19],b.people[:19])
    def test_event_replay(self):
        a=World(62,12,'urban',25,3,4,{'fire':80,'new_target':80})
        b=World(62,12,'urban',25,3,4,{'fire':80,'new_target':80})
        self.assertEqual(a.events,b.events)
        self.assertEqual(a.people,b.people)
        self.assertTrue(any(e.get('source')=='propagation' for e in a.events))
    def test_probability_zero_off(self):
        w=World(10,10,'urban',25,3,4,{k:0 for k in DEFAULT_PROB})
        self.assertEqual(w.events,[])
        self.assertEqual(len(w.people),10)
    def test_probability_full_generates_event(self):
        w=World(16,10,'urban',25,3,4,{'collapse':100,'new_target':100})
        self.assertEqual(sum(e['type']=='collapse' for e in w.events),len(range(30,w.horizon,30)))
        self.assertEqual(sum(e['type']=='new_target' for e in w.events),len(range(30,w.horizon,30)))
    def test_time_delayed_spawning(self):
        w=World(17,10,'urban',25,3,4,{'new_target':100})
        self.assertTrue(all(p.appeared_at>=30 for p in w.people[10:]))
        self.assertTrue(all(p.created_by_event for p in w.people[10:]))
    def test_route_cache_version_changes(self):
        w=World(55,10,'open',25,3,4,{k:0 for k in DEFAULT_PROB})
        st=TerrainState(w)
        a,b=st.route((1,1),(18,18))
        self.assertTrue(a)
        rev,c=st.route((18,18),(1,1))
        self.assertEqual(a,list(reversed(rev)))
        self.assertAlmostEqual(b,c)
        self.assertEqual(len(st.routes),2)
        st.grid[1][2]=8;st.version+=1;st.routes.clear();st._components=None
        path,_=st.route((1,1),(18,18))
        self.assertTrue(all(pt!=[2,1] for pt in path))
    def test_smoke_reduces_visibility(self):
        w=World(78,10,'urban',25,3,4,{'smoke':100})
        st=TerrainState(w)
        event=next(e for e in w.events if e['type']=='smoke')
        st.update(event['t']);x,y=event['cells'][0]
        self.assertLess(st.visibility(x,y),1)
        st.update(event['t']+200)
        self.assertEqual(st.visibility(x,y),1)
    def test_event_metadata(self):
        w=World(2026,16,'urban',25,3,4)
        for event in w.events:
            self.assertIn('id',event);self.assertIn('source',event)
            self.assertIn('confidence',event);self.assertIn('cells',event)
            self.assertLess(event['t'],w.horizon)

class TestNSGAII(unittest.TestCase):
    def test_dominance(self):
        self.assertTrue(dominates((1,2,3),(2,3,4)))
        self.assertFalse(dominates((2,2,2),(1,4,4)))
    def test_nondominated_sort(self):
        values=[(1,5),(5,1),(2,2),(6,6)]
        res=fronts(values)
        self.assertEqual(set(res[0]),{0,1,2})
        self.assertEqual(res[1],[3])
    def test_ga_real_front(self):
        out=ga(lambda rng: rng.randrange(10),lambda x:(x,9-x),
               lambda x,rng:rng.randrange(10),seed=4,population=10,generations=5)
        self.assertGreater(len(out),1)
        self.assertTrue(all(not dominates(a[1],b[1]) for a in out for b in out if a is not b))

class TestMission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w=World(2026,16,'urban',25,3,4)
        cls.data=run_collection('mission',cls.w)
    def test_five_methods(self):
        self.assertEqual(len(self.data['runs']),5)
        self.assertEqual([r['method'] for r in self.data['runs']],[m[0] for m in MISSION_METHODS])
    def test_identical_world_not_identical_results(self):
        self.assertEqual(len({tuple(r['rescues'][i]['id'] for i in range(min(5,len(r['rescues'])))) for r in self.data['runs']})>1,True)
        self.assertEqual(len(self.data['scenario']['events']),len(self.w.events))
    def test_no_rescue_before_detection(self):
        for run in self.data['runs']:
            seen={e['id']:e['t'] for e in run['discoveries']}
            for e in run['rescues']:
                self.assertIn(e['id'],seen)
                self.assertLessEqual(seen[e['id']],e['start'])
                self.assertLess(e['start'],e['t'])
                self.assertLessEqual(e['t'],self.w.horizon)
    def test_unique_people(self):
        for r in self.data['runs']:
            self.assertEqual(len({e['id'] for e in r['rescues']}),len(r['rescues']))
            self.assertEqual(len({e['id'] for e in r['discoveries']}),len(r['discoveries']))
    def test_energy_reserve(self):
        for r in self.data['runs']:
            self.assertGreaterEqual(r['final']['energy'],0)
            self.assertLessEqual(r['final']['energy'],(
                self.w.scouts*self.w.scout_battery+self.w.rescuers*self.w.rescuer_battery)*1.001)
    def test_dynamic_replans(self):
        self.assertTrue(any(r['final']['replans']>0 for r in self.data['runs']))
        self.assertTrue(any(d['type']=='environment_event' for d in self.data['runs'][0]['decisions']))
    def test_json_all_finite(self):
        json.dumps(self.data,allow_nan=False)
    def test_new_targets_not_visible_prematurely(self):
        for r in self.data['runs']:
            for d in r['discoveries']:
                truth=next(p for p in self.w.people if p.id==d['id'])
                self.assertGreaterEqual(d['t'],truth.appeared_at)
    def test_scout_and_rescue_pages(self):
        for mode,expected in [('scout',len(SCOUT_METHODS)),('rescue',len(RESCUE_METHODS))]:
            data=run_collection(mode,self.w)
            self.assertEqual(len(data['runs']),expected)
            json.dumps(data,allow_nan=False)
    def test_new_signal_after_full_initial_coverage(self):
        # If all sectors were scanned before late noise, a drone can return
        # from standby to re-inspect the already mapped sector.
        prob={k:0 for k in DEFAULT_PROB};prob['new_target']=100
        w=World(2026,3,'open',25,10,4,prob)
        r=Simulation(w,'mission','greedy_greedy').run()
        self.assertEqual(r['final']['coverage'],25)
        self.assertTrue(any(e['new'] for e in r['discoveries']))
        self.assertTrue(any(e['new'] for e in r['rescues']))
        self.assertTrue(all(e['t']>=30 for e in r['discoveries'] if e['new']))

    def test_failure_does_not_complete_trip(self):
        w=World(2026,16,'dynamic',25,3,4,{k:0 for k in DEFAULT_PROB})
        r=Simulation(w,'mission','greedy_greedy').run()
        fail=next(e for e in w.events if e['type']=='agent_failure')
        self.assertFalse(any(e['r']==fail['robot'] and e['t']>fail['t'] for e in r['rescues']))
    def test_failure_release_uses_current_position(self):
        w=World(13,8,'dynamic',25,2,2,{k:0 for k in DEFAULT_PROB})
        sim=Simulation(w,'mission','greedy_greedy')
        rob=sim.robots[1];p=w.people[0]
        sim.known[p.id]=p
        rob.update({'pos':[4.0,2.0],'carry':p.id,'target':p.id,'state':'waiting'})
        sim.claimed.add(p.id)
        sim.on_event({'type':'agent_failure','robot':1,'cells':[],'id':'test','sector':None},95)
        self.assertTrue(rob['failed'])
        self.assertNotIn(p.id,sim.claimed)
        self.assertEqual(sim.known[p.id].x,4)
        self.assertEqual(w.people[0],p)
    def test_replay_same_events_and_actions(self):
        w=World(101,8,'urban',25,3,3)
        a=Simulation(w,'mission','greedy_greedy').run()
        b=Simulation(w,'mission','greedy_greedy').run()
        self.assertEqual(a['rescues'],b['rescues'])
        self.assertEqual(a['discoveries'],b['discoveries'])
        self.assertEqual(a['replans'],b['replans'])
    def test_maximum_fleet_simulates(self):
        w=World(123,80,'urban',65,10,12,{k:0 for k in DEFAULT_PROB})
        r=Simulation(w,'mission','greedy_nsga2').run()
        self.assertLessEqual(r['final']['rescued'],len(w.people))
        self.assertLessEqual(r['final']['finished_at'],w.horizon)
        self.assertTrue(all(e['r']<w.rescuers for e in r['rescues']))

if __name__=='__main__':unittest.main()
