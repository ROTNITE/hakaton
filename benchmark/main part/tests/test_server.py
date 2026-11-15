import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rescuebench.server import Server


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=Server(('127.0.0.1',0))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.server.server_address[1])

    @classmethod
    def tearDownClass(cls):
        cls.server.app.close();cls.server.shutdown();cls.server.server_close();cls.thread.join(3)

    def request(self,path,data=None,extra=None):
        headers={'X-Rescue-Benchmark':'1','Content-Type':'application/json'}
        headers.update(extra or {})
        req=Request(self.url+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        try:
            with urlopen(req,timeout=15) as response:return response.status,response.read(),response.headers
        except HTTPError as response:
            with response:return response.code,response.read(),response.headers

    def test_static_and_export(self):
        for path in ['/','/app.js','/styles.css','/favicon.svg']:
            status,body,headers=self.request(path);self.assertEqual(status,200);self.assertTrue(body)
            self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        status,body,_=self.request('/api/export');self.assertEqual(status,200)
        self.assertIn('metadata',json.loads(body));self.assertIn('world',json.loads(body))

    def test_reset_step_and_stale_session(self):
        status,body,_=self.request('/api/reset',{'mode':'scout','config':{'width':20,'height':20,'people':8,'population':12,'generations':2}})
        self.assertEqual(status,200);session=json.loads(body)['session']
        status,body,_=self.request('/api/step',{'session':session,'steps':3})
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['time'],3)
        status,_,_=self.request('/api/step',{'session':'old','steps':1});self.assertEqual(status,409)

    def test_reject_invalid_and_cross_origin_requests(self):
        status,_,_=self.request('/api/reset',{'config':{'people':99999}});self.assertEqual(status,400)
        status,_,_=self.request('/api/reset',[],{});self.assertEqual(status,400)
        status,_,_=self.request('/api/reset',{}, {'Origin':'https://example.com'});self.assertEqual(status,403)
        status,_,_=self.request('/api/reset',{}, {'Host':'evil.example'});self.assertEqual(status,403)
        status,_,_=self.request('/../main.py');self.assertEqual(status,404)

    def test_batch_cancel_is_explicit(self):
        status,body,_=self.request('/api/batch',{'mode':'rescue','count':20,'config':{'width':20,'height':20,'people':12}})
        self.assertEqual(status,200);ident=json.loads(body)['id']
        status,_,_=self.request('/api/batch/cancel',{'id':ident});self.assertEqual(status,200)
        status,body,_=self.request('/api/batch/'+ident);self.assertEqual(status,200)
        self.assertNotIn('cancel',json.loads(body))


if __name__=='__main__':unittest.main()
