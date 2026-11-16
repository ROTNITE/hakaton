import math
import unittest

from controller.navigation import NavigationMap
from environment.config import Settings
from environment.layout import generate,public_map


class ShoreNavigationTests(unittest.TestCase):
    @staticmethod
    def navigation(world):
        announced=public_map(world)
        announced['navigation']={'kind':'street_surface_graph.v2','ground_clearance_m':.43,
            'base_surface_z_m':.07,'road_surface_z_m':0.}
        return NavigationMap(announced)

    def test_pier_is_connected_at_base_height_and_has_real_open_edges(self):
        for size,seed in ((25,2026),(25,17),(75,2026),(150,90210)):
            with self.subTest(size=size,seed=seed):
                world=generate(Settings.parse({'city_revision':'2.3','map_size':size,'seed':seed}))
                nav=self.navigation(world);station=world['watercraft']['shore_station']
                self.assertAlmostEqual(nav.ground_z(-76,22.5),3.9)
                start=(20.,10.,nav.ground_z(20,10));goal=(-76.,22.5,nav.ground_z(-76,22.5))
                route=nav.road_route(start,goal)
                self.assertGreater(route.distance_m,100)
                self.assertTrue(any(math.dist(p[:2],[-76,10])<.01 for p in route.points))
                self.assertTrue(all(nav._ground_clear(a,b,1.45,1.1) for a,b in zip(route.points,route.points[1:])))
                # A tempting diagonal shortcut leaves both real deck footprints.
                self.assertFalse(nav._ground_clear((-60,10,3.9),goal,1.45,1.1))
                self.assertFalse(nav._ground_clear((-50,20,3.9),(-50,25,3.9),1.45,1.1))
                self.assertGreater(station['deck_z_m'],world['hydrology']['storm_stage_m']+.6)
                self.assertEqual(station['patient_capacity'],1)

    def test_pier_is_optional_and_old_cities_keep_their_navigation(self):
        for settings in ({'city_revision':'2.3','boats':0},{'city_revision':'2.2'}):
            world=generate(Settings.parse(settings));nav=self.navigation(world)
            self.assertFalse(nav.elevated_platforms)
            self.assertEqual(len(nav.street_nodes),len(world['road_graph']['nodes']))


if __name__=='__main__':unittest.main()
