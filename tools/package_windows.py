"""Build and stage the independent Windows environment and controller."""
from __future__ import annotations

import argparse
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from controller.ai import file_lock
from environment.main import DEFAULT_OUTPUT, existing_unreal
from tools.native_archive import file_sha256


PROJECT = ROOT/'unreal/MetaRescue'
TOOLS = ('run_product.py', 'product_session.py', 'run_mission.py', 'native_archive.py',
         'native_process.py', 'analytics_service.py', 'run_native_series.py', 'series_plan.py', 'issue_operator.py')
DEPENDENCIES = ('jsonschema', 'jsonschema-specifications', 'attrs', 'referencing', 'rpds-py')
STARTUP = r"""@echo off
setlocal
cd /d "%~dp0"
set "PYTHONNOUSERSITE=1"
set "PYTHONPATH="
if not defined METARESCUE_OUTPUT set "METARESCUE_OUTPUT=%~dp0output"
if not defined METARESCUE_LIVE_BUDGET if exist "D:\MetaRescue-output\ai-budget.json" set "METARESCUE_LIVE_BUDGET=D:\MetaRescue-output\ai-budget.json"
if not defined METARESCUE_LIVE_BUDGET set "METARESCUE_LIVE_BUDGET=%LOCALAPPDATA%\MetaRescue\ai-budget.json"
"%~dp0python\python.exe" -B -X utf8 tools\run_product.py --configuration "%~dp0presets\offline.json" %*
exit /b %ERRORLEVEL%
"""


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def freeze_files(root):
    return {p.relative_to(root).as_posix(): file_sha256(p) for p in sorted(root.rglob('*')) if p.is_file()}


def project_inputs(project):
    values = {'MetaRescue.uproject': file_sha256(project/'MetaRescue.uproject')}
    for folder in ('Source', 'Config', 'Content'):
        values.update({folder+'/'+name: value for name, value in freeze_files(project/folder).items()})
    return values


def copy_project(snapshot):
    snapshot.mkdir(parents=True, exist_ok=False)
    descriptor = json.loads((PROJECT/'MetaRescue.uproject').read_bytes())
    plugins = [plugin for plugin in descriptor['Plugins'] if plugin['Name'] != 'AndroidFileServer']
    descriptor['Plugins'] = [*plugins, {'Name': 'AndroidFileServer', 'Enabled': False}]
    write_json(snapshot/'MetaRescue.uproject', descriptor)
    for part in ('Source', 'Config', 'Content'):
        shutil.copytree(PROJECT/part, snapshot/part)
    # Android File Server is not part of the Windows distribution.
    engine_ini = snapshot/'Config/DefaultEngine.ini'
    sections = engine_ini.read_text(encoding='utf-8-sig').splitlines()
    output = []
    include = True
    for line in sections:
        if line.startswith('['):
            include = not line.startswith('[/Script/AndroidFileServer')
        if include:
            output.append(line)
    engine_ini.write_text('\n'.join(output)+'\n', encoding='utf-8')


def prepare_grounding(project, engine, output, cache):
    scenario = project/'Content/Scenario'
    library = json.loads((scenario/'library-v3.json').read_bytes())
    replacements = json.loads((scenario/'city-assets.json').read_bytes())['replacements']
    meshes = set()
    for asset in library['assets']:
        for part in asset['parts']:
            if (asset['id'] in ('BuildingVariants', 'Rubble', 'Slab', 'Manhole') or
                    asset['id'] == 'SceneryKit' and part['object'].startswith('fragment_')):
                mesh = part['mesh']
                meshes.add(mesh)
                meshes.update(entry['mesh'] for entry in replacements.get(mesh, {}).get('parts', ()))
    requested = output/'grounding-meshes.json'
    report_path = output/'grounding-verification.json'
    write_json(requested, sorted(meshes))
    binaries = engine/'Engine/Binaries'
    dotnet = sorted((binaries/'ThirdParty/DotNet').glob('*/win-x64/dotnet.exe'))[-1]
    build_editor = [str(dotnet), str(binaries/'DotNET/UnrealBuildTool/UnrealBuildTool.dll'),
                    'MetaRescueEditor', 'Win64', 'Development', '-Project='+str(project/'MetaRescue.uproject'),
                    '-NoUBA', '-MaxParallelActions=2']
    script = ROOT/'unreal/tools/prepare_grounding_assets.py'
    prepare = [str(binaries/'Win64/UnrealEditor-Cmd.exe'), str(project/'MetaRescue.uproject'),
               '-run=pythonscript', '-script='+str(script), '-unattended', '-nullrhi', '-nop4', '-nosplash',
               '-LocalDataCachePath='+str(cache), '-stdout', '-FullStdOutLogOutput']
    with (output/'GroundingEditorBuild.log').open('w', encoding='utf-8') as log:
        subprocess.run(build_editor, cwd=project, stdout=log, stderr=subprocess.STDOUT, check=True)
    with (output/'GroundingPrepare.log').open('w', encoding='utf-8') as log:
        subprocess.run(prepare, cwd=project, stdout=log, stderr=subprocess.STDOUT, check=True,
                       env={**os.environ, 'MR_GROUNDING_MESHES':str(requested), 'MR_GROUNDING_REPORT':str(report_path)})
    report = json.loads(report_path.read_bytes())
    if report.get('passed') is not True or report['meshes'] != sorted(meshes):
        raise RuntimeError('Grounding commandlet did not verify the requested mesh assets')
    report.update(build_editor=build_editor, prepare=prepare, script_sha256=file_sha256(script),
                  report_sha256=file_sha256(report_path))
    return report


