"""Build/prepare/open the separate Unreal environment with installed engine tools."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
import json
import hashlib

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT/'MetaRescue'/'MetaRescue.uproject'



def functional_time_args(fps, *, quarter, smoke, environment, traffic_probe=None, capture_frames=False, visual_probe=None):
    """Fixed logical time is an explicit functional profile, never a performance run."""
    if fps is None:return []
    if fps!=30 or not quarter or not smoke or environment!='random' or traffic_probe or capture_frames or visual_probe not in {None,'events'}:
        raise ValueError('--fixed-step-fps 30 requires --quarter --smoke --environment random without traffic/window-inspection/capture')
    return ['-UseFixedTimeStep','-FPS=30']


def main():
    parser=argparse.ArgumentParser(description='MetaRescue Unreal physics environment')
    parser.add_argument('--engine',type=Path,default=Path(os.environ.get('MR_UNREAL_ENGINE',r'C:\Program Files\Epic Games\UE_5.8')))
    parser.add_argument('--build',action='store_true',help='compile the C++ Editor module')
    parser.add_argument('--automation',metavar='PREFIX',help='run native tests and verify their report, not just process exit')
    parser.add_argument('--build-jobs',type=int,choices=[1,2],default=1,help='bounded compiler concurrency')
    parser.add_argument('--use-uba',action='store_true',help='opt in to UBA; ordinary local builds avoid its additional memory allocation')
    parser.add_argument('--setup',action='store_true',help='create materials and map if not present')
    parser.add_argument('--rebuild-scene',action='store_true',help='explicitly regenerate the code-managed district geometry')
    parser.add_argument('--smoke',action='store_true',help='offscreen physics run (90 model seconds by default)')
    parser.add_argument('--smoke-seconds',type=int,default=None,help='duration of physics smoke, 30..900; default 90, or 480 for --quarter')
    parser.add_argument('--environment',choices=['random','static','showcase'],default='random',help='quarter event mode; showcase is explicitly scripted')
    parser.add_argument('--seed',type=int,default=None,help='quarter event seed, independent from layout')
    parser.add_argument('--fixed-step-fps',type=int,choices=[30],help='functional random validation at 30 model ticks/s; never use for FPS acceptance')
    parser.add_argument('--external-control',action='store_true',help='disable the built-in mission dispatcher')
    parser.add_argument('--traffic-probe',choices=['following','crossing','meeting','reverse','flight','landing','obstacle_replace'],help='explicit controlled safety fixture; no mission dispatch')
    parser.add_argument('--capture-frames',action='store_true',help='capture a real 5 fps engine frame sequence at 28..148 model seconds')
    parser.add_argument('--visual-probe',choices=['windows','events','city-assets','city-buildings','city-lumen','city-glazing','city-competition'],
                        help='windows, event sources, or CityV2 asset and structure views')
    parser.add_argument('--probe-warmup',type=float,default=0,help='extra seconds before diagnostic photographs, 0..120')
    parser.add_argument('--diagnostic-ev',type=float,help='fixed EV100 override for renderer diagnosis only')
    parser.add_argument('--lumen-view',type=int,choices=[3,5,8,12,13],help='diagnostic Lumen scene/cache/albedo/direct/indirect view')
    parser.add_argument('--glass-reflection-test',action='store_true',help='compare glazing without Lumen front-layer reflections')
    parser.add_argument('--probability',action='append',default=[],metavar='NAME=PERCENT',help='override one of the eight quarter probabilities')
    parser.add_argument('--editor',action='store_true',help='open the Unreal editor')
    parser.add_argument('--quarter',action='store_true',help='use the separate authored RescueQuarter map')
    parser.add_argument('--city-layout',type=Path,help='private generated city layout; current geometry acceptance requires static external control')
    parser.add_argument('--visible',action='store_true',help='show the game window during --smoke; wait for it before verification')
    parser.add_argument('--mechanics-probe',action='store_true',help='add two physical validation vehicles at 90s; quarter only')
    args=parser.parse_args()
    if args.automation:
        import re
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]*',args.automation):parser.error('Invalid Automation test prefix')
        if args.smoke or args.editor or args.setup or args.rebuild_scene:parser.error('--automation cannot be combined with scene/editor/smoke operations')
    if args.smoke_seconds is None:args.smoke_seconds=480 if args.quarter else 90
    if not 30<=args.smoke_seconds<=900:parser.error('--smoke-seconds must be 30..900')
    event_args=['-MREnvironment='+args.environment,'-MRHorizon='+str(max(480,args.smoke_seconds))]
    if args.seed is not None:event_args.append('-MRSeed='+str(args.seed))
    try:event_args+=functional_time_args(args.fixed_step_fps,quarter=args.quarter,smoke=args.smoke,environment=args.environment,traffic_probe=args.traffic_probe,capture_frames=args.capture_frames,visual_probe=args.visual_probe)
    except ValueError as error:parser.error(str(error))
    if args.traffic_probe:
        if not args.quarter or not args.smoke:parser.error('--traffic-probe requires --quarter --smoke')
        args.external_control=True;event_args.append('-MRTrafficProbe='+args.traffic_probe)
    if args.external_control:event_args.append('-MRExternalControl')
    if args.city_layout:
        if not args.quarter or args.environment!='static' or not args.external_control:
            parser.error('--city-layout currently requires --quarter --environment static --external-control')
        if not args.city_layout.is_file():parser.error('City layout file is missing')
        event_args.append('-MRLayoutFile='+str(args.city_layout.resolve()))
    if args.capture_frames:event_args.append('-MRCaptureFrames')
    if args.visual_probe:event_args.append('-MRVisualProbe='+args.visual_probe)
    import math
    if not math.isfinite(args.probe_warmup) or not 0<=args.probe_warmup<=120:parser.error('--probe-warmup must be 0..120')
    if args.probe_warmup:event_args.append('-MRProbeWarmup='+str(args.probe_warmup))
    if args.diagnostic_ev is not None:
        if not math.isfinite(args.diagnostic_ev) or not -4<=args.diagnostic_ev<=16:parser.error('--diagnostic-ev must be -4..16')
        event_args.append('-MRDiagnosticEV='+str(args.diagnostic_ev))
    renderer_commands=[]
    if args.lumen_view:renderer_commands.append('r.Lumen.Visualize '+str(args.lumen_view))
    if args.glass_reflection_test:renderer_commands.append('r.Lumen.TranslucencyReflections.FrontLayer.Allow 0')
    if renderer_commands:event_args.append('-ExecCmds='+','.join(renderer_commands))
    for value in args.probability:
        try:name,number=value.split('=',1);number=float(number)
        except ValueError:parser.error('--probability requires NAME=PERCENT')
        if name not in {'collapse','fire','flood','mud','road_damage','smoke','low_visibility','new_target'} or not math.isfinite(number) or not 0<=number<=100:
            parser.error('unknown event or probability outside 0..100')
        event_args.append('-MRProbability_'+name+'='+str(number))
    if args.mechanics_probe and (not args.quarter or not args.smoke or args.smoke_seconds<130):
        parser.error('--mechanics-probe requires --quarter --smoke and at least 130 seconds')
    engine=args.engine/'Engine'
    editor=engine/'Binaries/Win64/UnrealEditor.exe'
    commandlet=engine/'Binaries/Win64/UnrealEditor-Cmd.exe'
    cache=Path(os.environ.get('METARESCUE_OUTPUT','D:/MetaRescue-output'))/'cache/ddc'
    cache.mkdir(parents=True,exist_ok=True)
    cache_arg='-LocalDataCachePath='+str(cache)
    map_name='RescueQuarter' if args.quarter else 'RescueDistrict'
    if not editor.is_file():parser.error('Unreal Engine 5.8 not found; supply --engine or MR_UNREAL_ENGINE')
    logdir=ROOT/'MetaRescue'/'Saved'/'Automation';logdir.mkdir(parents=True,exist_ok=True)
    def run(command,name,hidden=False,log_path=None):
        log=log_path or logdir/(name+'.log');print(name+': '+str(log),flush=True)
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' and hidden else 0
        with log.open('w',encoding='utf-8') as output:
            result=subprocess.run([str(x) for x in command],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,creationflags=flags)
        if result.returncode:
            print(log.read_text(encoding='utf-8',errors='replace')[-7000:])
            raise RuntimeError(f'{name} failed: exit {result.returncode}; {log}')
        print(name+' completed',flush=True)
    if args.build:
        runtimes=list((engine/'Binaries/ThirdParty/DotNet').glob('*/win-x64/dotnet.exe'))
        if not runtimes:parser.error('Bundled Unreal .NET runtime not found')
        run([sorted(runtimes)[-1],engine/'Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll',
             'MetaRescueEditor','Win64','Development','-Project='+str(PROJECT),
             '-WaitMutex','-NoHotReloadFromIDE','-MaxParallelActions='+str(args.build_jobs),*([] if args.use_uba else ['-NoUBA'])],'build',True)
    if args.setup or args.rebuild_scene:
        scenario='quarter.json' if args.quarter else 'scenario.json'
        if not (ROOT/'MetaRescue/Content/Scenario'/scenario).is_file():
            exporter='author_quarter_scenario.py' if args.quarter else 'export_scenario.py'
            run([sys.executable,'-B','-X','utf8',ROOT/'tools'/exporter],'scenario',True)
        else:
            print('Preserving the existing exported scenario snapshot.',flush=True)
        marker='quarter-build.json' if args.quarter else 'scene-build.json'
        if not args.rebuild_scene and (ROOT/'MetaRescue/Content/Maps'/(map_name+'.umap')).is_file() and (ROOT/'MetaRescue/Content/Scenario'/marker).is_file():
            print('Saved map already exists; preserving it. Use the editor for authored changes.')
        else:
            scene_builder='build_quarter.py' if args.quarter else 'build_scene.py'
            run([commandlet,PROJECT,'-run=pythonscript','-script='+str(ROOT/'tools'/scene_builder),
                 '-unattended','-NoSound','-nosplash',cache_arg,'-stdout','-FullStdOutLogOutput'],'scene',True)
    if args.automation:
        from datetime import datetime,timezone
        sys.path.insert(0,str(ROOT.parent))
        from environment.main import DEFAULT_OUTPUT,existing_unreal
        from controller.ai import file_lock
        with file_lock(DEFAULT_OUTPUT/'locks/unreal-owner.lock'):
            if existing_unreal():raise RuntimeError('Another Unreal is running; Automation did not start')
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            output=DEFAULT_OUTPUT/'automation'/stamp;output.mkdir(parents=True,exist_ok=False)
            files=[Path(__file__),ROOT/'MetaRescue/Binaries/Win64/UnrealEditor-MetaRescue.dll']
            files.extend(p for p in (ROOT/'MetaRescue/Source').rglob('*') if p.is_file() and p.suffix in ('.h','.cpp','.cs'))
            def frozen():return {str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
            before=frozen();(output/'inputs.json').write_text(json.dumps(before,indent=2),encoding='utf-8')
            run([commandlet,PROJECT,'/Engine/Maps/Entry','-unattended','-nop4','-nosplash','-nullrhi','-nosound',
                 '-ExecCmds=Automation RunTests '+args.automation,'-TestExit=Automation Test Queue Empty',
                 '-ReportExportPath='+str(output),'-abslog='+str(output/'engine.log'),cache_arg,
                 '-stdout','-FullStdOutLogOutput'],'automation',True,output/'stdout.log')
            report=json.loads((output/'index.json').read_text(encoding='utf-8-sig'))
            preserved=before==frozen();passed=preserved and report['failed']==0 and report['notRun']==0 and report['inProcess']==0 and report['succeeded']+report['succeededWithWarnings']>0
            verification={k:report[k] for k in ('succeeded','succeededWithWarnings','failed','notRun','inProcess')}
            verification.update(passed=passed,frozen_inputs_preserved=preserved,prefix=args.automation)
            (output/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
            print(json.dumps({'report':str(output),**verification}),flush=True)
            if not passed:raise RuntimeError('Automation report failed; '+str(output))
        return 0
    if args.smoke:
        request={'started_at':time.time(),'requested_seconds':args.smoke_seconds,'quarter':args.quarter,'environment':args.environment,'seed':args.seed,'external_control':args.external_control,'traffic_probe':args.traffic_probe,'time_step_mode':'fixed_functional' if args.fixed_step_fps else 'real_time','requested_fixed_fps':args.fixed_step_fps or 0}
        if args.visual_probe:request['visual_probe']=args.visual_probe
        if args.glass_reflection_test:request['glass_reflection_test']=True
        if args.city_layout:request['city_layout_sha256']=hashlib.sha256(args.city_layout.read_bytes()).hexdigest()
        (logdir/'smoke-run.json').write_text(json.dumps(request),encoding='utf-8')
        native_wall_started=time.perf_counter()
        run([editor,PROJECT,'/Game/Maps/'+map_name,'-game',*([] if args.visible else ['-RenderOffscreen']),'-windowed',
             '-ResX=1600','-ResY=1000','-ForceRes','-NoSound','-nosplash','-unattended','-MRSmoke','-MRQuitAfter='+str(args.smoke_seconds),
             *(['-MRPhotoTour'] if args.quarter else []),*(['-MRMechanicsProbe'] if args.mechanics_probe else []),*(event_args if args.quarter else []),cache_arg,'-stdout','-FullStdOutLogOutput'],'physics-smoke',not args.visible)
        request['wall_elapsed_s']=time.perf_counter()-native_wall_started
        (logdir/'smoke-run.json').write_text(json.dumps(request),encoding='utf-8')
        if args.city_layout:
            run([sys.executable,'-B','-X','utf8',ROOT/'tools/check_city_run.py','--layout',args.city_layout],'physics-check',True)
        else:run([sys.executable,'-B','-X','utf8',ROOT/'tools/check_smoke.py'],'physics-check',True)
    elif args.editor or not (args.build or args.setup or args.rebuild_scene):
        subprocess.Popen([str(editor),str(PROJECT),'/Game/Maps/'+map_name,*(event_args if args.quarter else []),cache_arg],cwd=ROOT)
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (RuntimeError,OSError) as error:
        print(error,file=sys.stderr);raise SystemExit(1)
