from copy import deepcopy
import json
import unittest

from contracts.protocol import ProtocolError
from environment.config import Settings,EVENT_DEFAULTS
from environment.events import generate_tape,validate_tape
from environment.layout import generate,public_map


class EventTapeTests(unittest.TestCase):
    def world(self,profile='v052',probability=100):
        return generate(Settings.parse({'event_profile':profile,'probabilities':dict.fromkeys(EVENT_DEFAULTS[profile],probability)}))

    def test_zero_and_all_profile_windows_are_distinct(self):
        self.assertEqual(generate_tape(self.world(probability=0))['events'],[])
        for profile,count,window in (('v052',5,80),('v3',15,30)):
            tape=generate_tape(self.world(profile));self.assertEqual(tape['probability_window_s'],window)
            primary=[r for r in tape['events'] if not r['spread']]
            self.assertEqual(len(primary),count*len(EVENT_DEFAULTS[profile]))
            if profile=='v3':self.assertTrue(all(r['time']%30==0 for r in primary))
            else:self.assertTrue(any(r['time']%80!=0 for r in primary))

    def test_v3_keeps_exact_windows_at_the_horizon(self):
        world = self.world('v3')
        tape = generate_tape(world)
        primary = {row['id']:row['time'] for row in tape['events'] if not row['spread']}
        spread = [row for row in tape['events'] if row['spread']]
        self.assertTrue(spread)
        self.assertTrue(all(row['time']-primary[row['parent_id']] in (30,60) for row in spread))

        world['settings']['horizon'] = 30.005
        tape = generate_tape(world)
        self.assertEqual(len(tape['events']),len(EVENT_DEFAULTS['v3']))
        self.assertEqual({row['time'] for row in tape['events']},{30.0})

    def test_repeat_permutation_seed_and_public_privacy(self):
        world=self.world();tape=generate_tape(world);other=deepcopy(world)
        other['buildings'].reverse();other['road_axes_m'].reverse()
        self.assertEqual(tape,generate_tape(other));self.assertEqual(tape,generate_tape(world))
        other['settings']['seed']+=1;self.assertNotEqual(tape,generate_tape(other))
        private={**world,'event_model':tape};self.assertEqual(public_map(private),public_map(world))
        self.assertNotIn('event_model',json.dumps(public_map(private)))
        integrated=generate(Settings.parse(world['settings']),include_events=True)
        self.assertEqual(integrated['event_model'],tape)
        self.assertEqual(public_map(integrated),public_map(world))

    def test_late_people_safe_sources_spread_and_expiry(self):
        world=self.world();tape=generate_tape(world);self.assertTrue(tape['late_people'])
        events={r['id']:r for r in tape['events']}
        for row in tape['events']:
            if row['spread']:
                self.assertLess(events[row['parent_id']]['time'],row['time'])
            if row['kind']=='smoke':self.assertAlmostEqual(row['expires_at']-row['time'],72)
        self.assertEqual(validate_tape(tape,world),tape)
        for mutation in ('parent','cell','target','expiry'):
            bad=deepcopy(tape)
            if mutation=='parent':bad['events'][0]['parent_id']='future'
            elif mutation=='cell':next(r for r in bad['events'] if r['cells'])['cells']=[[0,0]]
            elif mutation=='target':bad['late_people'][0]['position']=[20,22,0]
            else:bad['events'][0]['expires_at']=-1
            with self.subTest(mutation=mutation),self.assertRaises(ProtocolError):validate_tape(bad,world)

    def test_short_horizon_never_creates_negative_or_past_end_events(self):
        world=self.world();world['settings']['horizon']=1
        tape=generate_tape(world);self.assertTrue(all(0<r['time']<1 for r in tape['events']))

    def test_malformed_rows_and_orphan_targets_fail_as_protocol_errors(self):
        world=self.world();tape=generate_tape(world)
        for mutation in ('row','cell','time','person','orphan','mixed_profile','target_reference'):
            bad=deepcopy(tape)
            if mutation=='row':bad['events'][0]=[]
            elif mutation=='cell':next(r for r in bad['events'] if r['cells'])['cells']=[{}]
            elif mutation=='time':bad['events'][0]['time']=-.5
            elif mutation=='person':bad['late_people'][0]['id']=True
            elif mutation=='orphan':
                target=bad['late_people'][0]['id'];bad['events']=[r for r in bad['events'] if r.get('target_id')!=target]
            elif mutation=='mixed_profile':bad['events'][0]['kind']='low_visibility'
            else:next(r for r in bad['events'] if r['kind']=='new_target')['target_id']={}
            with self.subTest(mutation=mutation),self.assertRaises(ProtocolError):validate_tape(bad,world)


if __name__=='__main__':unittest.main()
