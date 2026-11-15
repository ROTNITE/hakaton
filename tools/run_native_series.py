"""Execute a frozen native comparison in resumable, strictly serial order."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from controller.ai import file_lock
from environment.main import DEFAULT_OUTPUT,existing_unreal
from tools.native_archive import file_sha256
from tools.run_mission import hashes
from tools.series_plan import FORMAT,FAMILIES,OPTIMIZER_SEEDS,POLICIES,digest,json_bytes,tape_digest


NAME=re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,80}\Z')


def validate_design(plan_path):
    data=json.loads(plan_path.read_bytes())
    if data.get('format')!=FORMAT or data.get('renderer')!='null_rhi':
        raise ValueError('Unknown native series format')
    worlds={}
    for entry in data['worlds']:
        identifier=entry['id']
        if not NAME.fullmatch(identifier) or identifier in worlds:raise ValueError('Invalid or repeated world ID')
        path=(plan_path.parent/entry['private_layout']).resolve(strict=True)
        if not path.is_relative_to(plan_path.parent):raise ValueError('Series layout path escapes its directory')
        world=json.loads(path.read_bytes())
        if file_sha256(path)!=entry['layout_sha256'] or tape_digest(world)!=entry['external_tape_sha256']:
            raise ValueError(f'Frozen world or external tape changed for {identifier}')
        if world['settings']['seed']!=entry['seed'] or world['settings']['horizon']!=data['comparison_horizon_s']:
            raise ValueError(f'World settings changed for {identifier}')
        worlds[identifier]=(entry,path)
    if len(worlds)!=30 or sorted(e['family'] for e,_ in worlds.values())!=[f'S{f}' for f in range(1,len(FAMILIES)+1) for _ in range(5)]:
        raise ValueError('Exactly five maps per S1..S6 are required')
    policies={tag:(policy,mode,scope) for tag,policy,mode,scope in POLICIES}
    expected={(world,seed,tag) for world in worlds for seed in OPTIMIZER_SEEDS for tag in policies}
    combinations=set();ids=set()
    for case in data['runs']:
        identifier=case['id'];key=(case['world'],case['optimizer_seed'],case['policy_id'])
        if (not NAME.fullmatch(identifier) or identifier in ids or key not in expected or key in combinations or
            (case['policy'],case['ai_mode'],case['ai_scope'])!=policies.get(case['policy_id'])):
            raise ValueError(f'Unexpected comparison row {identifier}')
        ids.add(identifier);combinations.add(key)
    if combinations!=expected:raise ValueError('Comparison design is missing rows')
    return worlds,data['runs']


def runtime_hashes(world):
    path=world.resolve()
    return {name:sha for name,sha in hashes(path).items() if Path(name)!=path}


def read_complete(row_path,expected,*,check_archives=True):
    candidates=sorted(row_path.glob('attempt-*.json'))
    for path in candidates:
        row=json.loads(path.read_bytes())
        if row.get('complete') is not True:continue
        if any(row.get(key)!=value for key,value in expected.items()):
            raise ValueError(f'Completed evidence differs from frozen row {row_path.name}')
        manifest=Path(row['manifest'])
        if not manifest.is_file() or file_sha256(manifest)!=row['manifest_sha256']:
            raise ValueError(f'Completed run manifest changed for {row_path.name}')
        if check_archives:
            metadata=json.loads(manifest.read_bytes())
            archive=Path(metadata['native_archive'])
            audit=manifest.with_name('native-archive-verification.json')
            if not audit.is_file() or file_sha256(audit)!=row.get('archive_verification_sha256'):
                raise ValueError(f'Archive verification report changed for {row_path.name}')
            verification=json.loads(audit.read_bytes())
            if (verification.get('passed') is not True or verification['status']!=metadata['episode_status'] or
                    verification['episode_id']!=archive.name):
                raise ValueError(f'Archive verification differs from terminal outcome for {row_path.name}')
            for stream,details in verification['files'].items():
                for suffix in ('records','index'):
                    key='data_sha256' if suffix=='records' else 'index_sha256'
                    if file_sha256(archive/(stream+'.'+suffix))!=details[key]:
                        raise ValueError(f'{stream}.{suffix} changed for {row_path.name}')
        return row
    return None


def run(plan_path,*,limit=0,cases=(),port=8130,health_port=8131):
    plan_path=plan_path.resolve(strict=True)
    worlds,rows=validate_design(plan_path)
    selection=set(cases)
    unknown=selection-{case['id'] for case in rows}
    if unknown:raise ValueError('Unknown series rows: '+', '.join(sorted(unknown)))
    output=plan_path.parent/'execution';output.mkdir(exist_ok=True)
    plan_hash=file_sha256(plan_path)
    first_world=next(iter(worlds.values()))[1]
    inputs=runtime_hashes(first_world)
    series_tools={str(path):file_sha256(path) for path in (Path(__file__).resolve(),ROOT/'tools/series_plan.py')}
    frozen={'plan_sha256':plan_hash,'runtime_sha256':digest(inputs),'runtime_inputs':inputs,'series_tools':series_tools}
    frozen_path=output/'frozen.json'
    if frozen_path.exists():
        if json.loads(frozen_path.read_bytes())!=frozen:
            raise ValueError('Cannot resume this series with different native/controller inputs')
    else:
        with frozen_path.open('xb') as stream:stream.write(json_bytes(frozen))
    executed=completed=failed=0
    for case in rows:
        layout,path=worlds[case['world']]
        row_output=output/case['id'];row_output.mkdir(exist_ok=True)
        expected={**case,'layout_sha256':layout['layout_sha256'],'external_tape_sha256':layout['external_tape_sha256'],
                  'runtime_sha256':frozen['runtime_sha256']}
        if read_complete(row_output,expected):
            completed+=1;continue
        if selection and case['id'] not in selection:continue
        if limit and executed>=limit:continue
        if existing_unreal():raise RuntimeError('Another Unreal is active at the next serial boundary')
        if (file_sha256(plan_path)!=plan_hash or file_sha256(path)!=layout['layout_sha256'] or runtime_hashes(path)!=inputs or
            any(file_sha256(tool)!=checksum for tool,checksum in series_tools.items())):
            raise RuntimeError('Frozen inputs changed before the next native run')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        name='series-'+case['id']+'-'+stamp
        attempt=row_output/('attempt-'+stamp+'.json')
        native_manifest=DEFAULT_OUTPUT/'missions'/name/'manifest.json'
        row={**expected,'started_utc':datetime.now(timezone.utc).isoformat(),'complete':False,
             'run_name':name,'manifest':str(native_manifest)}
        attempt.write_bytes(json_bytes(row))
        started=time.perf_counter()
        cmd=[sys.executable,'-B','-X','utf8',str(ROOT/'tools/run_mission.py'),
             '--layout',str(path),'--name',name,'--headless','--port',str(port),'--health-port',str(health_port),
             '--optimizer-seed',str(case['optimizer_seed']),'--policy',case['policy'],
             '--ai-mode',case['ai_mode'],'--ai-scope',case['ai_scope']]
        # All three evolutionary policies use the same scenario library.
        if case['policy']=='nsga2_nsga2':cmd.append('--contest-coordination')
        with (row_output/('attempt-'+stamp+'.log')).open('x',encoding='utf-8') as log:
            process=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=False)
        executed+=1
        row.update(returncode=process.returncode,ended_utc=datetime.now(timezone.utc).isoformat(),
                   wall_elapsed_s=time.perf_counter()-started)
        if native_manifest.is_file():
            manifest=json.loads(native_manifest.read_bytes())
            native_inputs={key:value for key,value in manifest.get('frozen_inputs',{}).items() if Path(key)!=Path(manifest.get('layout',''))}
            verification=native_manifest.with_name('native-archive-verification.json')
            verified=verification.is_file() and json.loads(verification.read_bytes()).get('passed') is True
            row.update(complete=process.returncode==0 and manifest.get('state')=='complete' and verified and
                manifest.get('frozen_inputs_preserved') is True and native_inputs==inputs,
                episode_status=manifest.get('episode_status'),metrics=manifest.get('metrics'),
                error=manifest.get('error'),manifest_sha256=file_sha256(native_manifest),
                archive_verification_sha256=file_sha256(verification) if verified else None)
            if not row['complete'] and not row['error']:
                row['error']='Mission archive, terminal result or frozen runtime inputs failed verification'
        else:row['error']='Mission runner did not create a manifest'
        temporary=attempt.with_suffix('.part')
        temporary.write_bytes(json_bytes(row));temporary.replace(attempt)
        completed+=int(row['complete']);failed+=int(not row['complete'])
        print(json.dumps({'row':case['id'],'complete':row['complete'],'completed':completed,
                          'planned':len(rows),'run':name,'wall_s':round(row['wall_elapsed_s'],3),
                          'error':row.get('error')}),flush=True)
    result={'planned':len(rows),'complete':completed,'new_attempts':executed,'new_incomplete':failed}
    print(json.dumps(result),flush=True)
    return 0 if completed==len(rows) else 1 if failed else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path);parser.add_argument('--limit',type=int,default=0)
    parser.add_argument('--case',action='append',default=[],help='Select a declared row, keeping its original series identity')
    parser.add_argument('--port',type=int,default=8130);parser.add_argument('--health-port',type=int,default=8131)
    args=parser.parse_args()
    if args.limit<0 or any(not 1024<=port<=65535 for port in (args.port,args.health_port)) or args.port==args.health_port:
        parser.error('Invalid batch limit or ports')
    with file_lock(args.plan.resolve().parent/'series.lock'):
        raise SystemExit(run(args.plan,limit=args.limit,cases=args.case,port=args.port,health_port=args.health_port))
