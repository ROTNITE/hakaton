"""Standard-library HTTP server for the offline MetaRescue benchmark."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from world import World, DEFAULT_PROB
from simulation import run_collection

STATIC=Path(__file__).with_name('static')


def simulation_params(params):
    def val(name,default):return params.get(name,[str(default)])[0]
    probabilities={name:float(val(name,default)) for name,default in DEFAULT_PROB.items()}
    return {'seed':int(val('seed',2026)), 'people':int(val('people',16)),
            'scenario':val('scenario','urban'), 'map_size':int(val('map_size',25)),
            'scouts':int(val('scouts',3)), 'rescuers':int(val('rescuers',4)),
            'probabilities':probabilities}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args):
        if not self.path.startswith('/api/health'):
            print('%s %s'%(self.address_string(),fmt%args),flush=True)

    def send_bytes(self,code,data,content_type):
        self.send_response(code)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('Access-Control-Allow-Origin','*')
        self.end_headers();self.wfile.write(data)

    def do_GET(self):
        u=urlsplit(self.path)
        if u.path in ('/','/scout','/rescue','/mission'):
            file=STATIC/'index.html';typ='text/html; charset=utf-8'
        elif u.path=='/app.js':
            file=STATIC/'app.js';typ='application/javascript; charset=utf-8'
        elif u.path=='/style.css':
            file=STATIC/'style.css';typ='text/css; charset=utf-8'
        elif u.path=='/favicon.ico':
            return self.send_bytes(204,b'','image/x-icon')
        elif u.path=='/api/health':
            return self.send_bytes(200,b'{"status":"ok","version":"0.3.0"}','application/json')
        elif u.path=='/api/simulation':
            try:
                q=parse_qs(u.query)
                mode=q.get('mode',['mission'])[0]
                if mode not in ('scout','rescue','mission'):raise ValueError('Неверный режим')
                w=World(**simulation_params(q))
                payload=run_collection(mode,w)
                return self.send_bytes(200,json.dumps(payload,ensure_ascii=False,
                                                separators=(',',':'),allow_nan=False).encode(),
                                       'application/json; charset=utf-8')
            except (ValueError,TypeError) as err:
                return self.send_bytes(400,json.dumps({'error':str(err)},ensure_ascii=False).encode(),
                                       'application/json; charset=utf-8')
            except Exception as err:
                import traceback;traceback.print_exc()
                return self.send_bytes(500,json.dumps({'error':str(err)},ensure_ascii=False).encode(),
                                       'application/json; charset=utf-8')
        else:return self.send_bytes(404,b'Not found','text/plain')
        return self.send_bytes(200,file.read_bytes(),typ)


def start(open_browser=True,port=8765):
    import socket,webbrowser
    server=None
    for selected in range(port,port+50):
        try:
            server=ThreadingHTTPServer(('127.0.0.1',selected),Handler)
            break
        except OSError:continue
    if server is None:raise RuntimeError('Нет свободного локального порта')
    url=f'http://127.0.0.1:{server.server_port}/mission'
    print('\nMetaRescue Benchmark v0.3.0\nОткрыть: '+url+'\nЗакрыть: Ctrl+C\n',flush=True)
    if open_browser:
        import threading
        threading.Timer(.7,lambda:webbrowser.open(url)).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
