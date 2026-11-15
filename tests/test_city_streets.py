from copy import deepcopy
import math
import unittest
from unittest.mock import patch

from contracts.protocol import ProtocolError
from controller.navigation import NavigationMap
from environment.config import MAP_SIZES,Settings
from environment.events import validate_tape
from environment.layout import generate,preflight,public_map


def city(**settings):
    return generate(Settings.parse({'city_revision':'2.0',**settings}),include_events=True)


class StreetGraphTests(unittest.TestCase):
    def test_series_urban_5204_keeps_access_lanes_outside_base_fixtures(self):
        world = generate(Settings.parse({'city_revision': '2.2', 'seed': 5204, 'preset': 'urban',
                                         'scouts': 3, 'rescuers': 3, 'people': 12}))
        self.assertTrue(world['preflight']['passed'])
        self.assertEqual(world['preflight']['connected_nodes'], world['preflight']['road_nodes'])
        self.assertEqual(len(world['road_graph']['entrances']), 4)
        self.assertTrue(any(edge['street_class'] == 'access' for edge in world['road_graph']['edges']))

    def test_base_return_from_the_north_avoids_the_announced_medical_container(self):
        world=generate(Settings.parse({'seed':2027,'city_revision':'2.2','map_size':35,
                                       'scouts':3,'rescuers':4,'people':3}))
        announced=public_map(world)
        announced['navigation']={'kind':'street_surface_graph.v2','road_surface_z_m':0,
                                 'base_surface_z_m':.07,'ground_clearance_m':.43}
        nav=NavigationMap(announced)
        goal=(20.,18.3,.5)
        for start in ((19.44,27.64,.52),(46.53,32.92,.52)):
            route=nav.road_route(start,goal)
            self.assertEqual(route.points[0],start)
            self.assertEqual(route.points[-1],goal)
            self.assertTrue(all(nav.clear(a,b,1.45,1.1) for a,b in zip(route.points,route.points[1:])))
        self.assertFalse(nav.clear((19.44,27.64,.52),goal,1.45,1.1))

    def test_street_graph_repeats_and_has_distinct_junctions(self):
        a=city(seed=2026);b=city(seed=2026);changed=city(seed=1241)
        graph=a['road_graph'];self.assertEqual(graph,b['road_graph'])
        self.assertNotEqual(graph,changed['road_graph'])
        self.assertEqual(a['event_model'],b['event_model'])
        self.assertEqual({e['street_class'] for e in graph['edges']},{'avenue','street','access'})
        nodes={n['id']:n['position'] for n in graph['nodes']}
        self.assertTrue(any(all(abs(nodes[e['to']][i]-nodes[e['from']][i])>5 for i in (0,1)) for e in graph['edges']))
        self.assertEqual({tuple(x['outward']) for x in graph['entrances']},{(-1,0),(1,0),(0,-1),(0,1)})
        self.assertGreater(len(a['background']),100)
        self.assertEqual(a['preflight']['road_nodes'],a['preflight']['connected_nodes'])

    def test_outskirts_taper_without_changing_mission_inputs(self):
        for size, seed in ((25, 2026), (25, 2027), (35, 2027), (150, 2026)):
            with self.subTest(size=size, seed=seed):
                options = {'city_revision': '2.2', 'map_size': size, 'seed': seed}
                world = city(**options)
                self.assertEqual(world['background'], city(**options)['background'])
                with patch('environment.neighbourhood._outskirts', return_value=[]):
                    empty = city(**options)
                self.assertEqual({**world, 'background': []}, empty)
                self.assertEqual(public_map(world), public_map(empty))
                self.assertTrue(world['preflight']['passed'])

                nodes = {node['id']: node['position'] for node in world['road_graph']['nodes']}
                extent = world['size_m']
                houses = [[], [], []]
                corners = set()
                for lot in world['background']:
                    x, y, z = lot['position']
                    depth = max(-x, -y, x-extent, y-extent)
                    self.assertGreater(depth, 12)
                    self.assertEqual(z, 0)
                    if not 0 <= x <= extent and not 0 <= y <= extent:
                        self.assertEqual(lot['kind'], 'green')
                        corners.add((x < 0, y < 0))
                    for entrance in world['road_graph']['entrances']:
                        gx, gy, _ = nodes[entrance['node_id']]
                        dx, dy = entrance['outward']
                        if (x-gx)*dx + (y-gy)*dy > 0:
                            self.assertGreaterEqual(abs((x-gx)*dy - (y-gy)*dx), 15)
                    if lot['kind'] == 'housing':
                        houses[0 if depth < 32 else 1 if depth < 62 else 2].append(lot['floors'])
                self.assertEqual(len(corners), 4)
                self.assertGreater(len(houses[0]), len(houses[1]))
                self.assertGreater(len(houses[1]), len(houses[2]))
                self.assertEqual([max(band) for band in houses], [4, 3, 2])

    def test_all_sizes_keep_scale_and_largest_fleet(self):
        for size in MAP_SIZES:
            with self.subTest(size=size):
                extra={'scouts':48,'rescuers':40,'people':600} if size==150 else {}
                world=city(map_size=size,**extra)
                self.assertEqual(world['size_m'],size*10)
                self.assertTrue(world['preflight']['passed'])
                self.assertTrue(all(b['footprint']['half']==[4.75,4.75] for b in world['buildings']))
                self.assertEqual(validate_tape(world['event_model'],world),world['event_model'])
                self.assertNotIn('people',public_map(world));self.assertNotIn('event_model',public_map(world))
        self.assertEqual(len(world['spawns']),88);self.assertEqual(len(world['people']),600)

    def test_preflight_detects_physical_obstruction_in_street(self):
        world=city();bad=deepcopy(world)
        nodes={n['id']:n['position'] for n in bad['road_graph']['nodes']}
        edge=max(bad['road_graph']['edges'],key=lambda e:math.dist(nodes[e['from']],nodes[e['to']]))
        x,y,_=((u+v)/2 for u,v in zip(nodes[edge['from']],nodes[edge['to']]))
        bad['facilities'].append({'bounds':{'kind':'box','min':[x-2,y-2,0],'max':[x+2,y+2,2]}})
        with self.assertRaisesRegex(ProtocolError,'preflight failed'):preflight(bad)

    def test_route_from_actual_pose_to_rotated_street_shoulders(self):
        world=city(layout='rescue_quarter',scouts=1,rescuers=1,people=3)
        announced=public_map(world)
        announced['navigation']={'kind':'street_surface_graph.v2','road_surface_z_m':0,'base_surface_z_m':.07,
                                  'ground_clearance_m':.43}
        nav=NavigationMap(announced)
        start=(63.17,10.29,.513)
        for p in world['people']:
            goal=tuple(p['position'][:2])+(.43,)
            route=nav.road_route(start,goal)
            self.assertEqual(route.points[0],start);self.assertEqual(route.points[-1],goal)
            self.assertTrue(all(nav.clear(a,b,1.45,1.1) for a,b in zip(route.points,route.points[1:])))
            self.assertGreaterEqual(route.distance_m,math.dist(start,goal)-1.e-8)

    def test_decorated_layout_keeps_street_graph_and_separate_physical_models(self):
        base=city(layout='rescue_quarter')
        decorated=city(layout='rescue_quarter',city_revision='2.1')
        self.assertEqual(decorated['road_graph'],base['road_graph'])
        self.assertEqual(decorated['lot_covers'],city(layout='rescue_quarter',city_revision='2.1')['lot_covers'])
        self.assertEqual({cover['kind'] for cover in decorated['lot_covers']},{'housing','park','service'})
        self.assertTrue(all(len(cover['vertices'])>=3 for cover in decorated['lot_covers']))
        self.assertEqual(len({row['asset_id'] for row in decorated['features'] if row['kind']=='vegetation'}),7)
        public=public_map(decorated)
        self.assertEqual({row['id'] for row in public['fixed_obstacles']},
            {'van-service-lane','base-lamp-south','base-lamp-north','medical-container',
             'charge-generator','base-compute-cabinet','base-sensor-mast'})
        self.assertNotIn('lot_covers',public)
        # Native observations augment the exported static map with support heights.
        public['navigation']={'kind':'street_surface_graph.v2','road_surface_z_m':0,
                              'base_surface_z_m':.07,'ground_clearance_m':.43}
        nav=NavigationMap(public)
        for feature in decorated['features']:
            for collider in feature['obstacles']:
                if 'footprint' in collider:
                    center=collider['footprint']['center']
                else:
                    center=[(a+b)/2 for a,b in zip(collider['min'],collider['max'])]
                p=(*center[:2],.3)
                self.assertFalse(nav.clear(p,p,.18,.1),feature['id'])

    def test_rotated_yard_shelters_keep_maximum_fleet_road_clearance(self):
        for revision in ('2.1','2.2'):
            with self.subTest(revision=revision):
                world=city(city_revision=revision,map_size=150,scouts=48,rescuers=40,people=600,seed=2026)
                self.assertTrue(world['preflight']['passed'])
                self.assertEqual(world['preflight']['connected_nodes'],world['preflight']['road_nodes'])
                self.assertEqual((len(world['spawns']),len(world['people'])),(88,600))


if __name__=='__main__':unittest.main()