def bundle_python(destination):
    source = Path(sys.base_prefix)
    library = f'python{sys.version_info.major}{sys.version_info.minor}.dll'
    destination.mkdir()
    for filename in ('python.exe', 'python3.dll', library, 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt'):
        shutil.copy2(source/filename, destination)
    skip_cache = shutil.ignore_patterns('__pycache__', '*.pyc', '*_d.pyd', '*.pdb')
    shutil.copytree(source/'DLLs', destination/'DLLs', ignore=skip_cache)
    shutil.copytree(source/'Lib', destination/'Lib',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'site-packages', 'test', 'ensurepip'))
    packages = destination/'Lib/site-packages'
    packages.mkdir()
    versions = {}
    for name in DEPENDENCIES:
        distribution = metadata.distribution(name)
        versions[name] = distribution.version
        for item in distribution.files:
            source_file = Path(distribution.locate_file(item))
            if '..' in item.parts or source_file.suffix == '.pyc' or not source_file.is_file():
                continue
            target = packages/Path(item)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target)
    return {'interpreter': sys.version.split()[0], 'dependencies': versions}


def stage_runtime(distribution, demo, *, fab_usage_notice=None):
    for part in ('controller', 'contracts', 'environment', 'analytics', 'web'):
        shutil.copytree(ROOT/part, distribution/part, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (distribution/'tools').mkdir()
    for name in TOOLS:
        shutil.copy2(ROOT/'tools'/name, distribution/'tools'/name)
    native = distribution/'runtime/MetaRescue'
    if not (native/'Binaries/Win64/MetaRescue.exe').is_file():
        raise FileNotFoundError('BuildCookRun did not archive the Win64 game executable')
    if not (native/'Content/Scenario/core-scenarios-v1.json').is_file():
        raise FileNotFoundError('BuildCookRun did not stage the Scenario directory')
    shutil.copytree(native/'Content/Scenario', distribution/'unreal/MetaRescue/Content/Scenario')
    details = bundle_python(distribution/'python')
    write_json(distribution/'python/dependencies.json', details)
    (distribution/'presets').mkdir()
    write_json(distribution/'presets/offline.json', {'format': 'metarescue.product-request.v1',
        'settings': {'map_size': 25, 'seed': 2026, 'city_revision': '2.2', 'preset': 'urban', 'competition': True,
                     'resource_profile': 'contest', 'scouts': 2, 'rescuers': 2, 'people': 6},
        'controller': {'ai_mode': 'OFF', 'contest_coordination': True, 'realtime': True}})
    if demo is not None:
        shutil.copy2(demo, distribution/'presets/recovery.private.json')
    (distribution/'Start-MetaRescue.cmd').write_text(STARTUP, encoding='ascii', newline='\r\n')
    shutil.copy2(ROOT/'docs/stage-1-interaction.md', distribution/'Core-1.0.md')
    shutil.copy2(ROOT/'docs/windows-runtime.md', distribution/'README.md')
    shutil.copy2(ROOT/'docs/core-operator.md', distribution/'Operator.md')
    if fab_usage_notice is not None:
        shutil.copy2(fab_usage_notice, distribution/'Fab-Content-Notice.txt')
    return details


def build(output, engine, demo, *, fab_usage_notice=None):
    fab_packages = PROJECT/'Content/EffectsV3/Revision3/Fab'
    if any(fab_packages.rglob('*.uasset')) and fab_usage_notice is None:
        raise ValueError('Provide --fab-usage-notice for a cooked distribution containing Fab content')
    if fab_usage_notice is not None:
        fab_usage_notice = fab_usage_notice.resolve(strict=True)
        if not fab_usage_notice.is_file() or not fab_usage_notice.stat().st_size:
            raise ValueError('Fab usage notice must be a nonempty file')
        notice_sha256 = file_sha256(fab_usage_notice)
    output.mkdir(parents=True, exist_ok=False)
    project = output/'build-source/MetaRescue'
    distribution = output/'MetaEvolution-Rescue'
    copy_project(project)
    distribution.mkdir()
    cache = DEFAULT_OUTPUT/'cache/ddc'
    cache.mkdir(parents=True, exist_ok=True)
    initial = project_inputs(project)
    grounding = prepare_grounding(project, engine, output, cache)
    before = project_inputs(project)
    grounding_changes = {name for name in initial.keys() | before.keys() if initial.get(name) != before.get(name)}
    expected_meshes = {'Content/'+name.removeprefix('/Game/').split('.', 1)[0]+'.uasset' for name in grounding['meshes']}
    if not grounding_changes <= expected_meshes:
        raise RuntimeError('Grounding commandlet changed unexpected inputs: '+str(sorted(grounding_changes-expected_meshes)))
    uat = engine/'Engine/Build/BatchFiles/RunUAT.bat'
    command = [str(uat), 'BuildCookRun', '-project='+str(project/'MetaRescue.uproject'),
               '-noP4', '-unattended', '-utf8output', '-targetplatform=Win64', '-clientconfig=Development',
               '-ubtargs=-NoUBA -MaxParallelActions=2',
               '-build', '-cook', '-stage', '-pak', '-iostore', '-prereqs', '-archive',
               '-map=/Game/Maps/RescueQuarter+/Game/Maps/RescueDistrict',
               '-stagingdirectory='+str(output/'stage'), '-archivedirectory='+str(distribution/'runtime'),
               '-AdditionalCookerOptions=-SkipZenStore -LocalDataCachePath='+str(cache)]
    manifest = {'state': 'building', 'command': command, 'source_files': before,
                'grounding': grounding, 'grounding_changes': sorted(grounding_changes)}
    write_json(output/'build-manifest.json', manifest)
    with (output/'BuildCookRun.log').open('w', encoding='utf-8') as log:
        status = subprocess.run(command, cwd=project, stdout=log, stderr=subprocess.STDOUT, check=False)
    after = {name: file_sha256(project/name) if (project/name).is_file() else None for name in before}
    changed_inputs = [name for name, checksum in before.items() if after[name] != checksum]
    manifest.update(state='staging' if status.returncode == 0 and before == after else 'failed',
                    exit_code=status.returncode, frozen_inputs_preserved=not changed_inputs,
                    changed_inputs=changed_inputs)
    write_json(output/'build-manifest.json', manifest)
    if manifest['state'] == 'failed':
        raise RuntimeError('BuildCookRun or source verification failed. See '+str(output/'BuildCookRun.log'))
    try:
        manifest['python'] = stage_runtime(distribution, demo, fab_usage_notice=fab_usage_notice)
        if fab_usage_notice is not None:
            if file_sha256(distribution/'Fab-Content-Notice.txt') != notice_sha256:
                raise RuntimeError('Fab usage notice changed during packaging')
            manifest['fab_usage_notice_sha256'] = notice_sha256
    except Exception as error:
        manifest.update(state='failed', staging_error=f'{type(error).__name__}: {error}')
        write_json(output/'build-manifest.json', manifest)
        raise
    distribution_files = freeze_files(distribution)
    write_json(distribution/'SHA256.json', distribution_files)
    manifest.update(state='staged', distribution=str(distribution), files=len(distribution_files))
    write_json(output/'build-manifest.json', manifest)
    return distribution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--demo', type=Path)
    parser.add_argument('--fab-usage-notice', type=Path, help='recipient use conditions for incorporated Fab content')
    parser.add_argument('--engine', type=Path, default=Path(os.environ.get('MR_UNREAL_ENGINE',
                        r'C:\Program Files\Epic Games\UE_5.8')))
    args = parser.parse_args()
    if os.name != 'nt' or sys.version_info < (3, 13):
        parser.error('Packaging requires 64-bit Windows and the Python 3.13+ development environment')
    if not (args.engine/'Engine/Build/BatchFiles/RunUAT.bat').is_file():
        parser.error('RunUAT.bat is missing')
    with file_lock(DEFAULT_OUTPUT/'locks/unreal-owner.lock'):
        if existing_unreal():
            raise RuntimeError('Finish the current Unreal process before packaging')
        print(build(args.output.resolve(), args.engine.resolve(), args.demo, fab_usage_notice=args.fab_usage_notice), flush=True)


if __name__ == '__main__':
    main()
