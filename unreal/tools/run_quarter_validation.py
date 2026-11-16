"""Sequential native runs with provenance and fresh evidence. One UE owner only."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from check_quarter_v3_run import verify

ROOT=Path(__file__).resolve().parents[2]
SAVED=ROOT/'unreal/MetaRescue/Saved'
EVENTS=['collapse','fire','flood','mud','road_damage','smoke','low_visibility','new_target']
TRAFFIC=['following','crossing','meeting','reverse','flight','landing','obstacle_replace']


def sha256(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def source_snapshot():
    paths=[*ROOT.glob('unreal/MetaRescue/Source/MetaRescue/*'),*ROOT.glob('unreal/tools/*.py'),
           *ROOT.glob('unreal/MetaRescue/Content/Scenario/*.json'),*ROOT.glob('unreal/MetaRescue/Config/*'),
           ROOT/'unreal/launch.py',ROOT/'unreal/MetaRescue/MetaRescue.uproject',ROOT/'unreal/MetaRescue/Binaries/Win64/UnrealEditor-MetaRescue.dll',
           ROOT/'unreal/MetaRescue/Content/Maps/RescueQuarter.umap']
    paths.extend((ROOT/'unreal/MetaRescue/Content/RescueAssets/CityV2').rglob('*.uasset'))
    return {p.relative_to(ROOT).as_posix():{'sha256':sha256(p),'mtime':p.stat().st_mtime,'size':p.stat().st_size}
            for p in paths if p.is_file()}


def ensure_exclusive():
    if os.name!='nt':return
    query="Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'UnrealEditor*' } | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    completed=subprocess.run(['powershell','-NoProfile','-Command',query],capture_output=True,text=True,check=True)
    if completed.stdout.strip():raise RuntimeError('Unreal is already running. Preserve/close it before another native run: '+completed.stdout.strip())


def archive_files(out,started):
    for directory in ['Telemetry','Automation','Crashes']:
        destination=out/directory;destination.mkdir()
        for path in (SAVED/directory).rglob('*'):
            if path.is_file() and path.stat().st_mtime>=started:
                target=destination/path.relative_to(SAVED/directory);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    images=out/'Screenshots';images.mkdir()
    for path in (SAVED/'Screenshots').rglob('*.png'):
        if path.stat().st_mtime>=started:
            target=images/path.relative_to(SAVED/'Screenshots');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    for path in (SAVED/'Logs').glob('*.nv-gpudmp'):
        if path.stat().st_mtime>=started:
            target=out/'Automation'/path.name;shutil.copy2(path,target)


def run(name,extra,seconds,checker=verify):
    ensure_exclusive()
    out=Path(os.environ.get('METARESCUE_OUTPUT', 'D:/MetaRescue-output'))/'quarter-v3/runs'/name
    if out.exists():raise RuntimeError('Evidence folder already exists: '+str(out))
    out.mkdir(parents=True)
    input_files=[]
    if '--city-layout' in extra:
        layout=Path(extra[extra.index('--city-layout')+1])
        data=json.loads(layout.read_text(encoding='utf-8'))
        assert data.get('format') in (
            'rescue-city-1.0','rescue-city-1.1','rescue-city-2.0','rescue-city-2.1','rescue-city-2.2','rescue-city-2.3'),'not a generated city layout'
        if data['format'] in ('rescue-city-2.1','rescue-city-2.2','rescue-city-2.3'):
            revision=data.get('vegetation_revision',1)
            catalog_name=f'city-vegetation-v2-r{revision}.json' if revision>1 else 'city-vegetation-v2.json'
            vegetation=ROOT/'unreal/MetaRescue/Content/Scenario'/catalog_name
            assert sha256(vegetation)==data['vegetation_manifest_sha256'],'vegetation catalog changed since layout generation'
            if data['format'] in ('rescue-city-2.2','rescue-city-2.3'):
                assert sha256(vegetation.with_name('city-props-v1.json'))==data['city_props_manifest_sha256'],'prop catalog changed'
        shutil.copy2(layout,out/'layout.private.json');input_files.append(layout)
    input_hashes={str(p):sha256(p) for p in input_files}
    snapshot=source_snapshot();started=time.time()
    command=[sys.executable,'-B','-X','utf8',str(ROOT/'unreal/launch.py'),'--quarter','--smoke','--smoke-seconds',str(seconds),*extra]
    (out/'command.json').write_text(json.dumps(command,indent=2),encoding='utf-8')
    with (out/'launcher.log').open('w',encoding='utf-8') as log:
        completed=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    archive_files(out,started)
    ended=time.time()
    files={p.relative_to(out).as_posix():{'sha256':sha256(p),'mtime':p.stat().st_mtime,'size':p.stat().st_size}
           for p in out.rglob('*') if p.is_file()}
    fixed_fps=int(extra[extra.index('--fixed-step-fps')+1]) if '--fixed-step-fps' in extra else 0
    metadata={'started_at':started,'ended_at':ended,'launcher_exit':completed.returncode,'wall_elapsed_s':ended-started,
              'time_step_mode':'fixed_functional' if fixed_fps else 'real_time','requested_fixed_fps':fixed_fps,
              'source_hashes_before':snapshot,'source_hashes_after':source_snapshot(),'files':files}
    metadata['input_hashes_before']=input_hashes
    metadata['input_hashes_after']={str(p):sha256(p) for p in input_files}
    (out/'evidence-run.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    print(name,'native exit',completed.returncode,'evidence',out,flush=True)
    try:
        result=checker(out)
        assert completed.returncode==0,'launcher/common smoke checks failed; inspect launcher.log'
        assert metadata['source_hashes_before']==metadata['source_hashes_after'],'source or binary changed during native run'
        assert metadata['input_hashes_before']==metadata['input_hashes_after'],'private layout changed during native run'
    except (AssertionError,KeyError,FileNotFoundError,ValueError) as error:
        root_reason=None
        native_log=out/'Automation/physics-smoke.log'
        if completed.returncode and native_log.exists():
            for line in native_log.read_text(encoding='utf-8',errors='replace').splitlines():
                if any(marker in line for marker in ('DXGI_ERROR_','Fatal error:','GPU crash detected:','Assertion failed:')):
                    root_reason=line[:500]
                    if 'DXGI_ERROR_' in line:break
        (out/'verification.json').write_text(json.dumps({'passed':False,'error':str(error),
            'launcher_exit':completed.returncode,'native_failure':root_reason},indent=2),encoding='utf-8')
        raise RuntimeError('Native validation failed: '+str(error)+'; evidence '+str(out)) from error
    return out


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('suite',choices=['static','random','traffic','effects','showcase','windows','zero','replay'])
    parser.add_argument('--prefix',default='v3')
    parser.add_argument('--case',help='Run one traffic fixture, effect or numeric random seed')
    parser.add_argument('--seconds',type=int,help='Override duration for a diagnostic run')
    parser.add_argument('--probe-warmup',type=float,default=0)
    parser.add_argument('--diagnostic-ev',type=float)
    parser.add_argument('--lumen-view',type=int,choices=[3,5,8,12,13])
    parser.add_argument('--fixed-step-fps',type=int,choices=[30],help='functional random/replay/effects/zero only; no performance verdict')
    args=parser.parse_args()
    if args.seconds is not None and not 30<=args.seconds<=900:parser.error('--seconds must be 30..900')
    if args.fixed_step_fps and args.suite not in {'random','replay','effects','zero'}:parser.error('--fixed-step-fps is only for random/replay/effects/zero functional validation')
    if args.fixed_step_fps:args.prefix+='-fixed30'
    def duration(default):return args.seconds or default
    if args.suite=='static':run(args.prefix+'-static',['--environment','static'],duration(270))
    elif args.suite in {'random','replay'}:
        for seed in [int(args.case)] if args.case else [20261109,20261110,20261111]:
            options=['--environment','random','--seed',str(seed)]
            if args.fixed_step_fps:options+=['--fixed-step-fps',str(args.fixed_step_fps)]
            first=run(args.prefix+'-random-'+str(seed),options,duration(480))
            if args.suite=='replay':
                second=run(args.prefix+'-replay-'+str(seed),options,duration(480))
                subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/'unreal/tools/compare_quarter_replay.py'),str(first),str(second)],cwd=ROOT,check=True)
    elif args.suite=='traffic':
        if args.case and args.case not in TRAFFIC:parser.error('Unknown traffic case')
        for kind in [args.case] if args.case else TRAFFIC:
            run(args.prefix+'-traffic-'+kind,['--environment','static','--traffic-probe',kind],duration(100))
    elif args.suite=='effects':
        if args.case and args.case not in EVENTS:parser.error('Unknown effect case')
        for kind in [args.case] if args.case else EVENTS:
            options=['--environment','random','--visual-probe','events']
            if args.fixed_step_fps:options+=['--fixed-step-fps',str(args.fixed_step_fps)]
            for name in EVENTS:options+=['--probability',name+'='+str(100 if name==kind else 0)]
            run(args.prefix+'-effect-'+kind,options,duration(180))
    elif args.suite=='windows':
        # This is an explicit static visual fixture. Mission movement/delivery
        # remain mandatory in the separate static270 scenario.
        options=['--environment','static','--external-control','--visual-probe','windows','--probe-warmup',str(args.probe_warmup)]
        if args.diagnostic_ev is not None:options+=['--diagnostic-ev',str(args.diagnostic_ev)]
        if args.lumen_view:options+=['--lumen-view',str(args.lumen_view)]
        run(args.prefix+'-windows',options,duration(math.ceil(30+args.probe_warmup)))
    elif args.suite=='zero':
        options=['--environment','random']
        if args.fixed_step_fps:options+=['--fixed-step-fps',str(args.fixed_step_fps)]
        for name in EVENTS:options+=['--probability',name+'=0']
        run(args.prefix+'-zero',options,duration(160))
    else:run(args.prefix+'-showcase',['--environment','showcase','--visual-probe','events','--capture-frames'],duration(240))


if __name__=='__main__':main()
