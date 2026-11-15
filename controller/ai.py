"""DeepSeek transport, durable total LIVE budget, deterministic MOCK and replay.

No provider can execute a command. Callers validate proposals against the current
public state. HTTP headers and credentials never enter audit records.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import gzip
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import time
import uuid

from contracts.protocol import encode,strict_json,ProtocolError
from controller.ai_contracts import AIError,example_response
from controller.accounting import TARIFF,digest,numeric_usage,normalize_usage,estimate_cost,summarize,report_csv,report_text,validate_tariff


def utc():return datetime.now(timezone.utc).isoformat()


@contextmanager
def file_lock(path,timeout_s=3):
    """Kernel lock is released on process death; never steal a live owner's lock."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        if handle.tell()==0:handle.write(b'\0');handle.flush()
        deadline=time.monotonic()+timeout_s
        while True:
            try:
                handle.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic()>=deadline:raise AIError('AI_BUDGET_LOCK_TIMEOUT') from None
                time.sleep(.01)
        try:yield
        finally:
            handle.seek(0)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle,fcntl.LOCK_UN)


def atomic_json(path,data):
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as handle:
            handle.write(encode(data));handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()


class LiveBudget:
    def __init__(self,path,*,limit=240):
        if type(limit) is not int or not 0<=limit<=240:raise ValueError('LIVE limit must be 0..240')
        self.path=Path(path).resolve();self.limit=limit
        self.accounting_dir=self.path.parent/'api-accounting'/self.path.stem

    def _read(self):
        if not self.path.exists():return {'format':'metarescue.live-budget.v1','limit':self.limit,'used':0,'requests':[]}
        try:data=strict_json(self.path.read_bytes(),maximum_bytes=32*1024*1024)
        except (OSError,ProtocolError):raise AIError('AI_BUDGET_UNREADABLE') from None
        if (not isinstance(data,dict) or data.get('format')!='metarescue.live-budget.v1' or
            type(data.get('limit')) is not int or not 0<=data['limit']<=240 or
            type(data.get('used')) is not int or not isinstance(data.get('requests'),list) or
            not 0<=data['used']<=data['limit'] or data['used']!=len(data['requests']) or
            any(not isinstance(row,dict) or not isinstance(row.get('id'),str) for row in data['requests']) or
            len({row['id'] for row in data['requests']})!=data['used']):
            raise AIError('AI_BUDGET_CORRUPT')
        return data

    def snapshot(self):
        with file_lock(self.path.with_suffix(self.path.suffix+'.lock')):
            data=self._read()
            return {'used':data['used'],'limit':min(data['limit'],self.limit)}

    def _save(self,data):
        data['revision']=data.get('revision',0)+1
        atomic_json(self.path,data)

    def reserve(self,request,*,metadata=None):
        with file_lock(self.path.with_suffix(self.path.suffix+'.lock')):
            data=self._read();source=request.data
            if data['used']>=min(data['limit'],self.limit):
                self.accounting_dir.mkdir(parents=True,exist_ok=True)
                with (self.accounting_dir/'blocked.jsonl').open('ab') as handle:
                    handle.write(encode({'id':uuid.uuid4().hex,'request_id':source['request_id'],'episode_id':source['episode_id'],
                        'role':request.role,'utc':utc(),'reason':'AI_BUDGET_EXHAUSTED','network_sent':False,
                        'run_id':(metadata or {}).get('context',{}).get('run_id')})+b'\n')
                    handle.flush();os.fsync(handle.fileno())
                raise AIError('AI_BUDGET_EXHAUSTED')
            ticket=uuid.uuid4().hex;source=request.data
            prior=[r for r in data['requests'] if r.get('logical_request_id',r['request_id'])==source['request_id']]
            metadata=metadata or {};context={k:v for k,v in metadata.get('context',{}).items() if k in
                ('run_id','config_sha256','map_sha256','world_seed','optimizer_seed','policy','purpose')}
            data['requests'].append({'id':ticket,'logical_request_id':source['request_id'],
                'attempt':len(prior)+1,'retry_of':prior[-1]['id'] if prior else None,'backoff_s':0,
                'reserved_utc':utc(),'role':request.role,'mode':'LIVE','provider':metadata.get('provider','deepseek'),
                'requested_model':metadata.get('requested_model'),'returned_model':None,
                'context':context,'trigger':source.get('trigger'),'context_completeness':'declared_fields_only',
                'request_settings':metadata.get('request_settings',{}),'request_body_sha256':metadata.get('request_body_sha256'),
                'tariff':deepcopy(metadata.get('tariff',TARIFF)),
                'budget_before':{'used':data['used'],'limit':min(data['limit'],self.limit)},
                'budget_after_reservation':{'used':data['used']+1,'limit':min(data['limit'],self.limit)},
                'outcome':{'json_valid':None,'schema_valid':None,'controller_validated':None,
                           'controller_applied':False,'physical_application':None},
                'agent_id':source.get('agent_id'),'episode_id':source['episode_id'],
                'request_id':source['request_id'],'input_sha256':request.fingerprint,'status':'reserved'})
            data['used']+=1
            # Count before any network call, even if the process dies next.
            self._save(data)
            return ticket

    def finish(self,ticket,*,status,latency_s,usage=None,raw_usage=None,transport=None):
        with file_lock(self.path.with_suffix(self.path.suffix+'.lock')):
            data=self._read();row=next((r for r in data['requests'] if r['id']==ticket),None)
            if row is None:raise AIError('AI_BUDGET_UNKNOWN_TICKET')
            if row['status']!='reserved':raise AIError('AI_BUDGET_ALREADY_FINISHED')
            raw=numeric_usage(raw_usage if raw_usage is not None else usage)
            if raw is not None:
                raw_file=self.accounting_dir/'raw-usage'/(ticket+'.json');raw_file.parent.mkdir(parents=True,exist_ok=True)
                atomic_json(raw_file,raw)
                row['usage_raw']={'path':str(raw_file),'sha256':hashlib.sha256(raw_file.read_bytes()).hexdigest(),
                                  'completeness':'all_numeric_fields_received'}
            else:row['usage_raw']=None
            normalized=normalize_usage(raw);transport=transport or {}
            safe={k:v for k,v in transport.items() if k in ('http_status','response_received','api_response_id',
                'returned_model','error_code','json_valid','finish_reason')}
            row.update(status=status,latency_s=round(latency_s,6),finished_utc=utc(),usage=usage or {},
                       normalized_usage=normalized,**safe)
            row['outcome']['json_valid']=transport.get('json_valid')
            row['budget_at_finish']={'used':data['used'],'limit':min(data['limit'],self.limit)}
            row['cost']=estimate_cost(normalized,timestamp=row['reserved_utc'],tariff=row.get('tariff'),
                                      model=row.get('returned_model') or row.get('requested_model'))
            self._save(data)
            return deepcopy(row)

    def annotate(self,ticket,**updates):
        allowed={'schema_valid','controller_validated','controller_applied','physical_application',
                 'rejection_reason','related_command_id','application_utc','validation_utc','envelope_valid'}
        if not set(updates)<=allowed:raise ValueError('Unknown accounting outcome field')
        with file_lock(self.path.with_suffix(self.path.suffix+'.lock')):
            data=self._read();row=next((r for r in data['requests'] if r['id']==ticket),None)
            if row is None:raise AIError('AI_BUDGET_UNKNOWN_TICKET')
            outcome=row.setdefault('outcome',{});before=deepcopy(outcome);outcome.update(updates)
            if outcome!=before:self._save(data)

    def report(self,output=None,*,run_id=None,historical_tickets=()):
        with file_lock(self.path.with_suffix(self.path.suffix+'.lock')):
            data=self._read();blocked=[];path=self.accounting_dir/'blocked.jsonl'
            if path.exists():blocked=[strict_json(line) for line in path.read_bytes().splitlines()]
            source_sha256=hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path.exists() else None
        summary=summarize(data['requests'],blocked=blocked,budget={'used':data['used'],'limit':min(data['limit'],self.limit)})
        for field in ('role','requested_model','returned_model','purpose','run_id','episode_id'):
            groups={}
            for row in data['requests']:
                value=row.get('context',{}).get(field) if field in ('purpose','run_id') else row.get(field)
                groups.setdefault(str(value) if value is not None else 'unknown',[]).append(row)
            summary['by_'+field]={key:summarize(rows) for key,rows in groups.items()}
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        directory=Path(output) if output else self.accounting_dir/'summaries'/stamp
        directory.mkdir(parents=True,exist_ok=False)
        atomic_json(directory/'manifest.json',{'state':'incomplete','ledger_sha256':source_sha256,
                    'ledger_revision':data.get('revision',0),'created_utc':utc()})
        atomic_json(directory/'cumulative.json',summary)
        (directory/'attempts.csv').write_text(report_csv(data['requests']),encoding='utf-8-sig')
        (directory/'summary.txt').write_text(report_text(summary),encoding='utf-8')
        atomic_json(directory/'attempts.json',{'requests':data['requests'],'blocked':blocked})
        if run_id is not None:
            rows=[r for r in data['requests'] if r.get('context',{}).get('run_id')==run_id]
            run_summary=summarize(rows,blocked=[b for b in blocked if b.get('run_id')==run_id],budget=summary['budget'])
            atomic_json(directory/'run.json',run_summary)
            (directory/'run.csv').write_text(report_csv(rows),encoding='utf-8-sig')
            (directory/'run.txt').write_text(report_text(run_summary),encoding='utf-8')
        if historical_tickets:
            historical=[r for r in data['requests'] if r['id'] in set(historical_tickets)]
            historical_summary={**summarize(historical),'scope':'historical source calls used by replay',
                                'new_api_attempts':0,'new_api_cost':'0','zero_new_api_cost':True}
            atomic_json(directory/'historical-replay.json',historical_summary)
            (directory/'historical-replay.csv').write_text(report_csv(historical),encoding='utf-8-sig')
            (directory/'historical-replay.txt').write_text('HISTORICAL COST ONLY; no new API charge.\n'+report_text(historical_summary),encoding='utf-8')
        atomic_json(directory/'manifest.json',{'state':'complete','ledger_sha256':source_sha256,
            'ledger_revision':data.get('revision',0),'created_utc':utc(),'files':{
                p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.name!='manifest.json'}})
        self.accounting_dir.mkdir(parents=True,exist_ok=True)
        with file_lock(self.path.with_suffix(self.path.suffix+'.lock')):
            path=self.accounting_dir/'latest-summary.json';previous=strict_json(path.read_bytes()) if path.exists() else {}
            if previous.get('ledger_revision',-1)<=data.get('revision',0):
                atomic_json(path,{'directory':str(directory),'created_utc':utc(),'ledger_revision':data.get('revision',0),
                                 'ledger_sha256':source_sha256})
        return {'directory':str(directory),'summary':summary}


