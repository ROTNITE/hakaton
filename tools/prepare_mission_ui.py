"""Prepare two code-authored UI materials with the sole Unreal commandlet."""
from datetime import datetime,timezone
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'unreal/tools'))
from controller.ai import file_lock
from environment.main import DEFAULT_OUTPUT,existing_unreal
from run_quarter_validation import source_snapshot


def main(*,lease_owned=False):
    with nullcontext() if lease_owned else file_lock(DEFAULT_OUTPUT/'locks/unreal-owner.lock'):
        if existing_unreal():raise RuntimeError('Finish the current Unreal before material preparation')
        output=DEFAULT_OUTPUT/'checks'/('mission-ui-materials-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        output.mkdir(parents=True,exist_ok=False)
        script=ROOT/'unreal/tools/prepare_mission_ui_assets.py'
        before=source_snapshot();started=time.time()
        engine=Path(os.environ.get('MR_UNREAL_ENGINE',r'C:\Program Files\Epic Games\UE_5.8'))
        command=[str(engine/'Engine/Binaries/Win64/UnrealEditor-Cmd.exe'),str(ROOT/'unreal/MetaRescue/MetaRescue.uproject'),
            '-run=pythonscript','-script='+str(script),'-unattended','-nosplash','-NoSound','-nullrhi','-stdout','-FullStdOutLogOutput',
            '-abslog='+str(output/'engine.log'),'-LocalDataCachePath='+str(DEFAULT_OUTPUT/'cache/ddc')]
        report={'passed':False,'command':command,'input_hashes':before}
        try:
            with (output/'stdout.log').open('w',encoding='utf-8') as log:
                result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            report['native_exit_code']=result.returncode
            if result.returncode:raise RuntimeError('UI material commandlet failed; '+str(output))
            reports=[p for p in (DEFAULT_OUTPUT/'city-assets').glob('*-mission-ui-v1.json') if p.stat().st_mtime>=started]
            if len(reports)!=1:raise ValueError('UI material readback report is missing or ambiguous')
            readback=json.loads(reports[0].read_bytes())
            if len(readback.get('materials',{}))!=2:raise ValueError('Incomplete material readback')
            report.update(passed=True,readback=str(reports[0]),materials=readback['materials'])
        except BaseException as error:
            report.update(error_type=type(error).__name__,error=str(error));raise
        finally:
            report['frozen_inputs_preserved']=before==source_snapshot()
            report['passed']=report['passed'] and report['frozen_inputs_preserved']
            (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
            print(json.dumps({'output':str(output),'passed':report['passed'],'frozen_inputs_preserved':report['frozen_inputs_preserved']}),flush=True)
        return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
