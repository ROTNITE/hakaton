from copy import deepcopy
import json
import math
import unittest

from contracts.protocol import ProtocolError
from environment.config import EVENT_DEFAULTS, Settings
from environment.events import DETAILED_VERSION, generate_tape, validate_tape
from environment.layout import generate, public_map


class DisasterProfileTests(unittest.TestCase):
    def world(self, profile='v052', probability=100):
        return generate(Settings.parse({'city_revision': '2.3', 'event_profile': profile,
            'probabilities': dict.fromkeys(EVENT_DEFAULTS[profile], probability)}))

    def test_explicit_revision_keeps_the_old_world_and_tape_semantics(self):
        old = generate(Settings.parse({'city_revision': '2.2'}), include_events=True)
        new = generate(Settings.parse({'city_revision': '2.3'}), include_events=True)
        self.assertEqual(old['format'], 'rescue-city-2.2')
        self.assertEqual(old['event_model']['format'], 'metarescue.events-3d.1.0')
        self.assertEqual(new['format'], 'rescue-city-2.3')
        self.assertEqual(new['event_model']['format'], DETAILED_VERSION)
        self.assertNotIn('wind_m_s', old['event_model'])
        old_primary = [(r['id'], r['kind'], r['time']) for r in old['event_model']['events'] if not r['spread']]
        new_primary = [(r['id'], r['kind'], r['time']) for r in new['event_model']['events'] if not r['spread']]
        self.assertEqual(old_primary, new_primary)

    def test_percentages_are_event_probabilities_and_keep_both_windows(self):
        for profile, window in (('v052', 80), ('v3', 30)):
            world = self.world(profile)
            previous = set()
            for percentage in (0, 25, 50, 75, 100):
                world['settings']['probabilities'] = dict.fromkeys(EVENT_DEFAULTS[profile], percentage)
                tape = generate_tape(world)
                current = {row['id'] for row in tape['events'] if not row['spread']}
                self.assertLessEqual(previous, current)
                self.assertEqual(tape['probability_window_s'], window)
                previous = current

    def test_wind_and_roof_source_are_repeatable_and_stay_private(self):
        world = self.world()
        tape = generate_tape(world)
        other = deepcopy(world)
        other['buildings'].reverse()
        self.assertEqual(tape, generate_tape(other))
        self.assertTrue(1.9 < math.hypot(*tape['wind_m_s'][:2]) < 4.1)
        houses = {row['id']: row for row in world['buildings']}
        fires = [row for row in tape['events'] if row['kind'] == 'fire' and not row['rejection']]
        self.assertTrue(fires)
        for row in fires:
            self.assertEqual(row['smoke_emission_height_m'], houses[row['source_object_id']]['bounds']['max'][2])
            self.assertAlmostEqual(row['expires_at'] - row['time'], 180)
            self.assertAlmostEqual(row['visibility_expires_at'] - row['expires_at'], 45)
        self.assertEqual(public_map({**world, 'event_model': tape}), public_map(world))
        self.assertNotIn('wind_m_s', json.dumps(public_map({**world, 'event_model': tape})))

    def test_invalid_detailed_parameters_and_cross_version_tapes_fail_closed(self):
        world = self.world()
        tape = generate_tape(world)
        for mutation in ('nan_wind', 'vertical_wind', 'overspeed', 'boolean_height', 'infinite_height', 'old_format'):
            bad = deepcopy(tape)
            if mutation == 'nan_wind': bad['wind_m_s'][0] = float('nan')
            elif mutation == 'vertical_wind': bad['wind_m_s'][2] = 1
            elif mutation == 'overspeed': bad['wind_m_s'][0] = 16
            elif mutation == 'old_format': bad['format'] = 'metarescue.events-3d.1.0'
            else:
                row = next(row for row in bad['events'] if not row['rejection'])
                row['smoke_emission_height_m'] = True if mutation == 'boolean_height' else float('inf')
            with self.subTest(mutation=mutation), self.assertRaises(ProtocolError):
                validate_tape(bad, world)
        old = generate(Settings.parse({'city_revision': '2.2'}))
        with self.assertRaises(ProtocolError): validate_tape(tape, old)

    def test_floods_drive_the_declared_boundary_instead_of_spawning_water_in_dry_streets(self):
        world=self.world();tape=generate_tape(world)
        floods=[row for row in tape['events'] if row['kind']=='flood']
        self.assertTrue(floods)
        for row in floods:
            self.assertEqual(row['source'],[-91.5,43.,.05])
            self.assertEqual(row['cells'],[])
            self.assertEqual(row['hydraulic_forcing'],'connected_flow' if row['spread'] else 'stage_rise')
        for mutation in ('source','cells','boundary','forcing'):
            bad=deepcopy(tape);row=next(r for r in bad['events'] if r['kind']=='flood')
            if mutation=='source':row['source'][0]=120.
            elif mutation=='cells':row['cells']=[[40,40]]
            elif mutation=='boundary':row['hydraulic_boundary_id']='unknown-pipe'
            else:row['hydraulic_forcing']='instant_patch'
            with self.subTest(mutation=mutation),self.assertRaises(ProtocolError):validate_tape(bad,world)


if __name__ == '__main__':
    unittest.main()