def load_key(*,environment_name='DEEPSEEK_API_KEY',file_path=None):
    value=os.environ.get(environment_name,'').strip()
    if value:return value
    if file_path is None:return ''
    try:lines=Path(file_path).read_text(encoding='utf-8-sig').splitlines()
    except OSError:raise AIError('AI_SECRET_FILE_UNREADABLE') from None
    for line in lines:
        if not line.strip() or line.lstrip().startswith('#'):continue
        name,separator,value=line.partition('=')
        if separator and name.strip() in (environment_name,'API'):
            result=value.strip()
            if len(result)>=2 and result[0]==result[-1] and result[0] in ('"',"'"):result=result[1:-1]
            return result
    return ''


class DeepSeek:
    mode='LIVE'
    model='deepseek-flash'

    def __init__(self,budget,*,key_file=None,key_environment='DEEPSEEK_API_KEY',
                 local_timeout_s=3,global_timeout_s=6,context=None,tariff=None):
        self.budget=budget
        self.context=deepcopy(context or {})
        self.tariff=validate_tariff(tariff or TARIFF)
        self._key=load_key(environment_name=key_environment,file_path=key_file)
        if any(ord(char)<33 or ord(char)>126 for char in self._key):raise AIError('AI_SECRET_INVALID')
        if not .5<=local_timeout_s<=30 or not .5<=global_timeout_s<=60:raise ValueError('Invalid AI timeout')
        self.timeouts={'local':local_timeout_s,'global':global_timeout_s};self.successes=0

    def status(self):
        return {'mode':self.mode,'model':self.model,'key_configured':bool(self._key),
                'api_confirmed':self.successes>0,'successful_api_responses':self.successes,
                'budget':self.budget.snapshot()}

    def body(self,request):
        instruction=(
            'You advise the global rescue coordinator. Select only a supplied eligible strategy with a measurable benefit; '
            'otherwise KEEP. Never invent targets, forecasts or routes. '
            if request.role=='global' else
            'You are the private local advisor of this one mobile agent. Select only a supplied safe candidate, '
            'or KEEP. Allowed actions: KEEP, DETOUR, HOLD, ESCALATE. For an observed blocked route, '
            'prefer a supplied verified DETOUR that preserves the cargo and task; use HOLD or ESCALATE '
            'when no such route is offered. Never invent a route or change another agent. ')
        return {'model':self.model,'thinking':{'type':'disabled'},'response_format':{'type':'json_object'},
                'temperature':.1,'max_tokens':800,
                'messages':[{'role':'system','content':instruction+
                    'Return one json object. Echo request_id, episode_id, plan_version, based_on_time and valid_until exactly. '
                    'Use this JSON shape: '+json.dumps(example_response(request),ensure_ascii=False)},
                    {'role':'user','content':request.wire.decode('utf-8')}]}

    def _post(self,body,timeout_s):
        # Fixed official HTTPS origin: no credential-bearing redirects/proxy URL.
        connection=http.client.HTTPSConnection('api.deepseek.com',timeout=timeout_s,context=ssl.create_default_context())
        try:
            connection.request('POST','/chat/completions',body=body,
                headers={'Authorization':'Bearer '+self._key,'Content-Type':'application/json'})
            response=connection.getresponse();raw=response.read(1024*1024+1)
            if len(raw)>1024*1024:raise AIError('AI_API_RESPONSE_TOO_LARGE')
            if response.status!=200:raise AIError('AI_HTTP_'+str(response.status),
                details={'http_status':response.status,'response_received':True,
                         'error_response':raw.decode('utf-8','replace').replace(self._key,'[REDACTED]')})
            return raw
        finally:connection.close()

    def complete(self,request):
        if not self._key:raise AIError('AI_KEY_MISSING')
        payload=self.body(request);body=encode(payload)
        ticket=self.budget.reserve(request,metadata={'provider':'deepseek','requested_model':self.model,
            'context':self.context,'tariff':self.tariff,'request_body_sha256':hashlib.sha256(body).hexdigest(),
            'request_settings':{'max_tokens':payload['max_tokens'],'thinking':payload['thinking'],
                'response_format':payload['response_format'],'temperature':payload['temperature'],
                'cache_mode':'provider_automatic','stream':False,'template_version':'rescue-advisor.1.1'}})
        began=time.perf_counter();status='error';usage={};raw=None;usage_raw=None;result=None
        transport={'http_status':None,'response_received':False,'json_valid':None,'error_code':None}
        try:
            raw=self._post(body,self.timeouts[request.role]);data=strict_json(raw,maximum_bytes=1024*1024)
            transport.update(http_status=200,response_received=True,api_response_id=data.get('id'),returned_model=data.get('model'))
            usage_raw=numeric_usage(data.get('usage'))
            usage={key:value for key,value in (usage_raw or {}).items()
                   if key in ('prompt_tokens','completion_tokens','total_tokens') and type(value) is int}
            choice=data['choices'][0]
            transport['finish_reason']=choice['finish_reason']
            if choice['finish_reason']!='stop':raise AIError('AI_INCOMPLETE_OUTPUT')
            content=choice['message']['content']
            if not isinstance(content,str) or not content.strip():raise AIError('AI_EMPTY_OUTPUT')
            proposal=strict_json(content,maximum_bytes=32*1024)
            transport['json_valid']=True
            if not isinstance(proposal,dict):raise AIError('AI_OUTPUT_NOT_OBJECT')
            self.successes+=1;status='api_success'
            result={'mode':self.mode,'model':data.get('model',self.model),'proposal':proposal,
                    'latency_s':time.perf_counter()-began,'usage':usage,'budget_ticket':ticket,
                    'api_request_id':data.get('id'),'input_sha256':request.fingerprint,
                    'response_content':content}
            return result
        except AIError as error:
            if raw is not None and not error.details:
                error.details={'raw_api_response':raw.decode('utf-8','replace').replace(self._key,'[REDACTED]')}
            transport.update(error_code=str(error),http_status=error.details.get('http_status',transport['http_status']),
                             response_received=error.details.get('response_received',raw is not None))
            error.details['budget_ticket']=ticket
            raise
        except (TimeoutError,socket.timeout):
            transport['error_code']='AI_TIMEOUT'
            raise AIError('AI_TIMEOUT',details={'budget_ticket':ticket}) from None
        except (OSError,http.client.HTTPException):
            transport['error_code']='AI_TRANSPORT_ERROR'
            raise AIError('AI_TRANSPORT_ERROR',details={'budget_ticket':ticket}) from None
        except (ProtocolError,KeyError,IndexError,TypeError,AttributeError):
            transport.update(error_code='AI_API_RESPONSE_INVALID',http_status=200 if raw is not None else None,
                             response_received=raw is not None,json_valid=False)
            raise AIError('AI_API_RESPONSE_INVALID',details={'budget_ticket':ticket,
                'raw_api_response':raw.decode('utf-8','replace').replace(self._key,'[REDACTED]') if raw else None}) from None
        finally:
            row=self.budget.finish(ticket,status=status,latency_s=time.perf_counter()-began,usage=usage,
                                   raw_usage=usage_raw,transport=transport)
            if result is not None:result['accounting']={k:row.get(k) for k in ('normalized_usage','cost','usage_raw','http_status','budget_before','budget_after_reservation')}

    def record_outcome(self,ticket,**values):self.budget.annotate(ticket,**values)


