"""Local standard-library server. No internet, accounts or remote dependencies."""
from __future__ import annotations
import http.server, json, os, socketserver, threading, urllib.parse, webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from functools import lru_cache
from world import World, SCENARIOS
from scout import run_scout, LABELS as SCOUT_LABELS
from rescue import run_rescue, LABELS as RESCUE_LABELS
from mission import run_mission, CONFIGS

STATIC=Path(__file__).parent/'static'

@lru_cache(maxsize=20)
def scenario(seed, people, preset, grid_size=25, scouts=3, rescuers=4):
    return World(seed,people,preset,grid_size,scouts,rescuers)

@lru_cache(maxsize=12)
def run_collection(mode, seed, people, preset="urban", grid_size=25, scouts=3, rescuers=4):
    w=scenario(seed,people,preset,grid_size,scouts,rescuers)
    if mode=='scout':
        methods=['random','sweep','greedy','frontier','nsga2']
        runs=[run_scout(w,k) for k in methods]
    elif mode=='rescue':
        methods=['nearest','greedy','local','nsga2']
        # OR-Tools is optional, but when installed is used for real.
        try:
            from ortools.sat.python import cp_model
            methods.append('ortools')
        except ImportError:pass
        runs=[run_rescue(w,k) for k in methods]
    elif mode=='mission':
        methods=['greedy_greedy','frontier_local','nsga2_greedy','greedy_nsga2','nsga2_nsga2']
        scout_cache={m:run_scout(w,m,small=True) for m in ['greedy','frontier','nsga2']}
        runs=[run_mission(w,k,scout_cache) for k in methods]
    else:raise ValueError('Unknown mode')
    return {'version':'0.2.0','mode':mode,'scenario':w.public_map(), 'runs':runs,
            'notes':{'scout':'Истинные позиции пострадавших скрыты от всех разведывательных планировщиков. Обнаружение при полном обследовании сектора детерминированное.',
                     'rescue':'Offline: все позиции пострадавших известны одновременно. Одинаковая карта, A*, ресурсы и дедлайн для всех методов.',
                     'mission':'Online: только обнаруженные люди доступны эвакуации. Роботы не прерывают начатую транспортировку, планы пересчитываются по событиям.'}[mode]}

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(STATIC),**kwargs)
    def log_message(self,fmt,*args):
        if not str(args[1] if len(args)>1 else '').startswith('200'):
            super().log_message(fmt,*args)
    def do_GET(self):
        path=urllib.parse.urlparse(self.path)
        if path.path=='/api/health':
            return self.json_response({'ok':True,'name':'MetaRescue Benchmark','version':'0.2.0'})
        if path.path=='/api/simulation':
            q=urllib.parse.parse_qs(path.query)
            mode=q.get('mode',['scout'])[0]
            try:
                seed=int(q.get('seed',['2026'])[0]);people=int(q.get('people',['16'])[0]);preset=q.get('scenario',['urban'])[0]
                grid_size=int(q.get('map_size',['25'])[0]);scouts=int(q.get('scouts',['3'])[0]);rescuers=int(q.get('rescuers',['4'])[0])
                if not 0<=seed<=999999999:raise ValueError('seed вне диапазона 0..999999999')
                if not 3<=people<=80:raise ValueError('Количество пострадавших: 3..80')
                if grid_size not in (25,35,45,55,65):raise ValueError('Размер карты: 25, 35, 45, 55 или 65')
                if not 1<=scouts<=10:raise ValueError('Количество дронов: 1..10')
                if not 1<=rescuers<=12:raise ValueError('Количество эвакуаторов: 1..12')
                if preset not in SCENARIOS:raise ValueError('Неизвестный сценарий')
                data=run_collection(mode,seed,people,preset,grid_size,scouts,rescuers)
                return self.json_response(data)
            except (ValueError,TypeError) as e:
                return self.json_response({'error':str(e)},400)
            except Exception as e:
                import traceback
                traceback.print_exc()
                return self.json_response({'error':f'{type(e).__name__}: {e}'},500)
        if path.path in ('/','/index.html','/scout','/rescue','/mission'):
            self.path='/index.html';return super().do_GET()
        return super().do_GET()
    def json_response(self,data,status=200):
        raw=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(raw)))
        self.end_headers();self.wfile.write(raw)

class ThreadingHTTPServer(socketserver.ThreadingMixIn,http.server.HTTPServer):
    daemon_threads=True
    allow_reuse_address=True

def start(open_browser=True):
    import socket
    host='127.0.0.1'
    server=None
    for port in [8765,8766,0]:
        try:
            server=ThreadingHTTPServer((host,port),Handler);break
        except OSError:continue
    if server is None:raise RuntimeError('Не удалось открыть локальный сервер')
    url=f'http://{host}:{server.server_port}/'
    print('\n  MetaRescue Benchmark запущен!')
    print('  Откройте в браузере: '+url)
    print('  Для выхода нажмите Ctrl+C в окне запуска.\n')
    if open_browser:threading.Timer(1.0,lambda:webbrowser.open(url)).start()
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:server.server_close()
