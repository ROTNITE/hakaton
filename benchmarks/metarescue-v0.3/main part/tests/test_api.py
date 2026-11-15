"""End-to-end localhost HTTP API, including probability configuration."""
import json
import threading
import unittest
import urllib.request
import sys
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import Handler

class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(5)
    def fetch(self,path):
        with urllib.request.urlopen(self.url+path,timeout=45) as resp:
            return resp.status,resp.headers['Content-Type'],resp.read()
    def test_health_and_pages(self):
        status,_,body=self.fetch('/api/health')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['version'],'0.3.0')
        for path in ['/mission','/scout','/rescue','/style.css','/app.js']:
            status,_,body=self.fetch(path)
            self.assertEqual(status,200)
            self.assertGreater(len(body),100)
    def test_custom_events_work_in_api(self):
        url='/api/simulation?mode=mission&seed=123&people=6&scenario=open&map_size=35&scouts=5&rescuers=7&new_target=100&collapse=100'
        status,_,raw=self.fetch(url)
        self.assertEqual(status,200)
        o=json.loads(raw)
        self.assertEqual(o['version'],'0.3.0')
        self.assertEqual(o['scenario']['width'],35)
        self.assertEqual(o['scenario']['scouts'],5)
        self.assertEqual(o['scenario']['rescuers'],7)
        self.assertEqual(len(o['runs']),5)
        self.assertGreater(sum(e['type']=='new_target' for e in o['scenario']['events']),5)
        self.assertTrue(any(r['rescues'] for r in o['runs']))
        self.assertEqual(o['scenario']['probabilities']['collapse'],100)
    def test_invalid_parameter_returns_400(self):
        try:
            self.fetch('/api/simulation?mode=mission&people=999')
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code,400)
            self.assertIn('error',json.loads(exc.read()))
        else:self.fail('Request should be rejected')

if __name__=='__main__':unittest.main()
