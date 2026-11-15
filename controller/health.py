"""Read-only normative controller health on a local HTTP listener."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading

from contracts.protocol import OPERATIONS


def _exclusive(socket_handle):
    # Windows SO_REUSEADDR can share a port with an existing local service and
    # route requests to the wrong owner. The health endpoint has one owner.
    if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
        socket_handle.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)


def require_port_available(port):
    with socket.socket() as probe:
        _exclusive(probe)
        try:probe.bind(('127.0.0.1',port))
        except OSError as error:
            raise RuntimeError(f'Local port {port} is already in use or unavailable') from error


class _HealthHTTPServer(ThreadingHTTPServer):
    allow_reuse_address=False
    allow_reuse_port=False

    def server_bind(self):
        _exclusive(self.socket)
        super().server_bind()


class HealthServer:
    def __init__(self,port=8131):
        self.lock=threading.Lock()
        self.state={'protocol_version':'1.0','component':'controller','status':'initializing',
                    'controller_id':'metarescue_controller','supported_operations':list(OPERATIONS)}
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path!='/v1/controller/health':
                    self.send_error(404);return
                data=json.dumps(owner.snapshot(),ensure_ascii=False).encode('utf-8')
                self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers()
                self.wfile.write(data)
        self.server=_HealthHTTPServer(('127.0.0.1',port),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,name='controller-health',daemon=True)

    def snapshot(self):
        with self.lock:return deepcopy(self.state)

    def update(self,**values):
        with self.lock:self.state.update(values)

    def __enter__(self):self.thread.start();return self

    def __exit__(self,*args):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
