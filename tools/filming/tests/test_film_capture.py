import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import film_capture


def valid_plan():
    return {'format':'metarescue.film.v1','fps':30,'warmup_frames':120,'shots':[
        {'id':'01-city','frames':120,'keys':[
            {'u':0,'eye_cm':[0,0,200],'look_cm':[100,100,0],'fov':48},
            {'u':1,'eye_cm':[200,0,200],'look_cm':[100,100,0],'fov':48}]}]}


class FilmPlanTests(unittest.TestCase):
    def read(self,plan):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'plan.json';path.write_text(json.dumps(plan),encoding='utf-8')
            return film_capture.read_plan(path)

    def test_accepts_finite_rail_and_exact_agent_follow(self):
        plan=valid_plan();plan['shots'][0].update(follow='aerial_1',follow_space='heading',collision_test=True,wait_until_s=15.2,wait_for_delivered=1)
        self.assertEqual(self.read(plan),plan)

    def test_delivery_gate_and_core_time_must_be_valid(self):
        for key,value in [('wait_until_s',float('inf')),('wait_until_s',True),('wait_for_delivered',True),('wait_for_delivered',-1),('wait_for_delivered',601)]:
            with self.subTest(key=key,value=value):
                plan=valid_plan();plan['shots'][0][key]=value
                with self.assertRaises(ValueError):self.read(plan)

    def test_rejects_path_escape_and_windows_case_collision(self):
        for value in ('../city','city/../../','a:b','city\\test',''):
            with self.subTest(value=value):
                plan=valid_plan();plan['shots'][0]['id']=value
                with self.assertRaises(ValueError):self.read(plan)
        plan=valid_plan();plan['shots'].append(copy.deepcopy(plan['shots'][0]));plan['shots'][1]['id']='01-CITY'
        with self.assertRaises(ValueError):self.read(plan)

    def test_rejects_nonfinite_vectors_and_boolean_numbers(self):
        for value in (float('nan'),float('inf'),True,None):
            with self.subTest(value=value):
                plan=valid_plan();plan['shots'][0]['keys'][0]['eye_cm'][0]=value
                with self.assertRaises(ValueError):self.read(plan)

    def test_requires_monotone_keys_covering_whole_shot(self):
        for value in (0,.5,1.1):
            plan=valid_plan();plan['shots'][0]['keys'][-1]['u']=value
            with self.assertRaises(ValueError):self.read(plan)

    def test_requires_fixed_fps_and_bounded_runtime(self):
        plan=valid_plan();plan['fps']=60
        with self.assertRaises(ValueError):self.read(plan)
        plan=valid_plan();plan['shots'][0]['frames']=18001
        with self.assertRaises(ValueError):self.read(plan)

    def test_rejects_degenerate_camera_and_invalid_follow_space(self):
        plan=valid_plan();plan['shots'][0]['keys'][0]['look_cm']=[0,0,200]
        with self.assertRaises(ValueError):self.read(plan)
        plan=valid_plan();plan['shots'][0]['follow_space']='telemetry'
        with self.assertRaises(ValueError):self.read(plan)

    def test_frame_verifier_catches_missing_frame_and_time_gap(self):
        plan=valid_plan();plan['shots'][0]['frames']=2
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);shot=root/'01-city';shot.mkdir()
            (root/'capture.json').write_text(json.dumps({'complete':True,'frames':2,'fps':30}))
            rows=[{'shot':'01-city','frame':i,'world_time_s':1+i/30} for i in range(2)]
            (root/'frames.jsonl').write_text('\n'.join(map(json.dumps,rows)))
            (shot/'frame-000000.png').write_bytes(b'\x89PNG\r\n\x1a\n')
            with self.assertRaisesRegex(ValueError,'Missing'):film_capture.verify_capture(root,plan)
            (shot/'frame-000001.png').write_bytes(b'\x89PNG\r\n\x1a\n')
            with self.assertRaisesRegex(ValueError,'Invalid PNG'):film_capture.verify_capture(root,plan)
            for i in range(2):Image.new('RGB',(8,8),(30,60,90)).save(shot/f'frame-{i:06d}.png')
            self.assertTrue(film_capture.verify_capture(root,plan)['passed'])
            with self.assertRaisesRegex(ValueError,'dimensions'):film_capture.verify_capture(root,plan,(16,8))
            rows[1]['world_time_s']=2
            (root/'frames.jsonl').write_text('\n'.join(map(json.dumps,rows)))
            with self.assertRaisesRegex(ValueError,'Nonuniform'):film_capture.verify_capture(root,plan)

    def test_core_closing_hold_keeps_mission_clock_still_and_requires_delivery(self):
        plan=valid_plan();plan['shots'][0].update(frames=2,wait_for_delivered=1)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);shot=root/'01-city';shot.mkdir()
            for i in range(2):Image.new('RGB',(8,8),(30,60,90)).save(shot/f'frame-{i:06d}.png')
            (root/'capture.json').write_text(json.dumps({'complete':True,'frames':2,'fps':30}))
            rows=[{'shot':'01-city','frame':i,'world_time_s':300,'core_time_s':281,'core_controlled':True,
                   'held_tail':True,'delivered':1,'capture_time_s':i/30} for i in range(2)]
            (root/'frames.jsonl').write_text('\n'.join(map(json.dumps,rows)))
            result=film_capture.verify_capture(root,plan)
            self.assertEqual(result['shots'][0]['held_tail_frames'],2)
            self.assertEqual(result['shots'][0]['core_start_s'],result['shots'][0]['core_end_s'])
            rows[-1]['delivered']=0
            (root/'frames.jsonl').write_text('\n'.join(map(json.dumps,rows)))
            with self.assertRaisesRegex(ValueError,'actual delivery gate'):film_capture.verify_capture(root,plan)


if __name__=='__main__':unittest.main()
