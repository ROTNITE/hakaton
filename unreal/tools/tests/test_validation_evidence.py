"""Protect acceptance boundaries against false passes; no engine results fabricated."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_quarter_v3_run import check_tape,check_trajectories,check_effects,check_clock_profile,expected_visibility
import run_quarter_validation
_launch_spec=importlib.util.spec_from_file_location('quarter_launch',Path(__file__).resolve().parents[2]/'launch.py')
quarter_launch=importlib.util.module_from_spec(_launch_spec);_launch_spec.loader.exec_module(quarter_launch)


class EvidenceChecks(unittest.TestCase):
    def test_engine_float_clock_rounding_is_accepted_but_wrong_clock_is_rejected(self):
        request={'time_step_mode':'fixed_functional','requested_fixed_fps':30,'environment':'random','wall_elapsed_s':35.52}
        observed={'time_step_mode':'fixed_functional','requested_fixed_fps':29.999998435,
                  'model_delta_s_min':.0333333350718,'model_delta_s_max':.0333333350718,'wall_elapsed_s':35.52}
        self.assertTrue(check_clock_profile(request,observed))
        with self.assertRaisesRegex(AssertionError,'fixed rate metadata mismatch'):
            check_clock_profile(request,observed|{'requested_fixed_fps':31})
        with self.assertRaisesRegex(AssertionError,'actual model tick differs'):
            check_clock_profile(request,observed|{'model_delta_s_max':1/31})
        with self.assertRaisesRegex(AssertionError,'clock profile mismatch'):
            check_clock_profile(request,observed|{'time_step_mode':'real_time'})

    def test_fixed_functional_profile_keeps_normal_clock_unmodified(self):
        kwargs={'quarter':True,'smoke':True,'environment':'random'}
        self.assertEqual(quarter_launch.functional_time_args(None,**kwargs),[])
        self.assertEqual(quarter_launch.functional_time_args(30,**kwargs),['-UseFixedTimeStep','-FPS=30'])
        self.assertEqual(quarter_launch.functional_time_args(30,**(kwargs|{'visual_probe':'events'})),['-UseFixedTimeStep','-FPS=30'])
        for override in [{'environment':'static'},{'environment':'showcase'},{'quarter':False},{'smoke':False},
                         {'traffic_probe':'crossing'},{'capture_frames':True},{'visual_probe':'windows'}]:
            with self.assertRaises(ValueError):quarter_launch.functional_time_args(30,**(kwargs|override))

    def test_fixed_random_workflow_is_explicit_and_not_performance_named(self):
        with patch.object(sys,'argv',['run_quarter_validation.py','random','--prefix','unit','--case','20261109','--fixed-step-fps','30']),patch.object(run_quarter_validation,'run') as run:
            run_quarter_validation.main()
        name,options,seconds=run.call_args.args
        self.assertEqual(name,'unit-fixed30-random-20261109')
        self.assertEqual(options[options.index('--fixed-step-fps')+1],'30')
        self.assertEqual(seconds,480)
        for suite in ['traffic','static','showcase','windows']:
            with patch.object(sys,'argv',['run_quarter_validation.py',suite,'--fixed-step-fps','30']),patch.object(run_quarter_validation,'run') as run:
                with self.assertRaises(SystemExit):run_quarter_validation.main()
                run.assert_not_called()

    def test_late_person_requires_real_geometry_not_only_an_unhidden_actor(self):
        truth={'event_tape':[{'id':'E1','type':'new_target','time_s':30,'cells':[],'rejected':''}]}
        applied=[{'event_id':'E1','event_type':'new_target','time_s':30}]
        sample={'event_id':'E1','age_s':2,'active':True,'visible_components':0,'visual_components':[],
                'target_visual_exists':True,'target_mesh_components':0,'target_visual_hidden':False,'target_observed_at':-1}
        frames=[{'time_s':32,'event_effect_samples':[sample]}]
        with self.assertRaisesRegex(AssertionError,'no real mesh'):check_effects(truth,frames,applied)
        sample['target_mesh_components']=1
        self.assertEqual(check_effects(truth,frames,applied)['sampled_events'],1)

    def test_window_inspection_is_explicitly_static_without_dispatcher(self):
        # Inspect the requested workflow without launching or fabricating UE.
        with patch.object(sys,'argv',['run_quarter_validation.py','windows','--prefix','unit-window']),patch.object(run_quarter_validation,'run') as run:
            run_quarter_validation.main()
        name,options,seconds=run.call_args.args
        self.assertEqual(name,'unit-window-windows')
        self.assertEqual(seconds,30)
        self.assertIn('--external-control',options)
        self.assertEqual(options[options.index('--environment')+1],'static')
        self.assertEqual(options[options.index('--visual-probe')+1],'windows')

    def test_collision_is_rejected_before_unrelated_missing_fields(self):
        # A contact must fail before a controlled fixture's omitted sensor/
        # energy fields can hide the actual safety regression.
        frames=[{'time_s':2,'agents':[{'key':'ground_0','vehicle_contacts':1}]}]
        with self.assertRaisesRegex(AssertionError,'vehicle collision'):check_trajectories(frames)

    def test_zero_probability_rejects_secondary_events(self):
        truth={'event_tape':[{'id':'E1','type':'fire','time_s':30,'parent_id':'','site':'box','cells':[],'rejected':''}],
               'window_s':30,'mode':'random','horizon_s':480,'dynamic_cell_size_m':5,
               'probabilities_pct':{k:0 for k in ['collapse','fire','flood','mud','road_damage','smoke','low_visibility','new_target']}}
        actual=[{'type':'environment_event','event_id':'E1','event_type':'fire','time_s':30,'parent_id':'','site_id':'box','cells':[],'reason':''}]
        with self.assertRaisesRegex(AssertionError,'zero/static'):check_tape(truth,actual,40)

    def test_missing_or_extra_actual_events_fail(self):
        truth={'event_tape':[],'window_s':30,'mode':'static','horizon_s':480,'dynamic_cell_size_m':5,
               'probabilities_pct':{k:0 for k in ['collapse','fire','flood','mud','road_damage','smoke','low_visibility','new_target']}}
        with self.assertRaisesRegex(AssertionError,'differ from due tape'):
            check_tape(truth,[{'type':'environment_event','event_id':'unexpected'}],50)

    def test_visibility_expiry_and_overlap_boundaries(self):
        smoke={'type':'smoke','time_s':30,'cells':[[2,3]],'rejected':''}
        fog={'type':'low_visibility','time_s':30,'cells':[[2,3]],'rejected':''}
        self.assertAlmostEqual(expected_visibility((2,3),119.99,[smoke,fog]),.52*.62)
        self.assertEqual(expected_visibility((2,3),120,[smoke,fog]),.62)
        self.assertEqual(expected_visibility((2,3),130,[smoke,fog]),1)
        self.assertEqual(expected_visibility((5,5),60,[smoke,fog]),1)

    def test_fire_smoke_uses_seventy_seconds(self):
        fire={'type':'fire','time_s':30,'cells':[[2,3]],'rejected':''}
        self.assertEqual(expected_visibility((2,4),99.99,[fire]),.52)
        self.assertEqual(expected_visibility((2,4),100,[fire]),1)


if __name__=='__main__':unittest.main()
