from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from analytics.metrics import VERSION
from analytics.server import main
from analytics.store import SCHEMA
from tools.analytics_service import analytics_health,available_port,ensure_analytics


class AnalyticsServiceTests(unittest.TestCase):
    def test_archive_root_defaults_to_configured_output_and_can_be_overridden(self):
        configured = Path('configured output')
        explicit = Path('other output')
        with patch('analytics.server.DEFAULT_OUTPUT', configured), patch('analytics.server.serve') as serve:
            main(['--port', '8142'])
            serve.assert_called_once_with(configured, 8142)
            serve.reset_mock()
            main(['--root', str(explicit), '--port', '8143'])
            serve.assert_called_once_with(explicit, 8143)

    def test_reuse_requires_matching_component_version_and_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            health={'format':'metarescue.analytics-health.v1','component':'metarescue_analytics',
                    'metrics_version':VERSION,'index_schema':SCHEMA,'output_root':str(root.resolve())}
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_GET(self):
                    data=json.dumps(health).encode()
                    self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                port=server.server_port
                with patch('tools.analytics_service.subprocess.Popen') as spawn:
                    self.assertTrue(ensure_analytics(root,root,port=port)['reused'])
                    spawn.assert_not_called()
                    health['component']='another-service'
                    with self.assertRaises(RuntimeError):ensure_analytics(root,root,port=port)
                    spawn.assert_not_called()
                health['component']='metarescue_analytics';health['metrics_version']='old'
                with self.assertRaises(RuntimeError):analytics_health(root,port=port)
                health['metrics_version']=VERSION;health['output_root']=str(root/'elsewhere')
                with self.assertRaises(RuntimeError):analytics_health(root,port=port)
                with patch('tools.analytics_service.analytics_health',side_effect=[RuntimeError('other version'),None]):
                    self.assertEqual(available_port(root,exclude=(8141,)),8142)
            finally:server.shutdown();server.server_close();thread.join(timeout=5)
