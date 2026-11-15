import unittest

from contracts.protocol import AGENT_KINDS, ZONE_KINDS, ZONE, ProtocolError, validate
from controller.navigation import Box
from environment.config import Settings
from environment.layout import generate, public_map


class CompetitionLayoutTests(unittest.TestCase):
    def test_legacy_world_omits_annex_and_contest_world_declares_all_categories(self):
        self.assertNotIn('competition',generate(Settings()))
        settings=Settings.parse({'competition':True,'city_revision':'2.2'})
        world=generate(settings);annex=world['competition']
        kinds={row['kind'] for row in [*world['spawns'],*annex['units']]}
        self.assertEqual(kinds,set(AGENT_KINDS))
        self.assertEqual(len({row['id'] for row in [*world['spawns'],*annex['units']]}),len(world['spawns'])+6)
        bounds=Box.parse(world['bounds'])
        for unit in annex['units']:
            self.assertTrue(all(lo<=v<=hi for lo,v,hi in zip(bounds.minimum,unit['position'],bounds.maximum)))
            if 'limits' in unit:
                limits=Box.parse(unit['limits'])
                self.assertTrue(all(lo<=v<=hi for lo,v,hi in zip(limits.minimum,unit['position'],limits.maximum)))
        published=public_map(world)
        self.assertNotIn('people',published)
        self.assertNotIn('orbital_sensor',published)
        for area in published['declared_zones']:validate(area,ZONE)
        self.assertEqual({area['type'] for area in published['declared_zones']},set(ZONE_KINDS)-{'hazard','restricted'})

    def test_competition_setting_is_boolean(self):
        for invalid in (0,'true',None):
            with self.subTest(invalid=invalid),self.assertRaises(ProtocolError):
                Settings.parse({'competition':invalid})