class Mock:
    mode='MOCK'
    def status(self):return {'mode':self.mode,'key_configured':False,'api_confirmed':False}
    def complete(self,request):
        candidates=request.data['candidates'];selected=None
        if request.role=='global':
            selected=max((c for c in candidates if c.get('eligible')),key=lambda c:c.get('utility',0),default=None)
            action='SELECT'
        else:
            selected=next((c for c in candidates if c['action']=='DETOUR'),None)
            if selected is None:selected=next((c for c in candidates if c['action']=='ESCALATE'),None)
            action=selected['action'] if selected else 'KEEP'
        proposal=example_response(request,action if selected else 'KEEP',selected['id'] if selected else None)
        return {'mode':self.mode,'proposal':proposal,'latency_s':0.,'usage':{},
                'input_sha256':request.fingerprint,'response_content':encode(proposal).decode('utf-8')}


class Off:
    mode='OFF'
    def status(self):return {'mode':self.mode,'key_configured':False,'api_confirmed':False}
    def complete(self,request):raise AIError('AI_OFF')


def replay_key(request):
    data=request.data
    # Request/episode IDs are different on replay; all semantic state remains exact.
    for key in ('request_id','episode_id'):data.pop(key)
    for agent in data.get('knowledge',{}).get('agents',[]):agent.get('physical',{}).pop('active_command_id',None)
    if 'agent' in data:data['agent'].get('physical',{}).pop('active_command_id',None)
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()


