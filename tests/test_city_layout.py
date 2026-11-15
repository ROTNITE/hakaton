from copy import deepcopy
import math
import unittest

from contracts.protocol import ProtocolError
from environment.config import Settings, MAP_SIZES
from environment.layout import BASE_LAYOUT_REVISION, generate, public_map, preflight, fingerprint


class CityLayoutTests(unittest.TestCase):
    def test_parked_aircraft_cannot_block_the_ground_exit(self):
        world=generate(Settings.parse({'scouts':1,'rescuers':2}))
        aerial=next(a for a in world['spawns'] if a['kind']=='aerial')
        aerial['position']=[50,18,.31]
        with self.assertRaisesRegex(ProtocolError,'preflight'):preflight(world)

    def test_base_revision_is_public_and_checks_parked_traffic(self):
        world=generate(Settings.parse({'scouts':48,'rescuers':40,'people':3}))
        self.assertEqual(public_map(world)['base_layout_revision'],BASE_LAYOUT_REVISION)
        self.assertGreater(world['preflight']['parked_exit_checks'],0)
        self.assertEqual({row['asset'] for row in public_map(world)['fixed_obstacles']},
                         {'Medical','Generator','Sensor','UtilityBox'})
    def test_settings_ranges_and_profiles(self):
        self.assertEqual(Settings.parse({'event_profile':'v3'}).event_window_s,30)
        self.assertEqual(Settings.parse({'map_size':150}).horizon,2880)
        self.assertEqual(Settings.parse({'preset':'uncertain'}).sensor_reliability,.83)
        for settings in ({'scouts':True},{'map_size':65.0},{'people':601},
                         {'communication_loss':float('nan')},{'probabilities':{'fire':100}},
                         {'event_profile':'v3','probabilities':Settings.parse().probabilities}):
            with self.subTest(settings=settings),self.assertRaises(ProtocolError):Settings.parse(settings)

    def test_repeatable_private_generation_and_public_boundary(self):
        a=generate(Settings.parse());b=generate(Settings.parse())
        self.assertEqual(fingerprint(a),fingerprint(b))
        self.assertNotEqual(fingerprint(a),fingerprint(generate(Settings.parse({'seed':2027}))))
        public=public_map(a)
        self.assertNotIn('people',public)
        self.assertNotIn('settings',public)
        self.assertNotIn('seed',str(public))
        for house in a['buildings']:
            self.assertEqual(house['bounds']['max'][0]-house['bounds']['min'][0],9.5)

    def test_presets_and_all_supported_sizes(self):
        for size in MAP_SIZES:
            with self.subTest(size=size):
                world=generate(Settings.parse({'map_size':size}))
                self.assertEqual(world['size_m'],size*10)
                self.assertTrue(world['preflight']['passed'])
        for preset in ('open','urban','clusters','scarce','uncertain','dynamic'):
            self.assertTrue(generate(Settings.parse({'preset':preset}))['preflight']['passed'])

    def test_four_street_fronts_and_authored_tree_sizes(self):
        world=generate(Settings.parse())
        self.assertEqual({h['yaw'] for h in world['buildings']},{0,90,180,270})
        self.assertLess(max(b-a for a,b in zip(world['road_axes_m'],world['road_axes_m'][1:])),50)
        for tree in world['features']:
            self.assertEqual(tree['height_m'],(5.5,6.5,7.5)[tree['model']])
            self.assertEqual(tree['obstacles'][1]['max'][2],tree['position'][2]+tree['height_m'])

    def test_maximum_fleet_has_unique_physical_spaces(self):
        world=generate(Settings.parse({'map_size':150,'scouts':48,'rescuers':40,'people':600}))
        self.assertEqual(len(world['spawns']),88)
        self.assertEqual(len(world['people']),600)
        self.assertEqual(len({x['id'] for x in world['spawns']}),88)
        self.assertEqual(world['preflight']['connected_nodes'],world['preflight']['road_nodes'])

    def test_clustered_casualties_leave_physical_stretcher_clearance(self):
        world=generate(Settings.parse({'preset':'clusters','people':80}))
        positions=[p['position'][:2] for p in world['people']]
        self.assertGreaterEqual(min(math.dist(a,b) for i,a in enumerate(positions) for b in positions[i+1:]),2.2)
        world['people'][1]['position']=world['people'][0]['position'][:]
        with self.assertRaises(ProtocolError):preflight(world)

    def test_preflight_rejects_corrupted_world_geometry(self):
        world=generate(Settings.parse())
        bad=deepcopy(world);bad['buildings'].append(deepcopy(bad['buildings'][0]))
        with self.assertRaises(ProtocolError):preflight(bad)
        bad=deepcopy(world)
        p=bad['spawns'][0]['position']
        bad['buildings'].append({'bounds':{'min':[p[0]-2,p[1]-2,0],'max':[p[0]+2,p[1]+2,5]}})
        with self.assertRaises(ProtocolError):preflight(bad)
        bad=deepcopy(world)
        bad['buildings'].append({'bounds':{'min':[8,-1,0],'max':[12,251,10]}})
        with self.assertRaises(ProtocolError):preflight(bad)


if __name__=='__main__':unittest.main()
