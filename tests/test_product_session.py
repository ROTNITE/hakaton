import json
import os
import socket
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from controller.operational import OperationalControl
from tools.product_session import REQUEST_FORMAT,SESSION_FORMAT,availability,parse_request,prepare,session_file
from tools.native_archive import file_sha256
from tools.native_process import AttachedNative


class ProductSessionTests(unittest.TestCase):
    def request(self,**controller):
        return {'format':REQUEST_FORMAT,'settings':{'layout':'rescue_quarter','city_revision':'2.2','people':3},'controller':controller}

    def test_launcher_rejects_occupied_health_port_before_creating_native_or_session(self):
        from tools.run_product import main
        with tempfile.TemporaryDirectory() as directory,socket.socket() as owner:
            owner.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            owner.bind(('127.0.0.1',0));owner.listen(1);port=owner.getsockname()[1]
            with patch('sys.argv',['run_product','--health-port',str(port)]),\
                 patch('tools.run_product.DEFAULT_OUTPUT',Path(directory)),\
                 patch('tools.run_product.existing_unreal',return_value=[]),\
                 patch('tools.run_product.require_port_available',side_effect=[None,RuntimeError('occupied')]),\
                 patch('tools.run_product.subprocess.Popen') as launch:
                with self.assertRaisesRegex(RuntimeError,'occupied'):main()
                launch.assert_not_called()
                self.assertFalse((Path(directory)/'product-sessions').exists())

    def test_validation_preserves_profiles_and_requires_real_baselines(self):
        request=self.request(ai_mode='LIVE',realtime=False)
        result=parse_request(request)
        self.assertTrue(result['controller']['realtime'])
        self.assertEqual(result['settings']['event_profile'],'v052')
        self.assertEqual(len(result['settings']['probabilities']),7)
        request['settings']['event_profile']='v3'
        self.assertEqual(len(parse_request(request)['settings']['probabilities']),8)
        with self.assertRaises(ValueError):parse_request(self.request(policy='fixed_workflow'))
        result=parse_request(self.request(policy='fixed_workflow',contest_coordination=False))
        self.assertEqual(result['controller']['ai_mode'],'OFF')
        with self.assertRaises(ValueError):parse_request(self.request(scout_population=True))
        with self.assertRaises(ValueError):parse_request(self.request(optimizer_seed=-1))
        with self.assertRaises(ValueError):parse_request(self.request(secret='never'))

    def test_prepare_has_distinct_private_world_public_map_and_paused_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            request=Path(directory)/'request.json'
            request.write_text(json.dumps(self.request()))
            before=request.read_bytes()
            with patch('tools.product_session.availability',return_value={'key_configured':False,'budget_used':6,'budget_limit':240}):
                result=prepare({},request)
            self.assertEqual(result['state'],'prepared')
            self.assertTrue(result['preflight']['passed'])
            self.assertEqual(file_sha256(Path(result['layout'])),result['layout_sha256'])
            public=json.loads((request.parent/'world.public.json').read_bytes())
            self.assertNotIn('people',public)
            self.assertNotIn('event_model',public)
            self.assertNotIn('settings',public)
            self.assertEqual(request.read_bytes(),before)
            gate=OperationalControl(request.parent/'control.json',session_id=result['control_session'])
            self.assertEqual(gate.take(),'wait')

    def test_availability_returns_only_key_presence_and_existing_budget(self):
        with patch('tools.product_session.load_key',return_value=''),patch('tools.product_session.LiveBudget.snapshot',return_value={'used':6,'limit':240}):
            self.assertEqual(availability(),{'key_configured':False,'budget_used':6,'budget_limit':240})
        with patch('tools.product_session.load_key',return_value='private-value'),patch('tools.product_session.LiveBudget.snapshot',return_value={'used':6,'limit':240}):
            self.assertEqual(availability(),{'key_configured':True,'budget_used':6,'budget_limit':240})

    def test_session_lease_cannot_reference_another_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);workspace=root/'product-sessions/one';workspace.mkdir(parents=True)
            path=workspace/'session.json'
            data={'format':SESSION_FORMAT,'id':'0'*32,'workspace':str(workspace.resolve())}
            path.write_text(json.dumps(data))
            with patch('tools.product_session.DEFAULT_OUTPUT',root):
                self.assertEqual(session_file(path),data)
                data['workspace']=str(root);path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):session_file(path)
                (root/'outside.json').write_text('{}')
                with self.assertRaises(ValueError):session_file(root/'outside.json')

    @unittest.skipUnless(os.name=='nt','Windows read-only process handle')
    def test_attached_handle_reads_lifetime_without_owning_termination(self):
        process=AttachedNative(os.getpid())
        try:self.assertIsNone(process.poll())
        finally:process.close()
        self.assertFalse(hasattr(process,'terminate'))
