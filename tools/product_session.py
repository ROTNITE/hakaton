"""Prepare a native UI request or attach its separate HTTP controller. No Unreal spawn."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr,redirect_stdout
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from contracts.protocol import strict_json
from controller.ai import atomic_json,file_lock,load_key,LiveBudget
from controller.baselines import BASELINES
from controller.operational import FORMAT
from controller.policy import PAIRS
from environment.config import Settings
from environment.layout import generate,public_map
from environment.main import DEFAULT_OUTPUT,existing_unreal
from tools.native_archive import file_sha256
from tools.run_mission import run as run_mission


REQUEST_FORMAT='metarescue.product-request.v1'
SESSION_FORMAT='metarescue.product-session.v1'
CONTROLLER_DEFAULTS={'policy':'nsga2_nsga2','optimizer_seed':2026,'ai_mode':'OFF',
                     'ai_scope':'global_local','contest_coordination':True,'realtime':True,
                     'scout_population':40,'scout_generations':32,'rescue_population':26,'rescue_generations':17}


def parse_request(value):
    if (not isinstance(value,dict) or set(value)!={'format','settings','controller'} or value['format']!=REQUEST_FORMAT):
        raise ValueError('Invalid product request format')
    settings=Settings.parse(value['settings'])
    supplied=value['controller']
    if not isinstance(supplied,dict) or set(supplied)-set(CONTROLLER_DEFAULTS):raise ValueError('Unknown controller settings')
    options={**CONTROLLER_DEFAULTS,**supplied}
    for key in ('contest_coordination','realtime'):
        if type(options[key]) is not bool:raise ValueError(key+' must be boolean')
    if options['policy'] not in (*BASELINES,*PAIRS):raise ValueError('Unknown policy')
    if options['ai_mode'] not in ('OFF','MOCK','LIVE'):raise ValueError('Unknown interactive AI mode')
    if options['ai_scope'] not in ('global','global_local'):raise ValueError('Unknown AI scope')
    for key,low,high in (('optimizer_seed',0,999999999),('scout_population',4,256),('scout_generations',1,256),
                         ('rescue_population',4,256),('rescue_generations',1,256)):
        if type(options[key]) is not int or not low<=options[key]<=high:raise ValueError(f'{key}: integer {low}..{high}')
    if options['policy'] in BASELINES and (options['ai_mode']!='OFF' or options['contest_coordination']):
        raise ValueError('Control specimens require AI OFF and fixed coordination')
    if options['ai_mode']=='LIVE':options['realtime']=True
    return {'format':REQUEST_FORMAT,'settings':settings.json(),'controller':options}


def session_file(path):
    path=Path(path).resolve(strict=True)
    if not path.is_relative_to((DEFAULT_OUTPUT/'product-sessions').resolve()):
        raise ValueError('Product session must be under the output product-sessions directory')
    data=strict_json(path.read_bytes(),maximum_bytes=65536)
    if data.get('format')!=SESSION_FORMAT or not re.fullmatch('[0-9a-f]{32}',data.get('id','')):
        raise ValueError('Invalid product session')
    if data.get('workspace')!=str(path.parent):raise ValueError('Product workspace mismatch')
    return data


def child_path(session,value):
    path=Path(value).resolve()
    if not path.is_relative_to(Path(session['workspace'])):raise ValueError('Path escapes the product workspace')
    return path


def availability():
    try:
        configured=bool(load_key(file_path=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'MetaRescue/secrets.env'))
    except (OSError,ValueError,RuntimeError):configured=False
    budget=LiveBudget(Path(os.environ.get('METARESCUE_LIVE_BUDGET','D:/MetaRescue-output/ai-budget.json'))).snapshot()
    return {'key_configured':configured,'budget_used':budget['used'],'budget_limit':budget['limit']}


def presets():
    directory=DEFAULT_OUTPUT/'presets';directory.mkdir(exist_ok=True)
    rows=[]
    for path in directory.glob('*.json'):
        if not re.fullmatch('[0-9a-f]{32}',path.stem):continue
        try:
            item=strict_json(path.read_bytes(),maximum_bytes=65536)
            config=parse_request(item['configuration'])
            rows.append({'id':path.stem,'title':item['title'],'configuration':config})
        except (OSError,ValueError,KeyError):continue
    return sorted(rows,key=lambda row:row['title'].casefold())


def prepare(session,request):
    config=parse_request(strict_json(request.read_bytes(),maximum_bytes=65536))
    ui=availability()
    if config['controller']['ai_mode']=='LIVE':
        if not ui['key_configured']:raise ValueError('LIVE: no local DeepSeek key is configured')
        if ui['budget_used']>=ui['budget_limit']:raise ValueError('LIVE request budget is exhausted')
    world=generate(Settings.parse(config['settings']),include_events=True)
    directory=request.parent
    private=directory/'world.private.json';public=directory/'world.public.json'
    atomic_json(private,world);atomic_json(public,public_map(world))
    atomic_json(directory/'configuration.json',config)
    episode_session=uuid.uuid4().hex
    atomic_json(directory/'control.json',{'format':FORMAT,'session_id':episode_session,'revision':0,'mode':'paused','step_total':0})
    return {'state':'prepared','configuration':config,'preflight':world['preflight'],'layout':str(private),
            'layout_sha256':file_sha256(private),'control_session':episode_session,
            'run_name':'product-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'),
            'availability':ui,'format':REQUEST_FORMAT}


def attach(session,request):
    prepared=strict_json((request.parent/'result.json').read_bytes(),maximum_bytes=65536)
    if prepared.get('state')!='prepared':raise ValueError('World has not passed preparation')
    config=parse_request(prepared['configuration'])
    layout=child_path(session,prepared['layout']).resolve(strict=True)
    if file_sha256(layout)!=prepared['layout_sha256']:raise ValueError('Prepared layout changed')
    # The native process comes from the launcher lease, not from UI input.
    pid=session['native_pid']
    running=existing_unreal()
    if len(running)!=1 or int(running[0]['pid'])!=pid:raise RuntimeError('The leased Unreal process is unavailable')
    options=config['controller']
    args=argparse.Namespace(layout=layout,config=None,name=prepared['run_name'],seed=None,
        optimizer_seed=options['optimizer_seed'],policy=options['policy'],ai_mode=options['ai_mode'],ai_scope=options['ai_scope'],
        contest_coordination=options['contest_coordination'],ai_replay=None,ai_tariff=None,
        port=session['port'],health_port=session['health_port'],visible=True,headless=False,
        realtime=options['realtime'],build=False,ready_timeout=120,wall_timeout=0,attach_native_pid=pid,
        control_file=request.parent/'control.json',control_session=prepared['control_session'],
        operator_file=request.parent/'operator-input.json',
        **{key:options[key] for key in ('scout_population','scout_generations','rescue_population','rescue_generations')})
    with file_lock(DEFAULT_OUTPUT/'locks'/f'product-controller-{pid}.lock'):
        return run_mission(args)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('inspect','prepare','attach','save-preset'))
    parser.add_argument('--session',type=Path,required=True)
    parser.add_argument('--request',type=Path)
    args=parser.parse_args()
    session=session_file(args.session)
    request=child_path(session,args.request) if args.request else Path(session['workspace'])/'inspect.json'
    request.parent.mkdir(parents=True,exist_ok=True)
    output=request.parent/('attach-result.json' if args.operation=='attach' else 'result.json')
    with (request.parent/(args.operation+'.log')).open('w',encoding='utf-8') as log,redirect_stdout(log),redirect_stderr(log):
        try:
            if args.operation=='inspect':result={'state':'ready','presets':presets(),'availability':availability()}
            elif args.operation=='prepare':result=prepare(session,request)
            elif args.operation=='save-preset':
                body=strict_json(request.read_bytes(),maximum_bytes=65536)
                title=body['title']
                if not isinstance(title,str) or not 1<=len(title.strip())<=64:raise ValueError('Preset title must have 1..64 characters')
                title=title.strip()
                config=parse_request(body['configuration'])
                identifier=uuid.uuid4().hex
                (DEFAULT_OUTPUT/'presets').mkdir(exist_ok=True)
                atomic_json(DEFAULT_OUTPUT/'presets'/(identifier+'.json'),{'title':title,'configuration':config})
                result={'state':'saved','id':identifier,'presets':presets()}
            else:
                code=attach(session,request)
                result={'state':'complete' if code==0 else 'failed','exit_code':code}
            atomic_json(output,result)
            return 0 if result['state']!='failed' else 1
        except Exception as error:
            import traceback
            traceback.print_exc()
            atomic_json(output,{'state':'failed','error_type':type(error).__name__,'error':str(error),
                                'details':getattr(error,'details',None)})
            return 1


if __name__=='__main__':raise SystemExit(main())
