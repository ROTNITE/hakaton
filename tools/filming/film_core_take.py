"""Film an unchanged Core mission through the existing lifecycle/verification runner.

The scoped adapter replaces only the project path, render resolution and camera
flags. Core, controller, world, policy, archives and the common lock remain owned
by tools.run_mission. No HTTP request or AI response is supplied by this tool.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

if __package__:
    from .film_capture import digest, read_plan, verify_capture
else:
    from film_capture import digest, read_plan, verify_capture


def film_command(command, runtime, plan, capture, width, height):
    if len(command)<2 or Path(command[1]).suffix.casefold()!='.uproject':
        raise ValueError('Filming adapter requires the UE Editor source runtime')
    result=list(command);result[1]=str(runtime/'MetaRescue.uproject')
    # The movie owns the final few render frames after the verified terminal
    # handover. The normal runner still requires native exit 0 within 30 seconds.
    result=[item for item in result if item!='-MRCoreExitOnClose' and not item.startswith(('-ResX=','-ResY='))]
    result += [f'-ResX={width}',f'-ResY={height}','-MRFilmPlan='+str(plan),'-MRFilmOutput='+str(capture)]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--take',type=Path,required=True)
    parser.add_argument('--layout',type=Path,required=True)
    parser.add_argument('--name',required=True)
    parser.add_argument('--width',type=int,default=1920)
    parser.add_argument('--height',type=int,default=1080)
    args=parser.parse_args()
    repo=args.repo.resolve();runtime=args.runtime.resolve();plan=read_plan(args.plan)
    if not plan.get('exit_on_finish',True):
        parser.error('Core film must exit on completion; last shot must follow terminal delivery')
    if not 320<=args.width<=3840 or not 180<=args.height<=2160:parser.error('Unsupported dimensions')
    if not (runtime/'filming-snapshot.json').is_file():parser.error('Use an isolated prepared runtime')
    take=args.take.resolve();take.mkdir(parents=True,exist_ok=False)
    shutil.copy2(args.plan,take/'plan.json');shutil.copy2(args.layout,take/'world.private.json')
    source_files=[p for p in (runtime/'Source').rglob('*') if p.is_file() and p.suffix in ('.cpp','.h','.cs')]
    source_files += [runtime/'MetaRescue.uproject',runtime/'Binaries/Win64/UnrealEditor-MetaRescue.dll',runtime/'Content/Maps/RescueQuarter.umap']
    frozen={str(p.relative_to(runtime)):digest(p) for p in source_files}
    sys.path.insert(0,str(repo))
    from tools import run_mission as mission
    original=mission.native_command
    def camera_command(**kwargs):
        result=film_command(original(**kwargs),runtime,take/'plan.json',take/'capture',args.width,args.height)
        (take/'launch.json').write_text(json.dumps({'command':result,'native_inputs':frozen,
            'source_layout_sha256':digest(take/'world.private.json'),'plan_sha256':digest(take/'plan.json'),
            'purpose':'native Core mission with a presentation-only observer camera','ai_mode':'MOCK; no network calls'},indent=2),encoding='utf-8')
        return result
    arguments=[str(mission.__file__),'--layout',str(take/'world.private.json'),'--name',args.name,
               '--policy','nsga2_nsga2','--ai-mode','MOCK','--contest-coordination','--wall-timeout','1500']
    with patch.object(mission,'native_command',camera_command),patch.object(sys,'argv',arguments):
        status=mission.main()
    if status:raise RuntimeError('Core mission runner failed; inspect D:/MetaRescue-output/missions/'+args.name)
    verification=verify_capture(take/'capture',plan,(args.width,args.height))
    verification['frozen_native_inputs_preserved']=all(digest(runtime/name)==checksum for name,checksum in frozen.items())
    if not verification['frozen_native_inputs_preserved']:raise RuntimeError('Filming runtime changed')
    run=Path(mission.DEFAULT_OUTPUT)/'missions'/args.name
    manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
    if manifest['state']!='complete' or not manifest.get('frozen_inputs_preserved'):
        raise RuntimeError('Core run was not completely verified')
    verification['mission']={key:manifest.get(key) for key in ('state','episode_status','metrics','native_archive','native_exit_code','controller_exit_code')}
    verification['mission_directory']=str(run)
    shutil.copy2(run/'manifest.json',take/'mission-manifest.json')
    shutil.copy2(run/'native-archive-verification.json',take/'native-archive-verification.json')
    (take/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
    print(json.dumps(verification),flush=True)


if __name__=='__main__':main()
