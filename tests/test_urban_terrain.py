from copy import deepcopy
import unittest

from contracts.urban_terrain import FORMAT, Terrain
from controller.navigation import NavigationMap
from environment.config import Settings
from environment.layout import generate, public_map


def blueprint():
    return {'format': FORMAT, 'base': {'min': [0., 0.], 'max': [71., 42.]},
            'base_elevation_m': 3.4, 'grade_width_m': 45., 'pads': [],
            'ramp': {'min': [71., 4.], 'max': [116., 16.]},
            'depressions': [{'min': [-99., 24.], 'max': [-63., 62.], 'elevation_m': -7.2}]}


class UrbanTerrainTests(unittest.TestCase):
    def test_raised_base_has_a_real_access_grade_and_an_open_basin(self):
        terrain = Terrain(blueprint())
        self.assertEqual(terrain.height(20, 20), 3.4)
        self.assertAlmostEqual(terrain.height(50, 50), 3.4*(1-8/45))
        self.assertEqual(terrain.height(150, 150), 0.)
        self.assertEqual(terrain.height(-81, 43), -7.2)
        for x in range(71, 117):
            self.assertAlmostEqual(terrain.height(x, 10), 3.4*(116-x)/45)
        self.assertLess(3.4/45, 1/12)
        self.assertEqual(terrain.height(116, 10), 0.)
        self.assertEqual(Terrain().height(20, 20), 0.)

    def test_pad_feather_and_invalid_profiles(self):
        data = blueprint()
        data['pads'] = [{'min': [120., 20.], 'max': [130., 30.], 'elevation_m': .8}]
        terrain = Terrain(data)
        self.assertEqual(terrain.height(125, 25), .8)
        self.assertAlmostEqual(terrain.height(130.5, 25), .4)
        self.assertEqual(terrain.height(131, 25), 0.)
        for field, value in (('base_elevation_m', True), ('grade_width_m', float('nan'))):
            bad = deepcopy(data); bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): Terrain(bad)
        bad = deepcopy(data); bad['ramp']['min'][0] = 70.
        with self.assertRaises(ValueError): Terrain(bad)
        bad = deepcopy(data); bad['pads'][0]['elevation_m'] = True
        with self.assertRaises(ValueError): Terrain(bad)

    def test_only_new_worlds_lift_fleet_and_announce_initial_geometry(self):
        old = generate(Settings.parse({'city_revision': '2.2'}))
        world = generate(Settings.parse({'city_revision': '2.3'}))
        self.assertNotIn('terrain', old)
        self.assertNotIn('hydrology', old)
        self.assertEqual(world['base_layout_revision'], 4)
        for before, after in zip(old['spawns'], world['spawns']):
            self.assertAlmostEqual(after['position'][2]-before['position'][2], 3.4)
        announced = deepcopy(public_map(world))
        announced['navigation'] = {'kind': 'street_surface_graph.v2', 'ground_clearance_m': .43,
                                   'base_surface_z_m': .07, 'road_surface_z_m': 0.}
        nav = NavigationMap(announced)
        self.assertAlmostEqual(nav.ground_z(20, 10), 3.9)
        self.assertAlmostEqual(nav.ground_z(93.5, 10), 2.13)
        self.assertEqual(announced['terrain'], world['terrain'])
        self.assertTrue(world['preflight']['passed'])
        # This seed puts a junction just 6.7 cm beyond the old base boundary.
        # A vertical retaining edge there used to disconnect the whole graph.
        adjacent = generate(Settings.parse({'city_revision': '2.3', 'seed': 17}))
        self.assertTrue(adjacent['preflight']['passed'])
        self.assertEqual(adjacent['preflight']['road_nodes'], adjacent['preflight']['connected_nodes'])


if __name__ == '__main__':
    unittest.main()
