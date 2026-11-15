import math
import unittest

from controller.navigation import NavigationMap, RouteFailure


def box(a, b):
    return {'kind': 'box', 'min': a, 'max': b}


class NavigationTests(unittest.TestCase):
    def world(self, obstacles=(), surfaces=()):
        return NavigationMap({'bounds': box([0, 0, 0], [100, 100, 60]),
                              'buildings': [{'bounds': b} for b in obstacles], 'surfaces': list(surfaces)})

    def test_exact_start_and_continuous_clearance_around_wall(self):
        world = self.world([box([20, 1, 0], [23, 35, 15])])
        start, goal = (11.37, 11.19, .73), (35.41, 11.19, .73)
        route = world.route(start, goal)
        self.assertEqual(route.points[0], start)
        self.assertEqual(route.points[-1], goal)
        self.assertGreater(route.distance_m, math.dist(start, goal))
        for a, b in zip(route.points, route.points[1:]):
            self.assertTrue(world.clear(a, b, 1.45, 1.1))

    def test_no_corner_cut_or_thin_wall_sampling_gap(self):
        world = self.world([box([20, 0, 0], [20.00001, 100, 30])])
        self.assertFalse(world.clear((10, 50, 1), (30, 50, 1), 1, 1))
        with self.assertRaisesRegex(RouteFailure, 'no_known_path|search_budget'):
            world.route((10, 50, 1), (30, 50, 1), max_expanded=2000)

    def test_air_uses_real_altitude_and_blocked_cruise_falls_back(self):
        world = self.world([box([20, 0, 0], [23, 35, 15])])
        route = world.route((10.3, 10.2, .3), (35.7, 10.2, .3), aerial=True,
                            radius_m=1.65, half_height_m=.4)
        self.assertGreater(max(p[2] for p in route.points), 15)
        for a, b in zip(route.points, route.points[1:]):
            self.assertTrue(world.clear(a, b, 1.65, .4))
        detour = world.route((10.3, 10.2, 5), (35.7, 10.2, 5), aerial=True,
                             radius_m=1, half_height_m=.4, cruise_altitude_m=10)
        self.assertGreater(detour.expanded, 0)
        self.assertTrue(any(p[1] > 35 for p in detour.points))

    def test_expensive_mud_can_be_avoided_without_smoothing_through_it(self):
        world = self.world(surfaces=[{'bounds': box([20, 8, -.1], [40, 12, .1]), 'cost': 15}])
        route = world.route((10, 10, .73), (50, 10, .73))
        self.assertLess(route.weighted_distance_m, 60)
        self.assertLess(route.weighted_distance_m, world.cost((10, 10, .73), (50, 10, .73)))

    def test_rejects_unknown_layer_and_blocked_endpoints(self):
        world = self.world([box([20, 20, 0], [30, 30, 15])])
        with self.assertRaisesRegex(RouteFailure, 'endpoint_blocked'):
            world.route((25, 25, .73), (50, 50, .73))
        with self.assertRaisesRegex(RouteFailure, 'surface_graph'):
            world.route((10, 10, .73), (50, 50, 4.73))

    def test_budget_and_invalid_spatial_values_are_explicit(self):
        world = self.world([box([20, 0, 0], [25, 70, 20])])
        with self.assertRaisesRegex(RouteFailure, 'budget'):
            world.route((10, 10, .73), (50, 10, .73), max_expanded=1)
        with self.assertRaises(ValueError):
            world.route((True, 1, 1), (2, 2, 2))

    def test_road_graph_avoids_shortcut_across_a_raised_sidewalk(self):
        data={'bounds':box([0,0,0],[100,100,60]),'base':box([0,0,-.2],[35,35,.2]),
              'road_axes_m':[10,50,90],'road_width_m':8.5,
              'navigation':{'kind':'road_surface_graph.v1','road_surface_z_m':.04,
                            'base_surface_z_m':.11,'ground_clearance_m':.43,'max_step_m':.1}}
        nav=NavigationMap(data)
        start,goal=(20,22,.558),(78,10,.47)
        route=nav.road_route(start,goal)
        self.assertEqual(route.points[0],start)
        self.assertEqual(route.points[-1],goal)
        self.assertGreater(len(route.points),2)
        for a,b in zip(route.points,route.points[1:]):
            if min(a[0],b[0])<36.45<max(a[0],b[0]):
                t=(36.45-a[0])/(b[0]-a[0])
                self.assertLessEqual(abs(a[1]+t*(b[1]-a[1])-10),2.8)
        self.assertAlmostEqual(nav.ground_z(20,20),.54)
        self.assertAlmostEqual(nav.ground_z(78,10),.47)


if __name__ == '__main__':
    unittest.main()
