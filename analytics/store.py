"""Bounded indexed access to immutable native and controller evidence."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime,timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import zlib

from tools.native_archive import IndexedRecords,file_sha256,verify_archive
from analytics.metrics import VERSION,outcome_metrics


IDENTIFIER=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,180}\Z')
SCHEMA='metarescue.analytics-index.v3'
MOBILE_KINDS={'aerial','ground','underground','surface_water','underwater'}
DEFAULT_BOUNDS={'min':[0,0],'max':[250,250]}
TIMELINE_KINDS={'public':'observation','truth':'truth_snapshot'}


class Heatmap:
    def __init__(self,bounds,*,truth):
        self.low,self.high=bounds['min'][:2],bounds['max'][:2]
        self.columns,self.rows=(math.ceil((hi-lo)/10) for lo,hi in zip(self.low,self.high))
        if not 0<self.columns<=150 or not 0<self.rows<=150:raise ValueError('Invalid heatmap bounds')
        self.truth=truth
        self.cells={};self.seen={};self.records=0

    def add(self,agents,time):
        self.records+=1
        for agent in agents:
            position=agent.get('position')
            if agent.get('kind') not in MOBILE_KINDS or not position:continue
            if not all(lo<=value<=hi for lo,value,hi in zip(self.low,position,self.high)):continue
            if not self.truth:
                stamp=agent.get('freshness',{}).get('position',{}).get('observed_at',time)
                if type(stamp) not in (int,float) or stamp<=self.seen.get(agent['id'],-1):continue
                self.seen[agent['id']]=stamp
            x=min(self.columns-1,math.floor((position[0]-self.low[0])/10))
            y=min(self.rows-1,math.floor((position[1]-self.low[1])/10))
            cell=self.cells.setdefault((x,y),[0,0,0]);cell[0]+=1
            link=agent.get('communication',{});quality=link.get('quality')
            if link.get('reachable') is False or type(quality) in (int,float) and 0<=quality<=1:
                cell[1]+=1
                cell[2]+=int(link.get('reachable') is False or quality<.5)

    def report(self):
        return {'basis':'truth' if self.truth else 'public',
                'kind':'agent_telemetry' if self.truth else 'observation',
                'source_records':self.records,'bounds':{'min':self.low,'max':self.high},'cell_m':10,
                'weak_quality_threshold':.5,'cells':[[x,y,*cell] for (x,y),cell in sorted(self.cells.items())]}


def timeline_frame(payload,time):
    agents=[]
    for agent in payload['agents']:
        actor={k:agent[k] for k in ('id','kind','position','status','role','scenario_ids','freshness') if k in agent}
        physical=agent.get('physical',{});communication=agent.get('communication',{})
        actor['physical']={k:physical[k] for k in ('remaining_wh','consumed_wh','cargo_target_id','stop_reason',
                                                    'active_command_id') if k in physical}
        actor['communication']={k:communication[k] for k in ('reachable','quality') if k in communication}
        agents.append(actor)
    targets=[{k:target[k] for k in ('id','position','status','evacuation_state','rescued','discovered') if k in target}
             for target in payload.get('targets',()) if target.get('available_at',0)<=time+1e-9]
    return {'agents':agents,'targets':targets,
            'zones':[zone for zone in payload.get('zones',()) if zone.get('type') in ('hazard','restricted','water','low_connectivity')],
            'events':payload.get('events',()),'network':payload.get('network',{})}


def safe_path(root,path):
    resolved=Path(path).resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()):raise ValueError('Evidence path is outside the configured output directory')
    return resolved


def read_json(path):
    return json.loads(path.read_bytes())


def enumerate_runs(root):
    rows=[]
    for folder,prefix,filename in (('missions','mission','manifest.json'),('core-acceptance','fixture','verification.json'),
                                   ('quarter-v3/runs','visual','city-verification.json')):
        directory=root/folder
        if not directory.is_dir():continue
        for item in directory.iterdir():
            if not item.is_dir() or not IDENTIFIER.fullmatch(item.name):continue
            manifest=item/filename
            if not manifest.is_file():continue
            try:
                data=read_json(manifest)
                if prefix=='mission':
                    native=data.get('native_archive')
                    status=data.get('episode_status',data.get('state','unknown'))
                elif prefix=='fixture':
                    archives=data.get('native_archives',())
                    native=str(root/'core-runs'/archives[-1]['episode_id']) if archives else None
                    status='fixture_passed' if data.get('passed') else 'fixture_failed'
                else:native=None;status='render_passed' if data.get('passed') else 'render_failed'
                if native:
                    path=Path(native)
                    try:native=safe_path(root,path if path.is_absolute() else root/path)
                    except (OSError,ValueError):
                        if not IDENTIFIER.fullmatch(path.name):continue
                        native=safe_path(root,root/'core-runs'/path.name)
                row={'id':prefix+'-'+item.name,'name':item.name,'kind':prefix,'status':status,
                     'policy':data.get('policy'),'ai_mode':data.get('ai_mode'),'ai_scope':data.get('ai_scope'),
                     'path':item.resolve(),'manifest':manifest.resolve(),'native':native,'metadata':data,
                     'updated_at':datetime.fromtimestamp(manifest.stat().st_mtime,timezone.utc).isoformat()}
                rows.append(row)
            except (OSError,ValueError,KeyError):continue
    return sorted(rows,key=lambda row:row['updated_at'],reverse=True)


def streams_for(run):
    streams=[]
    native=run['native']
    if native:
        for name in ('public','truth'):
            if (native/(name+'.index')).is_file():streams.append((name,native/name,'indexed'))
    controller=run['path']/'controller/controller.jsonl.gz'
    if controller.is_file():streams.append(('controller',controller,'gzip'))
    return streams


def stream_records(path,codec):
    if codec=='indexed':yield from IndexedRecords(path).json_records()
    else:
        with gzip.open(path,'rt',encoding='utf-8') as source:
            for line in source:
                row=json.loads(line)
                if not isinstance(row,dict):raise ValueError('Invalid controller record')
                yield row


def signature(run):
    files={'schema':SCHEMA,'metrics':VERSION,str(run['manifest']):file_sha256(run['manifest'])}
    map_path=run['path']/'world.public.json'
    if map_path.is_file():files[str(map_path)]=file_sha256(map_path)
    if run['native']:files[str(run['native']/'manifest.json')]=file_sha256(run['native']/'manifest.json')
    # Replay is integrity-checked with the other native streams, even though it
    # is not exposed as searchable records. Its change must invalidate the cache.
    if run['native']:
        for name in ('replay.index','replay.records'):
            file=run['native']/name
            files[str(file)]=[file.stat().st_size,file.stat().st_mtime_ns] if file.exists() else None
    control=run['path']/'controller/manifest.json'
    if control.is_file():files[str(control)]=file_sha256(control)
    for _,path,codec in streams_for(run):
        for file in ([path] if codec=='gzip' else [Path(str(path)+'.index'),Path(str(path)+'.records')]):
            if file.exists():files[str(file)]=[file.stat().st_size,file.stat().st_mtime_ns]
    return hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()


def visible_strings(value,*,depth=0):
    if depth>10:return
    if isinstance(value,dict):
        for key,item in value.items():
            if key in ('body','response','encoding','data','announced_map'):continue
            yield key
            yield from visible_strings(item,depth=depth+1)
    elif isinstance(value,list):
        for item in value[:128]:yield from visible_strings(item,depth=depth+1)
    elif isinstance(value,str):yield value[:4096]


def model_time(row,previous):
    value=row.get('time')
    payload=row.get('payload',{})
    if value is None:value=payload.get('time')
    if value is None and row.get('record_type')=='decision':value=payload.get('decision',{}).get('time')
    return float(value) if type(value) in (int,float) else previous


class RunStore:
    def __init__(self,root):
        self.root=Path(root).resolve();self.cache=self.root/'analytics'/SCHEMA
        self.cache.mkdir(parents=True,exist_ok=True)
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='archive-index')
        self.lock=threading.Lock();self.jobs={};self.progress={}

    def close(self):
        self.executor.shutdown(wait=True,cancel_futures=True)

    def runs(self):
        return [{key:row[key] for key in ('id','name','kind','status','policy','ai_mode','ai_scope','updated_at')} for row in enumerate_runs(self.root)]

    def locate(self,identifier):
        if not IDENTIFIER.fullmatch(identifier):raise ValueError('Invalid run identifier')
        for row in enumerate_runs(self.root):
            if row['id']==identifier:return row
        raise FileNotFoundError('Run is unavailable')

    def ensure(self,identifier):
        run=self.locate(identifier)
        if run['kind']=='visual':return {'state':'ready','visual':run['metadata']}
        stamp=signature(run);directory=self.cache/identifier
        directory.mkdir(exist_ok=True)
        report=directory/'summary.json'
        if report.is_file():
            data=read_json(report)
            if data.get('source_signature')==stamp and (directory/'records.sqlite').is_file():
                return {'state':'ready','summary':data}
        with self.lock:
            entry=self.jobs.get(identifier)
            task=entry[1] if entry else None
            if task is None or (task.done() and entry[0]!=stamp):
                task=self.executor.submit(self._build,run,stamp,directory)
                self.jobs[identifier]=(stamp,task)
            if not task.done():return {'state':'indexing','progress':self.progress.get(identifier,{})}
            try:task.result()
            except Exception as error:return {'state':'error','error':type(error).__name__+': '+str(error)}
        return {'state':'ready','summary':read_json(report)}

    def _build(self,run,stamp,directory):
        if not run['native']:raise ValueError('Native journal is unavailable for this incomplete run')
        def progress(stage,**values):
            with self.lock:self.progress[run['id']]={'stage':stage,**values}
        progress('verify')
        verified=verify_archive(run['native'])
        controller_manifest=run['path']/'controller/manifest.json'
        if controller_manifest.is_file():
            manifest=read_json(controller_manifest)
            journal=run['path']/'controller/controller.jsonl.gz'
            if manifest.get('journal_sha256') and file_sha256(journal)!=manifest['journal_sha256']:
                raise ValueError('Controller journal checksum mismatch')
        database=directory/'records.sqlite.part'
        if database.exists():database.unlink()
        sources=streams_for(run)
        counts={};last_time=0.
        map_path=run['path']/'world.public.json'
        bounds=read_json(map_path).get('bounds') if map_path.is_file() else None
        heatmaps={}
        with closing(sqlite3.connect(database)) as connection:
            connection.executescript('''
                CREATE TABLE records(
                  id INTEGER PRIMARY KEY, stream TEXT NOT NULL, ordinal INTEGER NOT NULL,
                  time REAL NOT NULL, kind TEXT NOT NULL, search_text TEXT NOT NULL,
                  payload BLOB NOT NULL, trace_id TEXT, request_id TEXT, decision_id TEXT);
                CREATE INDEX by_time ON records(time,id);
                CREATE INDEX by_stream_ordinal ON records(stream,ordinal);
                CREATE INDEX by_kind ON records(kind,time);
                CREATE INDEX by_trace ON records(trace_id);
                CREATE INDEX by_decision ON records(decision_id);
                CREATE TABLE frames(id INTEGER PRIMARY KEY, stream TEXT NOT NULL, time REAL NOT NULL, payload BLOB NOT NULL);
                CREATE INDEX frames_by_stream ON frames(stream,time,id);
                CREATE TABLE heatmaps(stream TEXT PRIMARY KEY, payload TEXT NOT NULL);
            ''')
            for name,path,codec in sources:
                counts[name]=0;last_time=0.
                for ordinal,row in enumerate(stream_records(path,codec)):
                    counts[name]+=1;last_time=model_time(row,last_time)
                    payload=row.get('payload',{})
                    kind=row.get('record_type','unknown')
                    decision=payload.get('decision',{})
                    search=' '.join(visible_strings(payload))[:65536]
                    content=zlib.compress(json.dumps(row,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode(),3)
                    entry=connection.execute('INSERT INTO records(stream,ordinal,time,kind,search_text,payload,trace_id,request_id,decision_id) VALUES(?,?,?,?,?,?,?,?,?)',
                        (name,ordinal,last_time,kind,search,content,row.get('trace_id'),
                         row.get('request_id',payload.get('request_id')),row.get('decision_id',payload.get('decision_id',decision.get('decision_id')))))
                    if kind==TIMELINE_KINDS.get(name):
                        frame=timeline_frame(payload,last_time)
                        encoded=json.dumps(frame,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
                        connection.execute('INSERT INTO frames VALUES(?,?,?,?)',(entry.lastrowid,name,last_time,zlib.compress(encoded,3)))
                    if (name,kind) in (('public','observation'),('truth','agent_telemetry')):
                        if bounds is None and name=='public':bounds=payload.get('metaevolution',{}).get('announced_map',{}).get('bounds')
                        if name not in heatmaps:heatmaps[name]=Heatmap(bounds or DEFAULT_BOUNDS,truth=name=='truth')
                        heatmaps[name].add(payload['agents'],last_time)
                    if ordinal%200==0:
                        connection.commit();progress('records',stream=name,records=dict(counts))
            for name in TIMELINE_KINDS:
                heat=heatmaps.get(name) or Heatmap(bounds or DEFAULT_BOUNDS,truth=name=='truth')
                connection.execute('INSERT INTO heatmaps VALUES(?,?)',(name,json.dumps(heat.report(),separators=(',',':'))))
            connection.commit()
        sources_by_name={name:(path,codec) for name,path,codec in sources}
        def rows(name):
            entry=sources_by_name.get(name)
            return stream_records(*entry) if entry else iter(())
        progress('metrics',records=dict(counts))
        metrics=outcome_metrics(rows('truth'),rows('public'),rows('controller'))
        report={'format':SCHEMA,'source_signature':stamp,'run_id':run['id'],'name':run['name'],
                'status':run['status'],'policy':run['policy'],'ai_mode':run['ai_mode'],'ai_scope':run['ai_scope'],
                'episode_id':verified['episode_id'],'native_status':verified['status'],'archive_verified':verified['passed'],
                'streams':counts,'metrics':metrics,'native_journal':verified,
                'layout_sha256':run['metadata'].get('source_layout',{}).get('sha256')}
        db_final=directory/'records.sqlite';database.replace(db_final)
        temporary=directory/'summary.json.part'
        temporary.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
        temporary.replace(directory/'summary.json')

    def connection(self,identifier):
        ready=self.ensure(identifier)
        if ready['state']!='ready' or 'visual' in ready:raise ValueError('The run index is not ready')
        database=(self.cache/identifier/'records.sqlite').resolve()
        connection=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)
        connection.row_factory=sqlite3.Row
        return connection

    def records(self,identifier,*,cursor=0,limit=100,stream='',kind='',query='',after=0.):
        if not 0<=cursor or not 1<=limit<=250 or len(query)>256 or not math.isfinite(after) or after<0:
            raise ValueError('Invalid record page')
        terms=['id>?','time>=?'];arguments=[cursor,after]
        for field,value in (('stream',stream),('kind',kind)):
            if value:terms.append(field+'=?');arguments.append(value)
        if query:
            terms.append("search_text LIKE ? ESCAPE '\\'")
            arguments.append('%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
        with closing(self.connection(identifier)) as connection:
            entries=connection.execute('SELECT id,stream,time,kind,payload FROM records WHERE '+' AND '.join(terms)+' ORDER BY id LIMIT ?',
                                       [*arguments,limit+1]).fetchall()
        data=[];used=0
        for row in entries[:limit]:
            raw=zlib.decompress(row['payload'])
            if data and used+len(raw)>8*1024*1024:break
            used+=len(raw)
            data.append({'id':row['id'],'stream':row['stream'],'time':row['time'],'kind':row['kind'],'record':json.loads(raw)})
        return {'records':data,'next_cursor':data[-1]['id'] if data and len(entries)>len(data) else None}

    def timeline(self,identifier,*,truth=False):
        stream='truth' if truth else 'public'
        with closing(self.connection(identifier)) as connection:
            references=connection.execute('SELECT id FROM frames WHERE stream=? ORDER BY time,id',(stream,)).fetchall()
            total=len(references)
            stride=max(1,(total+249)//250)
            chosen=references[::stride]
            if references and chosen[-1]['id']!=references[-1]['id']:chosen.append(references[-1])
            frames=[]
            for ref in chosen:
                row=connection.execute('SELECT id,time,payload FROM frames WHERE id=?',(ref['id'],)).fetchone()
                frames.append({'record_id':row['id'],'time':row['time'],**json.loads(zlib.decompress(row['payload']))})
        return {'basis':stream,'source_frames':total,'sample_stride':stride,'frames':frames}

    def heatmap(self,identifier,*,truth=False):
        stream='truth' if truth else 'public'
        with closing(self.connection(identifier)) as connection:
            row=connection.execute('SELECT payload FROM heatmaps WHERE stream=?',(stream,)).fetchone()
        return json.loads(row['payload'])

    def map(self,identifier):
        run=self.locate(identifier)
        path=run['path']/'world.public.json'
        if path.is_file():return read_json(path)
        with closing(self.connection(identifier)) as connection:
            row=connection.execute("SELECT payload FROM records WHERE stream='public' AND kind='observation' ORDER BY id LIMIT 1").fetchone()
        return json.loads(zlib.decompress(row['payload']))['payload'].get('metaevolution',{}).get('announced_map',{}) if row else {}

    def fronts(self,identifier):
        with closing(self.connection(identifier)) as connection:
            rows=connection.execute("SELECT id,time,payload FROM records WHERE stream='controller' AND kind='planning_trace' ORDER BY id").fetchall()
        records=[]
        for row in rows:
            trace=json.loads(zlib.decompress(row['payload']))['payload']
            if trace.get('type')!='planning_result_committed':continue
            result=trace['result'];plan=result['plan']
            records.append({'record_id':row['id'],'time':row['time'],'planner':trace['planner'],
                            'problem':result.get('problem'),'based_on_time':trace['based_on_time'],
                            'points':plan.get('pareto',()),'selected':plan.get('selected_objectives'),'stats':plan.get('stats')})
        return records

    def usage(self,identifier):
        directory=self.locate(identifier)['path']/'controller/api-usage'
        if not directory.is_dir():return {'available':False}
        manifest=read_json(directory/'manifest.json')
        if manifest.get('state')!='complete':raise ValueError('API usage export is incomplete')
        for name,digest in manifest.get('files',{}).items():
            file=safe_path(directory,directory/name)
            if file_sha256(file)!=digest:raise ValueError('API usage checksum mismatch: '+name)
        return {'available':True,'run':read_json(directory/'run.json'),
                'cumulative':read_json(directory/'cumulative.json'),
                'attempts':read_json(directory/'attempts.json').get('requests',[]),
                'manifest':manifest}
