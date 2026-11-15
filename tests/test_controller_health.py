import http.client
import json
import socket
import unittest

from contracts.protocol import OPERATIONS
from controller.health import HealthServer,require_port_available


class ControllerHealthTests(unittest.TestCase):
    def test_listener_rejects_an_occupied_port_and_leaves_its_owner_intact(self):
        with socket.socket() as owner:
            owner.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            owner.bind(('127.0.0.1',0));owner.listen(1);port=owner.getsockname()[1]
            with self.assertRaises(OSError):
                health=HealthServer(port)
                health.server.server_close()
            with self.assertRaisesRegex(RuntimeError,f'Local port {port} is already in use'):
                require_port_available(port)
            self.assertEqual(owner.getsockname(),('127.0.0.1',port))
    def test_public_endpoint_is_read_only_and_state_is_copied(self):
        with HealthServer(0) as health:
            health.update(status='ready',episode_id='opaque-episode')
            connection=http.client.HTTPConnection('127.0.0.1',health.server.server_port,timeout=3)
            before=health.snapshot()
            self.assertEqual(before['supported_operations'],list(OPERATIONS))
            for _ in range(3):
                connection.request('GET','/v1/controller/health')
                response=connection.getresponse()
                self.assertEqual(response.status,200)
                self.assertEqual(json.loads(response.read()),before)
            copy=health.snapshot();copy['status']='changed outside server'
            self.assertEqual(health.snapshot(),before)
            connection.close()

    def test_unknown_path_does_not_expose_controller_objects(self):
        with HealthServer(0) as health:
            connection=http.client.HTTPConnection('127.0.0.1',health.server.server_port,timeout=3)
            connection.request('GET','/controller/private')
            response=connection.getresponse();response.read()
            self.assertEqual(response.status,404)
            self.assertNotIn('private',health.snapshot())
            connection.close()


if __name__=='__main__':unittest.main()
