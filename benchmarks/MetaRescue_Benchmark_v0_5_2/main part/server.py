"""Local benchmark API, three NSGA-II/AI systems and streamed full TXT audits."""
from __future__ import annotations
import gzip, http.server, json, os, socketserver, threading, urllib.parse, webbrowser, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from run_manager import RUN_MANAGER
from world import World, SCENARIOS, DEFAULT_PROBABILITIES
from mission import run_mission
from log_export import log_chunks

STATIC=Path(__file__).parent/'static'
MAP_CHOICES=(25,35,45,55,65,75,100,125,150)
VARIANTS=(('base','NSGA-II + NSGA-II'),
          ('global_ai','NSGA-II ×2 + Global AI'),
          ('global_local_ai','NSGA-II ×2 + Global + Local AI'))

def run_collection(mode='mission',seed=2026,people=16,preset='urban',grid_size=25,scouts=3,
                   rescuers=4,probabilities=None,ai_mode='live',max_calls=240,
                   local_timeout=3.,global_timeout=6.,run_id='0'):
    if mode!='mission':raise ValueError('В v0.4 доступен только режим сравнения общих миссий')
    w=World(seed,people,preset,grid_size,scouts,rescuers,
            dict(probabilities) if probabilities is not None else None)
    # Each contender runs in a separate fresh Python process, avoiding shared
    # mutable A*/NSGA-II caches and exhausting memory on 150x150 stress tests.
    options={'seed':seed,'people':people,'preset':preset,'grid_size':grid_size,
             'scouts':scouts,'rescuers':rescuers,
             'probabilities':dict(probabilities) if probabilities is not None else None,
             'ai_mode':ai_mode,'max_calls':max_calls,
             'local_timeout':local_timeout,'global_timeout':global_timeout}
    def calculate(item,outdir):
        name,label=item
        settings={**options,'variant':name}
        filepath=Path(outdir)/(name+'.json')
        cmd=[sys.executable,str(Path(__file__).parent/'variant_worker.py'),
             json.dumps(settings,ensure_ascii=False),str(filepath)]
        proc=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                            timeout=max(900, min(24000,options['max_calls']*max(options['local_timeout'],options['global_timeout'])+300)),check=False)
        if proc.returncode!=0:
            raise RuntimeError('Ошибка вычисления '+name+': '+proc.stderr.decode('utf-8','replace')[-2000:])
        return json.loads(filepath.read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='metarescue_v04_') as tmp:
        # Live API requests are kept sequential to avoid provider rate-limit
        # collisions; mock/off modes can compute three variants concurrently.
        workers=1 if ai_mode=='live' and bool(os.environ.get('DEEPSEEK_API_KEY')) else 3
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures=[pool.submit(calculate,item,tmp) for item in VARIANTS]
            results=[f.result() for f in futures]
    truth=[{'id':p.id,'x':p.x,'y':p.y,'priority':p.priority,
            'appearance_t':w._appear_time.get(p.id,0)} for p in w.people]
    return {'version':'0.5.2','mode':'mission','scenario':w.public_map(),
            'runs':results,'_truth_people':truth,'ai_mode':ai_mode,'run_id':run_id,
            'ai_connected':bool(os.environ.get('DEEPSEEK_API_KEY')),
            'notes':'v0.5.2: стратегический Global AI, оценка 5 альтернатив NSGA-II, причинная разведка с непрерывным патрулём, бесконечная энергия, датчики и сообщения. Три независимых прогона: базовые NSGA-II, + Global AI и + Global/Local AI. '
                    'DeepSeek только с ключом в LIVE; MOCK — явная тестовая имитация, '
                    'не результат нейросети. События и исходные ресурсы идентичны.'}

def params(q):
    def get(name,default):return q.get(name,[str(default)])[0]
    seed=int(get('seed',2026));people=int(get('people',16));preset=get('scenario','urban')
    grid=int(get('map_size',25));scouts=int(get('scouts',3));rescuers=int(get('rescuers',4))
    mode=get('mode','mission')
    if mode!='mission':raise ValueError('Поддерживается только общая миссия')
    if not 0<=seed<=999999999:raise ValueError('seed: 0..999999999')
    if not 3<=people<=600:raise ValueError('Пострадавшие: 3..600')
    if grid not in MAP_CHOICES:raise ValueError('Размер карты: '+', '.join(map(str,MAP_CHOICES)))
    if not 1<=scouts<=48:raise ValueError('Дроны: 1..48')
    if not 1<=rescuers<=40:raise ValueError('Эвакуаторы: 1..40')
    if preset not in SCENARIOS:raise ValueError('Неизвестный сценарий')
    probabilities={}
    for name,default in DEFAULT_PROBABILITIES.items():
        value=int(get('p_'+name,default))
        if not 0<=value<=100:raise ValueError('Вероятность '+name+': 0..100%')
        probabilities[name]=value
    mode_ai=get('ai_mode','live')
    if mode_ai not in ('live','mock','off'):raise ValueError('Режим AI: live/mock/off')
    calls=int(get('ai_calls',240));timeout_l=float(get('local_timeout',3));timeout_g=float(get('global_timeout',6))
    if not 0<=calls<=1600:raise ValueError('Лимит вызовов: 0..1600')
    if not .5<=timeout_l<=30 or not .5<=timeout_g<=60:raise ValueError('Тайм-аут вне диапазона')
    run_id=get('run_id','0')
    if len(run_id)>40 or not run_id.replace('-','').replace('_','').isalnum():raise ValueError('run_id некорректен')
    return (mode,seed,people,preset,grid,scouts,rescuers,
            tuple(sorted(probabilities.items())),mode_ai,calls,timeout_l,timeout_g,run_id)

