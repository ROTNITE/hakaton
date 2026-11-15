from copy import deepcopy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
import unittest

from contracts.protocol import (ProtocolError,encode,strict_json,validate_episode_response,
                                MAX_BODY_BYTES,MAX_RESPONSE_BYTES)
from controller.client import EnvironmentClient,PreparedRequest,TransportFailure


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples=json.loads((Path(__file__).parents[1]/'contracts/examples/interaction-v1.json').read_text(encoding='utf-8'))

    def test_response_identity_and_time_are_not_silently_mixed(self):
        for field,value in (('time',99),('episode_id','another'),('request_id','another')):
            response=deepcopy(self.examples['step_response']);response[field]=value
            with self.subTest(field=field),self.assertRaises(ProtocolError):validate_episode_response(response,step=True)

    def test_large_observation_does_not_raise_the_request_body_limit(self):
        raw=encode({'large_public_geometry':'x'*(MAX_BODY_BYTES+1)})
        with self.assertRaises(ProtocolError):strict_json(raw)
        self.assertIn('large_public_geometry',strict_json(raw,maximum_bytes=MAX_RESPONSE_BYTES))

    def test_uncertain_step_retries_the_exact_original_bytes(self):
        bodies=[];response=encode(self.examples['step_response'])
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                bodies.append(self.rfile.read(int(self.headers['Content-Length'])))
                if len(bodies)==1:
                    self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(response)));self.end_headers();self.wfile.write(response)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        client=EnvironmentClient('http://127.0.0.1:'+str(server.server_port))
        try:
            decision=deepcopy(self.examples['decisions']['select'])
            prepared=client.prepare_step(decision);decision['request_id']='mutated-after-serialization'
            actual=client.submit(prepared)
            self.assertEqual(actual['episode_id'],self.examples['step_response']['episode_id'])
            self.assertEqual(bodies,[prepared.body,prepared.body])
        finally:
            client.disconnect();server.shutdown();server.server_close();thread.join(timeout=2)

    def test_network_failure_is_explicitly_ambiguous(self):
        audit=[];client=EnvironmentClient('http://127.0.0.1:1',timeout_s=.1,audit=audit.append)
        try:
            with self.assertRaises(TransportFailure) as failure:
                client.submit(PreparedRequest('POST','/v1/environment/step',b'{}'),network_retries=0)
            self.assertTrue(failure.exception.state_may_have_changed)
            self.assertEqual(audit[0]['kind'],'http_transport_failure')
        finally:client.disconnect()

    def test_private_paths_are_not_a_client_extension(self):
        client=EnvironmentClient()
        for path in ('/v1/environment/../truth','/v1/environment/%2e%2e/truth','/private/truth'):
            with self.subTest(path=path),self.assertRaises(ValueError):client.submit(PreparedRequest('GET',path))

    def test_invalid_wire_is_not_reported_as_an_explicit_server_rejection(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                raw=b'{"protocol_version":"1.0","time":NaN}'
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        client=EnvironmentClient('http://127.0.0.1:'+str(server.server_port))
        try:
            with self.assertRaises(TransportFailure) as failure:
                client.submit(PreparedRequest('POST','/v1/environment/step',b'{}'))
            self.assertTrue(failure.exception.state_may_have_changed)
        finally:
            client.disconnect();server.shutdown();server.server_close();thread.join(timeout=2)


if __name__=='__main__':unittest.main()
