from argparse import Namespace
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from tools import core_event_check, run_core_acceptance, run_mission


class MissionCompletionTests(unittest.TestCase):
    def run_mission(self, *, attached=False, native_code=0, controller_code=0,
                    wall_timeout=0, wait_timeout=False, archived_status='time_limit',
                    corrupt_journal=False, change_inputs=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'source.json'
            source.write_text(json.dumps({'settings':{'seed':2026}}),encoding='utf-8')
            output=root/'missions/test'
            episode='a'*32
            native=Mock(pid=456,returncode=native_code)
            native.poll.side_effect=[None,native_code,native_code]
            native.wait.return_value=native_code
            controller=Mock(pid=789,returncode=None)
            controller.poll.side_effect=lambda:controller.returncode
            client=Mock()
            client.health.return_value={'status':'ready'}
            client.capabilities.return_value={'extensions':['metarescue.announced_map.v1']}
            client.reset.return_value={'observation':{'episode_id':episode,'metaevolution':{'announced_map':{}}}}

            def finish(timeout):
                if controller.terminate.called:
                    controller.returncode=1
                    return 1
                if wait_timeout:
                    raise subprocess.TimeoutExpired('controller',timeout)
                controller.returncode=controller_code
                if controller_code:
                    return controller_code
                control=output/'controller'
                control.mkdir()
                journal=control/'controller.jsonl.gz'
                journal.write_bytes(b'controller archive')
                manifest=json.loads((output/'manifest.json').read_text(encoding='utf-8'))
                (control/'manifest.json').write_text(json.dumps({
                    'state':'complete','run_id':manifest['run_id'],'episode_id':episode,
                    'episode_status':'time_limit','metrics':{'confirmed_evacuations':1},
                    'journal':journal.name,'journal_sha256':'bad' if corrupt_journal else hashlib.sha256(journal.read_bytes()).hexdigest(),
                }),encoding='utf-8')
                return 0

            controller.wait.side_effect=finish
            args=Namespace(attach_native_pid=native.pid if attached else None,build=False,name='test',
                           ai_mode='OFF',ai_scope='global_local',contest_coordination=True,policy='nsga2_nsga2',
                           headless=True,visible=False,realtime=False,port=8130,health_port=8131,layout=source,
                           seed=None,optimizer_seed=2026,ai_replay=None,ai_tariff=None,ready_timeout=5,
                           wall_timeout=wall_timeout)
            verification={'passed':True,'episode_id':episode,'status':archived_status}
            final_hashes={} if change_inputs else {'input':'initial'}
            with (patch.object(run_mission,'DEFAULT_OUTPUT',root),
                  patch.object(run_mission,'existing_unreal',return_value=[{'pid':native.pid}] if attached else []),
                  patch.object(run_mission,'hashes',side_effect=[{'input':'initial'},final_hashes]),
                  patch.object(run_mission,'public_map',return_value={}),
                  patch.object(run_mission,'native_command',return_value=['native']),
                  patch.object(run_mission,'AttachedNative',return_value=native),
                  patch.object(run_mission,'EnvironmentClient',return_value=client),
                  patch.object(run_mission,'verify_archive',return_value=verification),
                  patch.object(run_mission.subprocess,'Popen',side_effect=[controller] if attached else [native,controller]),
                  patch('builtins.print')):
                try:
                    code=run_mission.run(args)
                except (RuntimeError, TimeoutError, ValueError) as error:
                    code=error
            manifest=json.loads((output/'manifest.json').read_text(encoding='utf-8'))
        return code,manifest,controller,native

    def test_standalone_exit_zero_allows_controller_to_finalize(self):
        code,manifest,controller,_=self.run_mission()
        self.assertEqual(code,0)
        self.assertEqual(manifest['episode_status'],'time_limit')
        self.assertEqual(manifest['native_exit_code'],manifest['controller_exit_code'])
        controller.terminate.assert_not_called()

    def test_nonzero_native_exit_and_attached_exit_still_fail(self):
        for args,expected in (({'native_code':7},7),({'attached':True},0)):
            with self.subTest(args=args):
                error,manifest,controller,native=self.run_mission(**args)
                self.assertEqual(str(error),f'Native exited before controller: {expected}')
                self.assertEqual(manifest['state'],'failed')
                controller.terminate.assert_called_once()
                native.terminate.assert_not_called()

    def test_grace_is_bounded_by_remaining_wall_time(self):
        error,manifest,controller,_=self.run_mission(wall_timeout=1,wait_timeout=True)
        self.assertIsInstance(error,TimeoutError)
        self.assertIn('Mission wall timeout',str(error))
        self.assertGreater(controller.wait.call_args_list[0].kwargs['timeout'],0)
        self.assertLessEqual(controller.wait.call_args_list[0].kwargs['timeout'],1)
        self.assertEqual(manifest['state'],'failed')

    def test_grace_is_bounded_even_without_wall_limit(self):
        error,manifest,controller,_=self.run_mission(wait_timeout=True)
        self.assertIsInstance(error,TimeoutError)
        self.assertIn('Controller did not finalize after native exit',str(error))
        self.assertGreater(controller.wait.call_args_list[0].kwargs['timeout'],0)
        self.assertEqual(manifest['state'],'failed')

    def test_grace_keeps_controller_status_and_integrity_checks(self):
        for args,expected in (
            ({'controller_code':9},'Controller failed: 9'),
            ({'archived_status':'success'},'Native/controller terminal statuses differ'),
            ({'corrupt_journal':True},'Controller journal SHA-256 mismatch'),
        ):
            with self.subTest(args=args):
                error,manifest,_,_=self.run_mission(**args)
                self.assertEqual(str(error),expected)
                self.assertEqual(manifest['state'],'failed')
        code,manifest,_,_=self.run_mission(change_inputs=True)
        self.assertEqual(code,1)
        self.assertEqual(manifest['error'],'Frozen inputs changed')


class CoreInteropAcceptanceTests(unittest.TestCase):
    def test_persistent_interop_verifies_four_archives_before_owner_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            layout=root/'layout.json';layout.write_text('{}',encoding='utf-8')
            output=root/'core-acceptance/test'
            ids=[f'{i:032x}' for i in range(4)]
            native=Mock(pid=42,returncode=None)
            native.poll.side_effect=lambda:native.returncode
            client=Mock();client.health.return_value={'status':'ready'}
            command=Mock(return_value=['native'])

            def drive(port,seed):
                self.assertFalse(command.call_args.kwargs['exit_on_close'])
                with (output/'stdout.log').open('a',encoding='utf-8') as log:
                    for episode in ids:
                        log.write(f'MR_CORE episode {episode} journal path\n')
                return {'passed':True,'episode_ids':ids}

            def verify(archive):
                self.assertIsNone(native.poll())
                return {'episode_id':archive.name,'status':'failed','passed':True}

            archives=Mock(side_effect=verify)

            def wait(timeout):
                if native.terminate.called:
                    native.returncode=1
                    return 1
                self.assertEqual(archives.call_count,4)
                self.assertTrue((output/'owner-exit.request').is_file())
                self.assertIn(f'-MRCoreExitRequestFile={output / "owner-exit.request"}',command.return_value)
                native.returncode=0
                return 0

            native.wait.side_effect=wait
            with (patch.object(run_core_acceptance,'DEFAULT_OUTPUT',root),
                  patch.object(run_core_acceptance,'existing_unreal',return_value=[]),
                  patch.object(run_core_acceptance,'source_hashes',return_value={}),
                  patch.object(run_core_acceptance,'native_command',command),
                  patch.object(run_core_acceptance.subprocess,'Popen',return_value=native),
                  patch.object(run_core_acceptance,'EnvironmentClient',return_value=client),
                  patch.object(run_core_acceptance.core_interop_check,'drive',side_effect=drive),
                  patch.object(run_core_acceptance.core_interop_check,'verify'),
                  patch.object(run_core_acceptance,'verify_archive',archives),
                  patch('sys.argv',['runner',str(layout),'--name','test','--interop','--headless']),
                  patch('builtins.print')):
                self.assertEqual(run_core_acceptance.main(),0)
            result=json.loads((output/'verification.json').read_text(encoding='utf-8'))
        self.assertEqual([row['episode_id'] for row in result['native_archives']],ids)
        self.assertEqual(result['native_exit_code'],0)
        native.terminate.assert_not_called()


class WorkflowTerminalTests(unittest.TestCase):
    def verify_terminal(self, *, carrying=False, rescued=True):
        result={'time':12.5,'metrics':{'confirmed_evacuations':1},
                'terminal_public_carrying':['rover'],
                'native_archives':[{'episode_id':'episode','status':'success'}]}
        records=MagicMock()
        records.__len__.return_value=1
        records.json_records.return_value=iter([{
            'record_type':'truth_snapshot','time':12.5,
            'payload':{'phase':'close','agents':[{'id':'rover','physical':{'carrying':carrying}}],
                       'targets':[{'id':'person','rescued':rescued}]},
        }])
        with patch.object(run_core_acceptance,'IndexedRecords',return_value=records):
            run_core_acceptance.verify_workflow_terminal(result,Path('output'))
        return result

    def test_delayed_public_cargo_uses_final_physical_custody(self):
        result=self.verify_terminal()
        self.assertEqual(result['terminal_truth']['carrying_agents'],[])
        self.assertEqual(result['terminal_truth']['rescued_targets'],['person'])

    def test_terminal_rejects_attached_cargo_and_unrescued_person(self):
        with self.assertRaisesRegex(AssertionError,'Cargo remains physically attached'):
            self.verify_terminal(carrying=True)
        with self.assertRaisesRegex(AssertionError,'Physical and confirmed evacuations differ'):
            self.verify_terminal(rescued=False)


class CoreEventObservationTests(unittest.TestCase):
    def drive(self, *, reset_surface=False, received_at=7, observed_at=6):
        world={'fixture':{'id':'core-event-effects-v1','ground_route':[[1,0,0],[2,0,0]],
                          'drone_route':[[0,0,1]],'ground_second_command_at':1},
               'settings':{'seed':7,'horizon':10},'event_model':{'profile':'v3','probability_window_s':30,
               'events':[{'time':2}],'late_people':[{'id':1,'available_at':5}]}}
        declared={'id':'map-airspace','type':'air'}
        delivered={'id':'surface-23-2','observed_at':observed_at,'received_at':received_at,'surface':{
            'kinds':['mud','road_damage','smoke','low_visibility','flood'],'depth_m':.4,'ground_blocked':True}}
        agents=[{'id':'a','kind':'aerial','position':[0,0,1]},{'id':'g','kind':'ground','position':[0,0,0]}]
        client=Mock()
        client.capabilities.return_value={'event_model':{'profile':'v3','probability_window_s':30}}
        client.reset.side_effect=[{'status':'running','observation':{
            'episode_id':episode,'time':0,'zones':[declared,delivered] if reset_surface else [declared],
            'events':[],'targets':[],'agents':agents,'metaevolution':{'announced_map':{}},
        }} for episode in ('first','second')]
        client.step.side_effect=[{'status':'time_limit','observation':{
            'time':10,'zones':[declared,delivered],'events':[{'status':'resolved'}],
            'targets':[{'id':'person-1','observed_at':6,'received_at':7}],
        }} for _ in range(2)]
        with patch.object(core_event_check,'validate_episode_response',side_effect=lambda value,**_:value),patch('builtins.print'):
            return core_event_check.drive(client,world,Mock())

    def test_declared_zones_survive_reset_and_are_not_counted_as_measurements(self):
        result=self.drive()
        self.assertTrue(result['passed'])
        self.assertEqual(set(result['event_episodes']),{'first','second'})
        for evidence in result['event_episodes'].values():
            self.assertEqual(evidence['first_hazard_received_at'],7)
            self.assertEqual(evidence['max_known_depth_m'],.4)

    def test_surface_measurement_at_reset_is_a_failure(self):
        with self.assertRaisesRegex(AssertionError,'Reset exposed a measured surface'):
            self.drive(reset_surface=True)

    def test_surface_measurement_requires_causal_timestamps(self):
        for timestamps in ({'received_at':11},{'received_at':5},{'observed_at':1}):
            with self.subTest(timestamps=timestamps), self.assertRaisesRegex(AssertionError,'Noncausal surface measurement'):
                self.drive(**timestamps)


if __name__=='__main__':
    unittest.main()
