"""v0.4-specific regression tests for isolated competitors, AI and full audit."""
from __future__ import annotations
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from world import World,DEFAULT_PROBABILITIES
from ai_control import AIController,AIClient
from server import params,run_collection
from log_export import log_chunks

class TestV04(unittest.TestCase):
    def test_maximum_world_and_bounds(self):
        w=World(101,600,'urban',150,48,40,{k:0 for k in DEFAULT_PROBABILITIES})
        self.assertEqual(w.grid_size,150)
        self.assertEqual(len(w.people),600)
        self.assertEqual((w.n_scouts,w.n_rescuers),(48,40))
        self.assertGreater(w.horizon,480)
        with self.assertRaises(ValueError):
            World(101,601,'urban',150,48,40)

    def test_unavailable_ai_is_not_mock(self):
        c=AIClient(mode='off',max_calls=5)
        entries=[]
        response,delay=c.decide('global',{'known_targets':[]},entries,12.0)
        self.assertIsNone(response)
        self.assertEqual(c.calls,0)
        self.assertEqual(entries[-1]['type'],'AI_UNAVAILABLE')

    def test_global_only_confirmed_targets(self):
        world=World(44,8,'urban',25,2,3,{k:0 for k in DEFAULT_PROBABILITIES})
        ctrl=AIController(world,'global_ai',mode='mock',max_calls=3)
        confirmed=world.people[:2]  # only the supplied observations are available
        result,_=ctrl.global_event(50,'test',confirmed,[],force=True)
        self.assertTrue(set(result['priority_ids']) <= {p.id for p in confirmed})
        self.assertTrue(any(e['type']=='AI_API_REQUEST' for e in ctrl.audit))
        self.assertEqual(ctrl.client.role_calls['local'],0)

    def test_local_decision_and_message(self):
        world=World(44,8,'urban',25,2,3,{k:0 for k in DEFAULT_PROBABILITIES})
        ctrl=AIController(world,'global_local_ai',mode='mock',max_calls=8)
        options=[{'id':'detour_to_target','type':'DETOUR','duration':20,'energy':12,
                  'destination':[2,2]}]
        choice,_=ctrl.local_event(50,0,3,'collapse',[4,5],False,options,150.)
        self.assertEqual(choice['id'],'detour_to_target')
        self.assertEqual(ctrl.client.role_calls['local'],1)
        self.assertTrue(any(x['recipient']=='global' for x in ctrl.messages))
        self.assertTrue(any(e['type']=='LOCAL_ACCEPTED' for e in ctrl.audit))

    def test_comparison_same_world_full_txt_each_second(self):
        args=('mission',701,8,'open',25,2,2,tuple(sorted({k:0 for k in DEFAULT_PROBABILITIES}.items())),
              'mock',3,3.,6.,'v04-test-701')
        data=run_collection(*args)
        self.assertEqual([r['method'] for r in data['runs']],
            ['base','global_ai','global_local_ai'])
        self.assertEqual(data['runs'][0]['ai_stats']['calls'],0)
        self.assertTrue(all(r['final']['total']==8 for r in data['runs']))
        self.assertNotIn('DEEPSEEK_API_KEY',str(data))
        chunks=list(log_chunks(data))
        self.assertEqual(sum(c.count(b'TRUTH_MAP_BEGIN') for c in chunks),
            3*(data['scenario']['horizon']+1))
        # No reason to call the LLM in a tiny, disturbance-free mission.
        self.assertTrue(all(run['ai_stats']['calls']==0 for run in data['runs']))
        self.assertTrue(any(b'MOVE scout_segments' in c for c in chunks))

    def test_parameter_validation(self):
        with self.assertRaises(ValueError):params({'map_size':['151']})
        with self.assertRaises(ValueError):params({'people':['601']})
        with self.assertRaises(ValueError):params({'ai_mode':['unsafe']})
        with self.assertRaises(ValueError):params({'ai_calls':['1601']})

if __name__=='__main__':unittest.main()
