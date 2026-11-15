"""Open the native mission setup. Exactly one Unreal; controller attaches later."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from controller.ai import atomic_json,file_lock
from controller.health import require_port_available
from environment.main import DEFAULT_OUTPUT,PACKAGED_GAME,existing_unreal,native_command
from tools.product_session import SESSION_FORMAT,parse_request
from tools.run_mission import hashes
from tools.native_archive import file_sha256
from tools.analytics_service import available_port,ensure_analytics


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',action='store_true')
    parser.add_argument('--offscreen',action='store_true',help='Rendered acceptance only; UI remains native')
    parser.add_argument('--configuration',type=Path,help='Optional complete initial UI preset')
    parser.add_argument('--port',type=int,default=8130)
    parser.add_argument('--health-port',type=int,default=8131)
    parser.add_argument('--analytics-port',type=int)
    args=parser.parse_args()
    ports=[p for p in (args.port,args.health_port,args.analytics_port) if p is not None]
    if len(set(ports))!=len(ports) or any(not 1024<=port<=65535 for port in ports):
        parser.error('Invalid/conflicting ports')
    with file_lock(DEFAULT_OUTPUT/'locks/unreal-owner.lock'):
        if existing_unreal():raise RuntimeError('Another Unreal is running; close it before opening the mission application')
        for port in (args.port,args.health_port):require_port_available(port)
        if args.analytics_port is None:args.analytics_port=available_port(DEFAULT_OUTPUT,exclude=ports)
        if args.build:
            if PACKAGED_GAME.is_file():parser.error('Build the Windows candidate from the source checkout')
            subprocess.run([sys.executable,'-B','-X','utf8','unreal/launch.py','--quarter','--build'],cwd=ROOT,check=True)
        ui_assets=ROOT/'unreal/MetaRescue/Content/RescueAssets/UIV1'
        if not PACKAGED_GAME.is_file() and any(not (ui_assets/(name+'.uasset')).is_file() for name in ('M_TelemetryRibbon','M_KnowledgeBoard')):
            from tools.prepare_mission_ui import main as prepare_ui
            if prepare_ui(lease_owned=True):raise RuntimeError('Mission display materials could not be prepared')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        directory=(DEFAULT_OUTPUT/'product-sessions'/stamp).resolve();directory.mkdir(parents=True,exist_ok=False)
        session={'format':SESSION_FORMAT,'id':uuid.uuid4().hex,'workspace':str(directory),'source_root':str(ROOT),
                 'python':sys.executable,'port':args.port,'health_port':args.health_port,
                 'analytics_port':args.analytics_port,'state':'starting','native_pid':None}
        if args.configuration:session['configuration']=parse_request(json.loads(args.configuration.read_text(encoding='utf-8-sig')))
        path=directory/'session.json';atomic_json(path,session)
        session['analytics']=ensure_analytics(directory,DEFAULT_OUTPUT,port=args.analytics_port)
        command=native_command(output=directory,port=args.port,visible=not args.offscreen)
        command+=['-MRProductSession='+str(path)]
        session['command']=command
        marker=directory/'initial-configuration.json';atomic_json(marker,session.get('configuration',{}))
        def inputs():
            values=hashes(marker)
            for name in ('run_product.py','product_session.py','native_process.py','analytics_service.py'):
                file=ROOT/'tools'/name;values[str(file)]=file_sha256(file)
            for folder in ('analytics','web'):
                for file in (ROOT/folder).rglob('*'):
                    if file.is_file() and file.suffix not in ('.pyc',):values[str(file)]=file_sha256(file)
            return values
        before=inputs();atomic_json(directory/'frozen-inputs.json',before)
        try:
            with (directory/'native-stdout.log').open('w',encoding='utf-8') as log:
                process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                                         env={**os.environ,'METARESCUE_OUTPUT':str(DEFAULT_OUTPUT)})
                session.update(native_pid=process.pid,state='running');atomic_json(path,session)
                print(json.dumps({'workspace':str(directory),'native_pid':process.pid}),flush=True)
                try:session['native_exit_code']=process.wait()
                except KeyboardInterrupt:
                    # Explicit interruption by the owner; preserve unfinished archives.
                    process.terminate();session['native_exit_code']=process.wait(timeout=30)
                    session['interrupted_by_owner']=True
            session['state']='closed'
        finally:
            session['frozen_inputs_preserved']=before==inputs()
            session['ended_utc']=datetime.now(timezone.utc).isoformat();atomic_json(path,session)
        return session['native_exit_code']


if __name__=='__main__':raise SystemExit(main())