def public_projection(data):
    """Full evidence stays server-side for TXT; playback receives causal minimal updates.
    Avoid sending 30,000 x 25 clear observations and all full API prompts to Canvas.
    """
    out={k:v for k,v in data.items() if not k.startswith('_') and k!='runs'}
    public_runs=[]
    for run in data['runs']:
        visible=dict(run)
        previous={};updates=[]
        for observation in run.get('knowledge_events',[]):
            cells=[]
            for x,y,hazard,smoke in observation.get('cells',[]):
                key=(x,y);now=(hazard,bool(smoke))
                if previous.get(key,(None,False))!=now:
                    cells.append([x,y,hazard,bool(smoke)])
                previous[key]=now
            if cells:updates.append({'t':observation['t'],'cells':cells,'sector':observation['sector']})
        visible['knowledge_events']=updates
        # Keep complete audit only in server-side TXT, cap dense playback data.
        events=[e for e in run.get('audit',[]) if e.get('type') not in ('SECTOR_SCANNED','MESSAGE_SENT','MESSAGE_DELIVERED')]
        visible['audit']=events[:2500] if len(events)<2500 else events[::max(1,len(events)//2500)][:2500]
        visible['messages']=[]
        public_runs.append(visible)
    out['runs']=public_runs
    return out

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(STATIC),**kwargs)
    def log_message(self,fmt,*args):
        if not str(args[1] if len(args)>1 else '').startswith('200'):super().log_message(fmt,*args)
    def do_POST(self):
        path=urllib.parse.urlparse(self.path)
        if path.path!='/api/runs':return self.json_response({'error':'Неизвестный API-метод'},404)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<1 or size>120000:raise ValueError('Неверный размер запроса')
            raw=self.rfile.read(size)
            body=json.loads(raw)
            if not isinstance(body,dict):raise ValueError('Нужны настройки JSON')
            args=params({k:[str(v)] for k,v in body.items()})
            uid=RUN_MANAGER.start(args,run_collection)
            return self.json_response({'run_id':uid,'status':'QUEUED'},202)
        except (ValueError,TypeError,json.JSONDecodeError) as exc:
            return self.json_response({'error':str(exc)},400)
    def do_GET(self):
        path=urllib.parse.urlparse(self.path)
        if path.path=='/api/health':
            return self.json_response({'ok':True,'name':'MetaRescue Benchmark','version':'0.5.2',
                'ai_connected':bool(os.environ.get('DEEPSEEK_API_KEY')),
                'model':os.environ.get('DEEPSEEK_MODEL','deepseek-flash')})
        if path.path in ('/api/runs/status','/api/runs/result','/api/logs'):
            query=urllib.parse.parse_qs(path.query)
            uid=query.get('run_id',[''])[0]
            status=RUN_MANAGER.status(uid)
            if not status:return self.json_response({'error':'Запуск не найден'},404)
            if path.path=='/api/runs/status':return self.json_response(status)
            data=RUN_MANAGER.result(uid)
            if data is None:return self.json_response({'error':'Результаты ещё не готовы','status':status['status']},409)
            if path.path=='/api/logs':return self.stream_logs(data)
            return self.json_response(public_projection(data))
        if path.path=='/api/simulation':
            return self.json_response({'error':'Расчёт выполняется только через кнопку Старт (POST /api/runs).'},405)
        if path.path in ('/','/index.html','/scout','/rescue','/mission'):
            self.path='/index.html';return super().do_GET()
        return super().do_GET()
    def json_response(self,data,status=200):
        raw=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
        use_gzip='gzip' in self.headers.get('Accept-Encoding','') and len(raw)>15_000
        if use_gzip:raw=gzip.compress(raw,compresslevel=4)
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        if use_gzip:self.send_header('Content-Encoding','gzip')
        self.send_header('Content-Length',str(len(raw)))
        self.end_headers();self.wfile.write(raw)
    def stream_logs(self,data):
        sc=data['scenario'];name=f'metarescue_v052_full_audit_{sc["width"]}x{sc["height"]}_seed{sc["seed"]}.txt'
        self.send_response(200)
        self.send_header('Content-Type','text/plain; charset=utf-8')
        self.send_header('Content-Disposition',f'attachment; filename="{name}"')
        self.send_header('Cache-Control','no-store')
        self.send_header('Connection','close')
        self.end_headers()
        try:
            for chunk in log_chunks(data):self.wfile.write(chunk)
            self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError):pass
        self.close_connection=True

class ThreadingHTTPServer(socketserver.ThreadingMixIn,http.server.HTTPServer):
    daemon_threads=True;allow_reuse_address=True

def start(open_browser=True):
    server=None
    for port in [8765,8766,8770,0]:
        try:server=ThreadingHTTPServer(('127.0.0.1',port),Handler);break
        except OSError:continue
    if server is None:raise RuntimeError('Не удалось открыть локальный порт')
    url=f'http://127.0.0.1:{server.server_port}/'
    print('\nMetaRescue Benchmark v0.5.2 — '+url)
    print('DeepSeek: '+('ключ настроен' if os.environ.get('DEEPSEEK_API_KEY') else 'ключ отсутствует; live будет использовать безопасный fallback'))
    if open_browser:threading.Timer(1.,lambda:webbrowser.open(url)).start()
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:server.server_close()
