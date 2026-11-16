import math
import unittest

from contracts.protocol import ProtocolError
from environment.config import Settings
from environment.layout import generate,public_map


class WatercraftConfigurationTests(unittest.TestCase):
    def test_watercraft_are_an_explicit_new_profile_without_changing_legacy_fleets(self):
        self.assertEqual(Settings.parse({'city_revision':'2.2'}).boats,0)
        self.assertEqual(Settings.parse({'city_revision':'2.3'}).boats,2)
        for count in range(5):
            world=generate(Settings.parse({'city_revision':'2.3','boats':count}))
            self.assertEqual(len(world['spawns']),7)
            self.assertEqual(len(world.get('watercraft',{}).get('spawns',[])),count)
            if count:
                self.assertEqual(public_map(world)['watercraft'],world['watercraft'])
                seen=set()
                for boat in world['watercraft']['spawns']:
                    self.assertNotIn(boat['id'],seen);seen.add(boat['id'])
                    x,y,z=boat['position']
                    self.assertTrue(-100<x<-63 and 62<y<73)
                    self.assertGreater(z,.5)
                    self.assertLess(abs(boat['pitch']),10)
                for a,b in zip(world['watercraft']['spawns'],world['watercraft']['spawns'][1:]):
                    self.assertGreater(math.dist(a['position'][:2],b['position'][:2]),6)
        for value in (-1,5,1.5,True):
            with self.subTest(value=value),self.assertRaises(ProtocolError):Settings.parse({'boats':value})


if __name__=='__main__':unittest.main()
