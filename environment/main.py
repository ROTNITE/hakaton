"""Start the authoritative Unreal environment; the controller is separate."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGED_GAME = ROOT/'runtime/MetaRescue/Binaries/Win64/MetaRescue.exe'
DEFAULT_OUTPUT = Path(os.environ.get('METARESCUE_OUTPUT',
    str(ROOT/'output' if PACKAGED_GAME.is_file() else 'D:/MetaRescue-output'))).resolve()


def existing_unreal():
    """Inventory only. Never stop an editor owned by another task/user."""
    if os.name != 'nt':
        return []
    result = []
    for name in ('UnrealEditor.exe', 'UnrealEditor-Cmd.exe', 'MetaRescue.exe'):
        response = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq '+name, '/FO', 'CSV', '/NH'],
                                  capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if response.returncode:
            raise RuntimeError('Cannot verify the single-Unreal boundary: tasklist failed')
        for row in csv.reader(response.stdout.splitlines()):
            if row and row[0].casefold() == name.casefold():
                result.append({'name': row[0], 'pid': row[1]})
    return result


def native_command(*, layout=None, port=8130, output, visible=False, headless=False, exit_on_close=False,realtime=False):
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('port must be 1024..65535')
    if PACKAGED_GAME.is_file():
        command = [str(PACKAGED_GAME)]
    else:
        engine = Path(os.environ.get('MR_UNREAL_ENGINE', r'C:\Program Files\Epic Games\UE_5.8'))
        executable = engine/'Engine/Binaries/Win64/UnrealEditor.exe'
        if not executable.is_file():
            raise FileNotFoundError('Unreal Engine 5.8 executable is missing')
        command = [str(executable), str(ROOT/'unreal/MetaRescue/MetaRescue.uproject')]
    output = Path(output).resolve()
    cache = DEFAULT_OUTPUT/'cache/ddc'
    cache.mkdir(parents=True, exist_ok=True)
    command += ['/Game/Maps/RescueQuarter', '-game', '-windowed', '-ResX=1600', '-ResY=1000',
               '-ForceRes', '-NoSound', '-nosplash', '-unattended', '-MRExternalControl',
               '-MRCorePort='+str(port), '-LocalDataCachePath='+str(cache),
               '-MRCorePython='+sys.executable, '-MRCoreSource='+str(ROOT),
               '-stdout', '-FullStdOutLogOutput', '-abslog='+str(output/'engine.log')]
    if headless and visible:raise ValueError('Headless and visible rendering are mutually exclusive')
    if headless:
        command.append('-nullrhi')
    elif not visible:
        command.append('-RenderOffscreen')
    if layout is not None:
        layout = Path(layout).resolve(strict=True)
        command.append('-MRLayoutFile='+str(layout))
    if exit_on_close:
        command.append('-MRCoreExitOnClose')
    if realtime:command.append('-MRCoreRealtime')
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layout', type=Path)
    parser.add_argument('--port', type=int, default=8130)
    parser.add_argument('--output', type=Path)
    rendering = parser.add_mutually_exclusive_group()
    rendering.add_argument('--visible', action='store_true')
    rendering.add_argument('--headless', action='store_true', help='Run native physics without rendering')
    parser.add_argument('--realtime',action='store_true',help='Wall-paced fixed 60 Hz execution, required for LIVE AI')
    parser.add_argument('--exit-on-close',action='store_true')
    args = parser.parse_args()
    running = existing_unreal()
    if running:
        parser.error('Another Unreal is running; finish it before this launch: '+json.dumps(running))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = (args.output or DEFAULT_OUTPUT/'environment-launches'/stamp).resolve()
    output.mkdir(parents=True, exist_ok=False)
    command = native_command(layout=args.layout, port=args.port, output=output, visible=args.visible,headless=args.headless,
                             realtime=args.realtime,exit_on_close=args.exit_on_close)
    manifest = {'command': command, 'port': args.port,
                'layout_sha256': hashlib.sha256(args.layout.read_bytes()).hexdigest() if args.layout else None}
    (output/'launch.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Environment endpoint: http://127.0.0.1:'+str(args.port), flush=True)
    print('Evidence: '+str(output), flush=True)
    startup = None
    if os.name == 'nt' and not args.visible:
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    with (output/'stdout.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, startupinfo=startup,
                                   env={**os.environ,'METARESCUE_OUTPUT':str(DEFAULT_OUTPUT)})
        try:
            code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            code = process.wait(timeout=30)
            manifest['stopped_by_owner'] = True
    manifest['exit_code'] = code
    (output/'launch.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
