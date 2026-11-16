"""Import revision5 under the shared Unreal lock and retain verifiable evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from controller.ai import file_lock
from environment.main import DEFAULT_OUTPUT, existing_unreal


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new evidence directory')
    args = parser.parse_args()
    inputs = args.inputs.resolve(strict=True)
    output = args.output.resolve()
    if output.is_relative_to(ROOT / 'unreal/MetaRescue/Content'):
        parser.error('Evidence must be outside Content')
    preparation = json.loads(inputs.read_bytes())
    if preparation.get('format') != 'metarescue.disaster-effects.sources.v1':
        parser.error('Unsupported art preparation')
    binary = ROOT / 'unreal/MetaRescue/Binaries/Win64/UnrealEditor-MetaRescue.dll'
    if not binary.is_file():
        parser.error('Build the Editor module with unreal/launch.py --quarter --build first')
    engine = Path(os.environ.get('MR_UNREAL_ENGINE', 'C:/Program Files/Epic Games/UE_5.8'))
    executable = engine / 'Engine/Binaries/Win64/UnrealEditor-Cmd.exe'
    if not executable.is_file():
        parser.error('UnrealEditor-Cmd.exe was not found')
    output.mkdir(parents=True, exist_ok=False)
    paths = [Path(__file__), inputs, binary]
    paths.extend(p for p in (ROOT / 'unreal/tools').rglob('*') if p.suffix in ('.py', '.hlsl') and p.is_file())
    paths.extend(p for p in (ROOT / 'unreal/MetaRescue/Source').rglob('*') if p.suffix in ('.cpp', '.h', '.cs') and p.is_file())
    for row in preparation['textures'].values():
        path = (inputs.parent / row['path']).resolve(strict=True)
        if not path.is_relative_to(inputs.parent) or path.stat().st_size != row['bytes'] or sha256(path) != row['sha256']:
            raise ValueError('Art source changed or is outside its preparation directory')
        paths.append(path)
    for revision in (2, 3, 4):
        paths.extend((ROOT / f'unreal/MetaRescue/Content/EffectsV3/Revision{revision}').rglob('*.uasset'))
    def frozen():
        return {str(path): sha256(path) for path in paths}
    before = frozen()
    (output / 'inputs.json').write_text(json.dumps(before, indent=2) + '\n', encoding='utf-8')
    report = output / 'import.json'
    command = [str(executable), str(ROOT / 'unreal/MetaRescue/MetaRescue.uproject'), '/Engine/Maps/Entry',
               '-run=pythonscript', '-script=' + str(ROOT / 'unreal/tools/build_disaster_effects.py'),
               '-unattended', '-nop4', '-nosplash', '-NoSound', '-stdout', '-FullStdOutLogOutput',
               '-LocalDataCachePath=' + str(DEFAULT_OUTPUT / 'cache/ddc'), '-abslog=' + str(output / 'engine.log')]
    verification = {'passed': False, 'started': datetime.now(timezone.utc).isoformat(), 'command': command}
    with file_lock(DEFAULT_OUTPUT / 'locks/unreal-owner.lock'):
        if existing_unreal():
            raise RuntimeError('Another Unreal is running; disaster art import did not start')
        try:
            environment = {**os.environ, 'MR_DISASTER_ART_INPUTS': str(inputs), 'MR_DISASTER_ART_REPORT': str(report)}
            with (output / 'stdout.log').open('w', encoding='utf-8') as log:
                result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=environment,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            verification['exit_code'] = result.returncode
            verification['frozen_sources_and_old_effects_preserved'] = before == frozen()
            log = (output / 'stdout.log').read_text(encoding='utf-8', errors='replace')
            verification['shader_errors'] = [line for line in log.splitlines() if
                'Failed to compile Material' in line or 'error X' in line or 'LogPython: Error:' in line]
            verification['passed'] = result.returncode == 0 and report.is_file() and \
                verification['frozen_sources_and_old_effects_preserved'] and not verification['shader_errors']
            if verification['passed']:
                artifacts = list((ROOT / 'unreal/MetaRescue/Content/EffectsV3/Revision5').rglob('*.uasset'))
                verification['generated_assets'] = {path.relative_to(ROOT).as_posix(): sha256(path) for path in artifacts}
        finally:
            verification['ended'] = datetime.now(timezone.utc).isoformat()
            (output / 'verification.json').write_text(json.dumps(verification, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': verification['passed'], 'output': str(output),
                      'assets': len(verification.get('generated_assets', {}))}), flush=True)
    return 0 if verification['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
