"""Prepare an isolated UE filming runtime, build and capture under the common lock."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

FORMAT = 'metarescue.film.v1'


def read_plan(path):
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'),
                       parse_constant=lambda s: (_ for _ in ()).throw(ValueError('Nonfinite JSON: '+s)))
    if value.get('format') != FORMAT or type(value.get('fps')) is not int or value['fps'] != 30:
        raise ValueError('Expected metarescue.film.v1 at 30 fps')
    warmup = value.get('warmup_frames')
    if type(warmup) is not int or not 0 <= warmup <= 3600:
        raise ValueError('warmup_frames must be 0..3600')
    if type(value.get('exit_on_finish',True)) is not bool:
        raise ValueError('exit_on_finish must be boolean')
    shots = value.get('shots')
    if not isinstance(shots, list) or not 1 <= len(shots) <= 100:
        raise ValueError('shots must contain 1..100 entries')
    seen = set()
    total = 0
    for shot in shots:
        name = shot.get('id')
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name) or name.casefold() in seen:
            raise ValueError('Shot IDs must be unique portable directory names')
        seen.add(name.casefold())
        frames, wait = shot.get('frames'), shot.get('wait_frames',0)
        if type(frames) is not int or not 2 <= frames <= 18000 or type(wait) is not int or not 0 <= wait <= 54000:
            raise ValueError('Invalid shot frame count/wait')
        total += frames+wait
        until=shot.get('wait_until_s',0)
        if type(until) not in (int,float) or not math.isfinite(until) or not 0 <= until <= 3600:
            raise ValueError('wait_until_s must be 0..3600')
        delivered=shot.get('wait_for_delivered',0)
        if type(delivered) is not int or not 0<=delivered<=600:
            raise ValueError('wait_for_delivered must be 0..600')
        if shot.get('follow_space','world') not in ('world','heading'):
            raise ValueError('follow_space must be world or heading')
        if not isinstance(shot.get('follow',''),str):
            raise ValueError('follow must be an exact native agent ID')
        if type(shot.get('collision_test',False)) is not bool:
            raise ValueError('collision_test must be boolean')
        keys = shot.get('keys')
        if not isinstance(keys,list) or not 2 <= len(keys) <= 64:
            raise ValueError('Each shot requires 2..64 keys')
        previous = -1
        for key in keys:
            u, fov = key.get('u'), key.get('fov')
            if not all(type(x) in (int,float) and math.isfinite(x) for x in (u,fov)) or not previous < u <= 1 or not 15 <= fov <= 100:
                raise ValueError('Invalid key time/FOV')
            previous = u
            for component in ('eye_cm','look_cm'):
                vec=key.get(component)
                if not isinstance(vec,list) or len(vec)!=3 or not all(type(x) in (int,float) and math.isfinite(x) and abs(x)<=2_000_000 for x in vec):
                    raise ValueError('Invalid camera vector')
            if math.dist(key['eye_cm'],key['look_cm']) <= 1:
                raise ValueError('Eye and look point coincide')
        if keys[0]['u'] != 0 or keys[-1]['u'] != 1:
            raise ValueError('Keys must cover u=0..1')
    if total>108000:
        raise ValueError('Plan exceeds one hour of model time')
    return value


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def prepare(repo, destination, additions):
    project = repo/'unreal/MetaRescue'
    destination.mkdir(parents=True,exist_ok=False)
    def source_files():
        return [project/'MetaRescue.uproject']+[p for sub in ('Source','Config','Content') for p in (project/sub).rglob('*') if p.is_file()]
    before={str(p.relative_to(project)):digest(p) for p in source_files()}
    for name in ('Source','Config','Content'):
        shutil.copytree(project/name,destination/name)
    shutil.copy2(project/'MetaRescue.uproject',destination/'MetaRescue.uproject')
    for name in ('MRFilmSubsystem.h','MRFilmSubsystem.cpp'):
        target=destination/'Source/MetaRescue'/name
        if target.exists():
            if digest(target)!=digest(additions/name):
                raise ValueError('Snapshot and filming additions disagree: '+name)
        else:
            shutil.copy2(additions/name,target)
    for relative, checksum in before.items():
        if digest(project/relative)!=checksum or digest(destination/relative)!=checksum:
            raise RuntimeError('Source changed during snapshot: '+relative)
    if set(before)!={str(p.relative_to(project)) for p in source_files()}:
        raise RuntimeError('Source file set changed during snapshot')
    (destination/'filming-snapshot.json').write_text(json.dumps({'created_utc':datetime.now(timezone.utc).isoformat(),
        'source':str(project),'source_files':before,'extra_files':{name:digest(additions/name) for name in ('MRFilmSubsystem.h','MRFilmSubsystem.cpp')},
        'maps_are_copies':True,'original_project_modified':False},indent=2),encoding='utf-8')
    print('SNAPSHOT '+str(destination),flush=True)


def run(command, cwd, log, timeout_s=1800):
    print('RUN '+str(log),flush=True)
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    with log.open('w',encoding='utf-8') as stream:
        result=subprocess.run([str(x) for x in command],cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,creationflags=flags,timeout=timeout_s)
    if result.returncode:
        raise RuntimeError(f'Exit {result.returncode}: {log}\n'+log.read_text(encoding='utf-8',errors='replace')[-3500:])


def verify_capture(folder, plan, expected_size=None):
    from PIL import Image
    folder=Path(folder)
    result=json.loads((folder/'capture.json').read_text(encoding='utf-8-sig'))
    expected=sum(shot['frames'] for shot in plan['shots'])
    if not result.get('complete') or result['frames']!=expected or result['fps']!=30:
        raise ValueError('Incomplete native capture manifest')
    rows=[json.loads(line) for line in (folder/'frames.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    if len(rows)!=expected:
        raise ValueError('Incomplete frame journal')
    cursor=0
    report=[]
    for shot in plan['shots']:
        files=sorted((folder/shot['id']).glob('frame-*.png'))
        if [p.name for p in files]!=[f'frame-{i:06d}.png' for i in range(shot['frames'])]:
            raise ValueError('Missing or extra frames in '+shot['id'])
        section=rows[cursor:cursor+shot['frames']];cursor+=shot['frames']
        for i,(p,row) in enumerate(zip(files,section)):
            try:
                with Image.open(p) as picture:
                    if picture.format!='PNG':raise ValueError('Not PNG')
                    if expected_size is None:expected_size=picture.size
                    if picture.size!=expected_size:raise ValueError('Unexpected frame dimensions')
                    picture.verify()
                with Image.open(p) as picture:picture.load()
            except (OSError,ValueError,SyntaxError) as error:
                raise ValueError('Invalid PNG: '+str(p)+' ('+str(error)+')') from error
            if row['shot']!=shot['id'] or row['frame']!=i:
                raise ValueError('Frame journal mismatch')
            if i:
                delta=row['world_time_s']-section[i-1]['world_time_s']
                if row.get('core_controlled'):
                    held=row.get('held_tail',False)
                    if held and (shot.get('wait_for_delivered',0)<1 or row.get('delivered',0)<shot['wait_for_delivered']):
                        raise ValueError('Held Core scene lacks its actual delivery gate')
                    if not (0 if held else 1e-12) <= delta <= 1/30+1/60+.001:
                        raise ValueError('Core render sample gap exceeds one physics quantum')
                    if row.get('core_time_s',-1)<section[i-1].get('core_time_s',-1):
                        raise ValueError('Core mission time went backwards')
                elif abs(delta-1/30)>.001:
                    raise ValueError('Nonuniform model time within a shot')
        report.append({'id':shot['id'],'frames':len(files),'duration_s':len(files)/30,
                       'world_start_s':section[0]['world_time_s'],'world_end_s':section[-1]['world_time_s'],
                       'core_start_s':section[0].get('core_time_s'),'core_end_s':section[-1].get('core_time_s'),
                       'held_tail_frames':sum(bool(row.get('held_tail')) for row in section),
                       'delivered_at_end':section[-1].get('delivered'),'follow':shot.get('follow','')})
    return {'passed':True,'frames':expected,'duration_s':expected/30,'dimensions':list(expected_size),'all_pngs_fully_decoded':True,'shots':report}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--engine',type=Path,default=Path(os.environ.get('MR_UNREAL_ENGINE',r'C:\Program Files\Epic Games\UE_5.8')))
    parser.add_argument('--output-root',type=Path,default=Path('D:/MetaRescue-output'))
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--build',action='store_true')
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--take',type=Path)
    parser.add_argument('--width',type=int,default=1920)
    parser.add_argument('--height',type=int,default=1080)
    parser.add_argument('--environment',choices=['showcase','static','random'],default='showcase')
    args=parser.parse_args()
    repo=args.repo.resolve();runtime=args.runtime.resolve()
    if args.prepare:
        additions=Path(__file__).resolve().parent
        if not (additions/'MRFilmSubsystem.cpp').is_file():
            additions=repo/'unreal/MetaRescue/Source/MetaRescue'
        prepare(repo,runtime,additions)
    if not args.build and not args.plan:return
    if not (runtime/'filming-snapshot.json').is_file():
        parser.error('Use a prepared isolated runtime')
    if args.width<320 or args.width>3840 or args.height<180 or args.height>2160:
        parser.error('Unsupported capture dimensions')
    plan=read_plan(args.plan) if args.plan else None
    if plan and not args.take:parser.error('--plan requires a new --take directory')
    sys.path.insert(0,str(repo))
    from controller.ai import file_lock
    from environment.main import existing_unreal
    # Same kernel lock used by the mission runner, not a second private lock.
    with file_lock(args.output_root/'locks/unreal-owner.lock',timeout_s=3):
        occupied=existing_unreal()
        if occupied:raise RuntimeError('Unreal slot is occupied; no build or capture started: '+str(occupied))
        engine=args.engine/'Engine';project=runtime/'MetaRescue.uproject'
        if args.build:
            runtimes=sorted((engine/'Binaries/ThirdParty/DotNet').glob('*/win-x64/dotnet.exe'))
            if not runtimes:raise FileNotFoundError('Bundled Unreal dotnet')
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            build_files=[p for p in (runtime/'Source').rglob('*') if p.is_file() and p.suffix in ('.cpp','.h','.cs')]
            build_hashes={str(p.relative_to(runtime)):digest(p) for p in build_files}
            (runtime/('build-'+stamp+'-inputs.json')).write_text(json.dumps(build_hashes,indent=2),encoding='utf-8')
            run([runtimes[-1],engine/'Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll','MetaRescueEditor','Win64','Development',
                 '-Project='+str(project),'-WaitMutex','-NoHotReloadFromIDE','-MaxParallelActions=1','-NoUBA'],runtime,runtime/('build-'+stamp+'.log'))
            if any(digest(runtime/name)!=checksum for name,checksum in build_hashes.items()):
                raise RuntimeError('Runtime source changed during build')
        if plan:
            take=args.take.resolve();take.mkdir(parents=True,exist_ok=False)
            shutil.copy2(args.plan,take/'plan.json')
            input_files=[runtime/'MetaRescue.uproject',runtime/'Binaries/Win64/UnrealEditor-MetaRescue.dll',runtime/'Content/Maps/RescueQuarter.umap']
            input_files += [p for sub in ('Source','Config','Content/Scenario') for p in (runtime/sub).rglob('*') if p.is_file()]
            frozen_inputs={str(p.relative_to(runtime)):digest(p) for p in input_files}
            command=[engine/'Binaries/Win64/UnrealEditor.exe',project,'/Game/Maps/RescueQuarter','-game',
                '-RenderOffscreen','-windowed',f'-ResX={args.width}',f'-ResY={args.height}','-ForceRes','-NoSound','-nosplash','-unattended',
                '-UseFixedTimeStep','-FPS=30','-FixedSeed','-MREnvironment='+args.environment,
                '-MRHorizon=3600','-MRQuitAfter='+str((plan['warmup_frames']+sum(s['frames']+s.get('wait_frames',0) for s in plan['shots']))/30+max(s.get('wait_until_s',0) for s in plan['shots'])+10),
                '-MRFilmPlan='+str(take/'plan.json'),'-MRFilmOutput='+str(take/'capture'),
                '-LocalDataCachePath='+str(args.output_root/'cache/ddc'),'-abslog='+str(take/'engine.log'),'-stdout','-FullStdOutLogOutput']
            manifest={'command':[str(x) for x in command],'plan_sha256':digest(args.plan),'runtime_snapshot_sha256':digest(runtime/'filming-snapshot.json'),
                'dll_sha256':digest(runtime/'Binaries/Win64/UnrealEditor-MetaRescue.dll'),'environment':args.environment,
                'film_sources':{name:digest(runtime/'Source/MetaRescue'/name) for name in ('MRFilmSubsystem.h','MRFilmSubsystem.cpp')},
                'native_inputs':frozen_inputs,
                'purpose':'presentation; not competition acceptance or FPS measurement'}
            (take/'launch.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
            run(command,runtime,take/'stdout.log')
            telemetry=runtime/'Saved/Telemetry'
            if telemetry.is_dir():shutil.copytree(telemetry,take/'telemetry')
            verification=verify_capture(take/'capture',plan,(args.width,args.height))
            verification['frozen_inputs_preserved']=all(digest(runtime/name)==checksum for name,checksum in frozen_inputs.items())
            if not verification['frozen_inputs_preserved']:raise RuntimeError('Native input changed during capture')
            (take/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
            print(json.dumps(verification),flush=True)


if __name__=='__main__':
    main()
