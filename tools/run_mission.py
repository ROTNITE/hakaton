"""Run separate native environment and public-HTTP controller processes.

Development runner. The packaged application and full Unreal setup UI have their
own acceptance gates. Failed/incomplete runs are retained under unique IDs.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from contracts.protocol import strict_json,ProtocolError
from controller.ai import file_lock,AIError
from controller.baselines import BASELINES
from controller.client import EnvironmentClient
from controller.policy import PAIRS
from environment.config import Settings
from environment.disturbances import validate_tape as validate_disturbances
from environment.events import validate_tape
from environment.layout import generate,public_map
from environment.main import DEFAULT_OUTPUT,PACKAGED_GAME,existing_unreal,native_command
from tools.native_archive import file_sha256,verify_archive
from tools.native_process import AttachedNative


CONTROLLER_CLOSE_GRACE_S=30


def hashes(layout):
    files=[layout,Path(__file__),ROOT/'tools/native_archive.py',ROOT/'unreal/MetaRescue/Binaries/Win64/UnrealEditor-MetaRescue.dll']
    if PACKAGED_GAME.is_file():
        files.extend(p for p in PACKAGED_GAME.parents[3].rglob('*')
                     if p.suffix in ('.exe','.dll','.pak','.ucas','.utoc') and p.is_file())
    for directory in ('controller','contracts','environment','unreal/MetaRescue/Source','unreal/MetaRescue/Config'):
        files.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and p.suffix in ('.py','.cpp','.h','.cs','.ini'))
    content=ROOT/'unreal/MetaRescue/Content'
    files.extend((content/'RescueAssets/UIV1').glob('*.uasset'))
    files.extend((content/'Scenario').glob('*.json'))
    files.append(content/'Maps/RescueQuarter.umap')
    world=strict_json(layout.read_bytes(),maximum_bytes=64*1024*1024)
    if world.get('competition'):
        files.extend((content/'RescueAssets/Competition').glob('*.uasset'))
    if world.get('format') in ('rescue-city-2.1','rescue-city-2.2'):
        files.extend((content/'RescueAssets/CityV2').rglob('*.uasset'))
    return {str(p.resolve()):file_sha256(p) for p in files if p.is_file()}


def save_manifest(output,manifest):
    temporary=output/'manifest.json.tmp'
    temporary.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,output/'manifest.json')


def run(args):
    rescue_initializer=getattr(args,'rescue_initializer','heuristic')
    if rescue_initializer not in ('heuristic','assignment'):raise ValueError('Unknown rescue initializer')
    if rescue_initializer!='heuristic' and (args.policy not in PAIRS or PAIRS[args.policy][1]!='nsga2'):
        raise ValueError('Assignment initialization requires NSGA-II rescue')
    attached=getattr(args,'attach_native_pid',None)
    running=existing_unreal()
    if attached:
        if len(running)!=1 or int(running[0]['pid'])!=attached:
            raise RuntimeError('Product attachment requires exactly the declared native process')
        if args.build:raise ValueError('Cannot build while attached to native')
    elif running:raise RuntimeError('Another Unreal is running; finish it before starting a mission')
    name=args.name or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    if not name or Path(name).name!=name or name in ('.','..') or ':' in name or '\\' in name or '/' in name:
        raise ValueError('Run name must be one directory name')
    output=DEFAULT_OUTPUT/'missions'/name;output.mkdir(parents=True,exist_ok=False)
    native_output=output/'environment';native_output.mkdir()
    run_id=uuid.uuid4().hex
    manifest={'format':'metarescue.mission-run.v1','state':'incomplete','name':name,'run_id':run_id,'ai_mode':args.ai_mode,
              'ai_scope':args.ai_scope if args.ai_mode!='OFF' else None,
              'contest_coordination':args.contest_coordination,
              'rescue_initializer':rescue_initializer,
              'policy':args.policy,'rendering':'null_rhi' if args.headless else 'visible' if args.visible else 'offscreen',
              'native_pid':None,'controller_pid':None,'started_utc':datetime.now(timezone.utc).isoformat()}
    save_manifest(output,manifest)
    native=controller=None;before=None;client=EnvironmentClient('http://127.0.0.1:'+str(args.port),timeout_s=3)
    startup=None
    if os.name=='nt' and not args.visible:
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
    try:
        layout=args.layout.resolve(strict=True) if args.layout else output/'world.private.json'
        if not args.layout:
            parameters=strict_json(args.config.read_bytes()) if args.config else {}
            if args.seed is not None:parameters['seed']=args.seed
            settings=Settings.parse(parameters);args.seed=settings.seed
            world=generate(settings,include_events=True)
            layout.write_text(json.dumps(world,ensure_ascii=False,indent=2),encoding='utf-8')
            (output/'world.public.json').write_text(json.dumps(public_map(world),ensure_ascii=False,indent=2),encoding='utf-8')
        else:
            private_bytes=layout.read_bytes();world=strict_json(private_bytes,maximum_bytes=64*1024*1024)
            layout_seed=world['settings']['seed']
            if 'event_model' in world:validate_tape(world['event_model'],world)
            if 'disturbances' in world:validate_disturbances(world['disturbances'],world)
            if args.seed is not None and args.seed!=layout_seed:raise ValueError('--seed conflicts with immutable layout seed')
            args.seed=layout_seed
            manifest['source_layout']={'path':str(layout),'sha256':hashlib.sha256(private_bytes).hexdigest()}
            layout=output/'world.private.json';layout.write_bytes(private_bytes)
            (output/'world.public.json').write_text(json.dumps(public_map(world),ensure_ascii=False,indent=2),encoding='utf-8')
        if world.get('format') in ('rescue-city-2.1','rescue-city-2.2'):
            revision=world.get('vegetation_revision',1)
            name=f'city-vegetation-v2-r{revision}.json' if revision>1 else 'city-vegetation-v2.json'
            vegetation=ROOT/'unreal/MetaRescue/Content/Scenario'/name
            if file_sha256(vegetation)!=world['vegetation_manifest_sha256']:
                raise ValueError('CityV2 vegetation manifest differs from the generated layout')
            if world['format']=='rescue-city-2.2' and file_sha256(vegetation.with_name('city-props-v1.json'))!=world['city_props_manifest_sha256']:
                raise ValueError('CityV2 prop manifest differs from the generated layout')
        if args.build:
            with (output/'build.log').open('w',encoding='utf-8') as log:
                subprocess.run([sys.executable,'-B','-X','utf8','unreal/launch.py','--quarter','--build'],
                               cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        before=hashes(layout);manifest['frozen_inputs']=before;manifest['layout']=str(layout)
        command=None if attached else native_command(layout=layout,port=args.port,output=native_output,visible=args.visible,headless=args.headless,
                               realtime=args.realtime or args.ai_mode=='LIVE',exit_on_close=True)
        if getattr(args,'capture_overview',False):
            if attached or args.headless:raise ValueError('Overview recording needs a standalone rendered mission')
            command.append('-MRCoreCaptureOverview')
            if args.capture_base_at is not None:
                command.append('-MRCoreCaptureBaseAt='+str(args.capture_base_at))
        manifest['native_command']=command
        if attached:manifest['attached_native_pid']=attached
        save_manifest(output,manifest)
        with (native_output/'stdout.log').open('w',encoding='utf-8') as native_log, (output/'controller-stdout.log').open('w',encoding='utf-8') as control_log:
            child_env={**os.environ,'METARESCUE_OUTPUT':str(DEFAULT_OUTPUT)}
            native=AttachedNative(attached) if attached else subprocess.Popen(
                command,cwd=ROOT,stdout=native_log,stderr=subprocess.STDOUT,startupinfo=startup,env=child_env)
            manifest['native_pid']=native.pid;save_manifest(output,manifest)
            deadline=time.monotonic()+args.ready_timeout
            while time.monotonic()<deadline:
                if native.poll() is not None:raise RuntimeError('Native exited during startup: '+str(native.returncode))
                try:
                    if client.health()['status']=='ready':
                        if attached and 'metarescue.announced_map.v1' not in client.capabilities().get('extensions',()):
                            raise RuntimeError('Unexpected native environment for product attachment')
                        break
                except (OSError,RuntimeError,ProtocolError):pass
                time.sleep(.25)
            else:raise TimeoutError('Native readiness timeout')
            if attached:
                initial=client.reset(seed=args.seed)['observation']
                announced=initial['metaevolution']['announced_map']
                expected=public_map(world)
                # Declared competition zones are carried in Observation.zones,
                # not in the optional static-map extension.
                expected.pop('declared_zones',None)
                if any(announced.get(key)!=value for key,value in expected.items()):
                    client.close(initial['episode_id'])
                    raise RuntimeError('Attached native geometry differs from the prepared world')
                manifest['attachment']={'episode_id':initial['episode_id'],'public_map_verified':True,
                    'map_sha256':hashlib.sha256(json.dumps(expected,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
            command=[sys.executable,'-B','-X','utf8','-m','controller.main',
                '--environment','http://127.0.0.1:'+str(args.port),'--health-port',str(args.health_port),
                '--policy',args.policy,'--seed',str(args.seed),'--optimizer-seed',str(args.optimizer_seed),
                '--ai-mode',args.ai_mode,'--ai-scope',args.ai_scope,'--output',str(output/'controller'),'--run-id',run_id]
            if args.ai_replay:command+=['--ai-replay',str(args.ai_replay.resolve(strict=True))]
            if args.ai_tariff:command+=['--ai-tariff',str(args.ai_tariff.resolve(strict=True))]
            if args.contest_coordination:command.append('--contest-coordination')
            if rescue_initializer!='heuristic':command+=['--rescue-initializer',rescue_initializer]
            if attached:command.append('--attach')
            for key in ('scout_population','scout_generations','rescue_population','rescue_generations'):
                if hasattr(args,key):command+=['--'+key.replace('_','-'),str(getattr(args,key))]
            if getattr(args,'control_file',None):command+=['--control-file',str(args.control_file),'--control-session',args.control_session]
            if getattr(args,'operator_file',None):command+=['--operator-file',str(args.operator_file)]
            manifest['controller_command']=command
            controller=subprocess.Popen(command,cwd=ROOT,stdout=control_log,stderr=subprocess.STDOUT,startupinfo=startup,env=child_env)
            manifest['controller_pid']=controller.pid;save_manifest(output,manifest)
            print(json.dumps({'run':str(output),'native_pid':native.pid,'controller_pid':controller.pid}),flush=True)
            began=time.monotonic();last=-10
            while controller.poll() is None:
                elapsed=time.monotonic()-began
                if args.wall_timeout and elapsed>=args.wall_timeout:raise TimeoutError('Mission wall timeout')
                native_code=native.poll()
                if native_code is not None:
                    manifest['native_exit_code']=native_code
                    if attached or native_code!=0:raise RuntimeError('Native exited before controller: '+str(native_code))
                    # The standalone server can exit after /close while the controller seals its journal.
                    remaining=began+args.wall_timeout-time.monotonic() if args.wall_timeout else CONTROLLER_CLOSE_GRACE_S
                    if remaining<=0:raise TimeoutError('Mission wall timeout')
                    try:controller.wait(timeout=min(remaining,CONTROLLER_CLOSE_GRACE_S))
                    except subprocess.TimeoutExpired as error:
                        if args.wall_timeout and remaining<=CONTROLLER_CLOSE_GRACE_S:
                            raise TimeoutError('Mission wall timeout while finalizing controller') from error
                        raise TimeoutError('Controller did not finalize after native exit') from error
                    break
                if elapsed-last>=5:
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:'+str(args.health_port)+'/v1/controller/health',timeout=1) as response:
                            health=strict_json(response.read(65536))
                        manifest['last_controller_health']=health
                        print(json.dumps({'wall_s':round(elapsed,1),'model_s':health.get('time'),
                                          'status':health.get('episode_status',health['status'])}),flush=True)
                    except OSError:pass
                    last=elapsed
                time.sleep(.2)
            manifest['controller_exit_code']=controller.returncode
            if controller.returncode:raise RuntimeError('Controller failed: '+str(controller.returncode))
            if attached:
                native_code=native.poll()
                if native_code is not None:
                    manifest['native_exit_code']=native_code
                    raise RuntimeError('Attached native exited during controller finalization: '+str(native_code))
            else:
                manifest['native_exit_code']=native.wait(timeout=30)
                if native.returncode:raise RuntimeError('Native failed: '+str(native.returncode))
        controller_output=output/'controller'
        result=json.loads((controller_output/'manifest.json').read_text(encoding='utf-8'))
        if result['state']!='complete' or result['run_id']!=run_id:
            raise ValueError('Controller archive does not describe a complete current run')
        if result['journal']!='controller.jsonl.gz' or file_sha256(controller_output/result['journal'])!=result['journal_sha256']:
            raise ValueError('Controller journal SHA-256 mismatch')
        episode_id=result['episode_id']
        if not re.fullmatch('[0-9A-Fa-f]{32}',episode_id):raise ValueError('Native archive ID is not a generated UUID')
        native_archive=DEFAULT_OUTPUT/'core-runs'/episode_id
        verification=verify_archive(native_archive)
        if verification['episode_id']!=episode_id:raise ValueError('Native/controller episode IDs differ')
        if verification['status']!=result['episode_status']:raise ValueError('Native/controller terminal statuses differ')
        (output/'native-archive-verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
        manifest['native_archive']=str(native_archive.resolve())
        manifest.update(state='complete',episode_status=result['episode_status'],metrics=result['metrics'])
    except BaseException as error:
        manifest.update(state='failed',error_type=type(error).__name__,error=str(error))
        raise
    finally:
        if controller is not None and controller.poll() is None:
            controller.terminate();controller.wait(timeout=30);manifest['forced_controller_cleanup']=True
        if native is not None and not attached and native.poll() is None:
            try:
                observation=client.observation();client.close(observation['episode_id']);native.wait(timeout=10)
            except (OSError,RuntimeError,ProtocolError,subprocess.TimeoutExpired):
                if native.poll() is None:native.terminate();native.wait(timeout=30);manifest['forced_native_cleanup']=True
        if attached and native is not None:native.close()
        client.disconnect()
        if before is not None:
            manifest['frozen_inputs_preserved']=before==hashes(layout)
            if not manifest['frozen_inputs_preserved']:manifest['state']='failed';manifest['error']='Frozen inputs changed'
        manifest['ended_utc']=datetime.now(timezone.utc).isoformat();save_manifest(output,manifest)
        print(json.dumps({'run':str(output),'state':manifest['state'],'episode_status':manifest.get('episode_status'),
                          'metrics':manifest.get('metrics')}),flush=True)
    return 0 if manifest['state']=='complete' else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group();group.add_argument('--layout',type=Path);group.add_argument('--config',type=Path)
    parser.add_argument('--name');parser.add_argument('--seed',type=int)
    parser.add_argument('--optimizer-seed',type=int,default=2026)
    parser.add_argument('--scout-population',type=int,default=40)
    parser.add_argument('--scout-generations',type=int,default=32)
    parser.add_argument('--rescue-population',type=int,default=26)
    parser.add_argument('--rescue-generations',type=int,default=17)
    parser.add_argument('--rescue-initializer',choices=('heuristic','assignment'),default='heuristic')
    parser.add_argument('--policy',choices=[*BASELINES,*PAIRS],default='nsga2_nsga2')
    parser.add_argument('--ai-mode',choices=['OFF','MOCK','LIVE','REPLAY'],default='OFF')
    parser.add_argument('--ai-scope',choices=['global','global_local'],default='global_local')
    parser.add_argument('--contest-coordination',action='store_true')
    parser.add_argument('--ai-replay',type=Path);parser.add_argument('--port',type=int,default=8130)
    parser.add_argument('--ai-tariff',type=Path,help='Verified immutable API pricing snapshot')
    parser.add_argument('--health-port',type=int,default=8131)
    rendering=parser.add_mutually_exclusive_group();rendering.add_argument('--visible',action='store_true')
    rendering.add_argument('--headless',action='store_true',help='Run native physics without GPU rendering')
    parser.add_argument('--capture-overview',action='store_true',help='Record one native overhead image per external step')
    parser.add_argument('--capture-base-at',type=float,help='Switch the recording to the base view at this model second')
    parser.add_argument('--realtime',action='store_true');parser.add_argument('--build',action='store_true')
    parser.add_argument('--ready-timeout',type=float,default=600);parser.add_argument('--wall-timeout',type=float,default=0)
    parser.add_argument('--control-file',type=Path);parser.add_argument('--control-session')
    parser.add_argument('--operator-file',type=Path,help='Episode-bound local human requirements through Core issue_directive')
    args=parser.parse_args()
    if args.capture_base_at is not None and (not args.capture_overview or not 0<=args.capture_base_at<=86400):
        parser.error('--capture-base-at requires overview recording and a model second in 0..86400')
    if args.ai_mode!='OFF' and args.policy in BASELINES:parser.error('Control specimens run with AI OFF')
    if args.contest_coordination and args.policy in BASELINES:parser.error('Control specimens have fixed coordination')
    if args.ai_mode=='REPLAY' and not args.ai_replay:parser.error('REPLAY requires --ai-replay')
    if bool(args.control_file)!=bool(args.control_session):parser.error('Operator gate requires both file and session')
    if not 1024<=args.port<=65535 or not 1024<=args.health_port<=65535 or args.port==args.health_port:parser.error('Invalid/conflicting ports')
    if args.ready_timeout<=0 or args.wall_timeout<0:parser.error('Timeouts must be positive (wall=0 disables limit)')
    try:
        with file_lock(DEFAULT_OUTPUT/'locks/unreal-owner.lock'):return run(args)
    except AIError as error:raise RuntimeError('Another mission runner owns the Unreal lock') from error


if __name__=='__main__':raise SystemExit(main())