class Replay:
    mode='REPLAY'
    def __init__(self,records):
        self.records={}
        for record in records:
            key=record['replay_key']
            if key in self.records:raise AIError('AI_REPLAY_DUPLICATE_KEY')
            self.records[key]=record
    def status(self):return {'mode':self.mode,'key_configured':False,'api_confirmed':False,'records':len(self.records)}
    def complete(self,request):
        record=self.records.get(replay_key(request))
        if record is None:raise AIError('AI_REPLAY_MISS')
        # Scheduler uses this recorded model-time delay. No controller-thread sleep.
        source=record.get('result') or {'replay_error':record['error']}
        proposal=dict(source['proposal']) if source.get('proposal') is not None else None
        current=request.data
        if proposal is not None:
            for key in ('request_id','episode_id'):proposal[key]=current[key]
        return {**source,'mode':self.mode,'proposal':proposal,'input_sha256':request.fingerprint,
                'recorded_delay_model_s':record['delay_model_s']}


def load_replay(path):
    path=Path(path);opener=gzip.open if path.suffix=='.gz' else open
    records=[]
    with opener(path,'rt',encoding='utf-8') as handle:
        for line in handle:
            if len(line)>2*1024*1024:raise AIError('AI_REPLAY_RECORD_TOO_LARGE')
            row=strict_json(line,maximum_bytes=2*1024*1024)
            if row.get('record_type')=='planning_trace':row=row['payload']
            if row.get('type') not in ('ai_response','ai_error'):continue
            records.append({'replay_key':row['replay_key'],'delay_model_s':row['delay_model_s'],
                            **({'result':row['result']} if row.get('result') else {'error':row['reason']})})
            if len(records)>5000:raise AIError('AI_REPLAY_TOO_MANY_RECORDS')
    if not records:raise AIError('AI_REPLAY_EMPTY')
    return Replay(records)
