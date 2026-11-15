"""Replay saved public decisions against a fresh native Unreal world."""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from analytics.metrics import distribution
from contracts.protocol import ProtocolError, encode
from controller.ai import file_lock, load_replay
from controller.ai_contracts import AIRequest
from controller.client import EnvironmentClient, TransportFailure
from environment.main import DEFAULT_OUTPUT, existing_unreal, native_command
from tools.native_archive import IndexedRecords, file_sha256, verify_archive
from tools.run_mission import hashes


def recorded_replies(journal):
    """Match exact saved semantic requests and keep original delay/tickets."""
    replay = load_replay(journal)
    requests = {}
    replies = []
    gzip_journal=journal.suffix=='.gz'
    opener=gzip.open if gzip_journal else open
    with opener(journal,'rt',encoding='utf-8') as file:
        for line in file:
            if gzip_journal and '"record_type":"planning_trace"' not in line[:90]:
                continue
            row=json.loads(line)
            record=row['payload'] if gzip_journal else row
            kind = record.get('type')
            if kind == 'ai_request':
                requests[record['request_id']] = AIRequest(record['role'],encode(record['input']))
            elif kind in ('ai_response','ai_error'):
                request = requests[record['request_id']]
                result = replay.complete(request)
                assert result['recorded_delay_model_s']==record['delay_model_s']
                if kind == 'ai_response':
                    assert result.get('proposal')==record['result'].get('proposal')
                else:
                    assert result['replay_error']==record['reason']
                replies.append({'request_id':record['request_id'],'role':record['role'],
                                'delay_model_s':result['recorded_delay_model_s'],'budget_ticket':result.get('budget_ticket'),
                                'replay_key':record['replay_key'],'outcome':kind})
    return replies


def recorded_steps(archive):
    """Stream accepted native replay rows and validate their request/response identity."""
    for row in IndexedRecords(archive/'replay').json_records():
        if row['http_status']!=200:
            continue
        decision=json.loads(base64.b64decode(row['request_body_base64'],validate=True))
        response=json.loads(row['response'])
        if (decision['decision_id']!=row['decision_id'] or
            any(decision[key]!=response[key] for key in ('episode_id','request_id'))):
            raise ValueError('Native replay request and response identities differ')
        yield decision,response


def indexed_snapshot(archive, *, final=False):
    store = IndexedRecords(archive/'truth')
    if final:
        snapshot = next(store.json_records(start=len(store)-1))
        assert snapshot['payload']['phase']=='close'
        return snapshot
    return next(row for row in store.json_records() if row['record_type']=='truth_snapshot')


def pose_errors(left,right):
    a = {row['id']:row['position'] for row in left}
    b = {row['id']:row['position'] for row in right}
    if a.keys()!=b.keys() or any((a[key] is None)!=(b[key] is None) for key in a):
        raise ValueError('Replay participant identities or observation visibility changed')
    return [math.dist(a[key],b[key]) for key in a if a[key] is not None]


def terminal_comparison(source,replay):
    def signature(archive):
        payload = indexed_snapshot(archive,final=True)['payload']
        targets = sorted((t['id'],t['discovered'],t['rescued']) for t in payload['targets'])
        contacts = sorted((a['id'],a['physical']['vehicle_contacts']) for a in payload['agents'])
        handovers = [r['time'] for r in IndexedRecords(archive/'public').json_records()
                     if r['record_type']=='command_result' and r['payload']['action']=='handover' and
                     r['payload']['execution_status']=='completed']
        return targets,contacts,handovers
    left,right = signature(source),signature(replay)
    same = len(left[2])==len(right[2])
    errors = [abs(a-b) for a,b in zip(left[2],right[2])]
    return {'same_target_states':left[0]==right[0],'same_vehicle_contacts':left[1]==right[1],
            'same_handover_count':same,'handover_error_s':distribution(errors),
            'maximum_handover_error_s':max(errors,default=0.)}


def run(mission,output,port):
    original = json.loads((mission/'manifest.json').read_bytes())
    source = Path(original['native_archive'])
    source_layout = mission/'world.private.json'
    source_audit = json.loads((mission/'native-archive-verification.json').read_bytes())
    if original['state']!='complete' or not source_audit['passed'] or not original['frozen_inputs_preserved']:
        raise ValueError('Source mission lacks a verified native archive')
    output.mkdir(parents=True,exist_ok=False)
    layout = output/'world.private.json'
    layout.write_bytes(source_layout.read_bytes())
    assert file_sha256(source_layout)==file_sha256(layout)
    before = hashes(layout)
    result = {'passed':False,'source_mission':str(mission),'source_archive':str(source),
              'layout_sha256':file_sha256(layout),'original_terminal_status':original['episode_status'],
              'tolerances':{'initial_pose_m':.001,'p95_public_pose_m':.20,'max_public_pose_m':1.,
                            'handover_time_s':.5,'terminal_time_s':.5}}
    command = native_command(layout=layout,port=port,output=output,headless=True,exit_on_close=True)
    startup = subprocess.STARTUPINFO() if os.name=='nt' else None
    if startup:
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    episode_id = None
    with (output/'stdout.log').open('x',encoding='utf-8') as log:
        process = subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,startupinfo=startup,
                                   env={**os.environ,'METARESCUE_OUTPUT':str(DEFAULT_OUTPUT)})
        client = EnvironmentClient(f'http://127.0.0.1:{port}',timeout_s=70)
        try:
            deadline = time.monotonic()+240
            while time.monotonic()<deadline:
                if process.poll() is not None:
                    raise RuntimeError(f'Unreal exited at startup with {process.returncode}')
                try:
                    if client.health()['status']=='ready':break
                except (ProtocolError,TransportFailure,OSError):
                    pass
                time.sleep(.25)
            else:
                raise TimeoutError('Native replay readiness timeout')
            seed = json.loads(layout.read_bytes())['settings']['seed']
            response = client.reset(seed=seed)
            episode_id = response['episode_id']
            initial = indexed_snapshot(source)
            initial_error = max(pose_errors(initial['payload']['agents'],response['observation']['agents']),default=0.)
            errors,clock_error = [],0.
            count = 0
            for decision,expected in recorded_steps(source):
                decision['episode_id'] = episode_id
                decision['time'] = response['time']
                decision['explanation']['observation_refs'] = [response['observation']['request_id']]
                response = client.step(decision)
                count += 1
                clock_error = max(clock_error,abs(expected['time']-response['time']))
                errors.extend(pose_errors(expected['observation']['agents'],response['observation']['agents']))
                if count%60==0:print(json.dumps({'replayed_steps':count,'model_s':response['time']}),flush=True)
            assert count>0
            result.update(episode_id=episode_id,steps=count,initial_max_pose_error_m=initial_error,
                          public_pose_error_m=distribution(errors),maximum_step_time_error_s=clock_error,
                          actual_terminal_status=response['status'],
                          metrics_match=original['metrics']==response['observation']['metrics'])
            client.close(episode_id)
            result['native_exit_code'] = process.wait(timeout=30)
            replay = DEFAULT_OUTPUT/'core-runs'/episode_id
            result['archive'] = verify_archive(replay)
            checks = terminal_comparison(source,replay)
            result['physical'] = checks
            result['passed'] = (result['native_exit_code']==0 and result['archive']['passed'] and
                result['actual_terminal_status']==original['episode_status'] and result['metrics_match'] and
                checks['same_target_states'] and checks['same_vehicle_contacts'] and checks['same_handover_count'] and
                checks['maximum_handover_error_s']<=.5 and clock_error<=.5 and initial_error<=.001 and
                result['public_pose_error_m']['p95']<=.20 and result['public_pose_error_m']['maximum']<=1.)
        except BaseException as error:
            result.update(error_type=type(error).__name__,error=str(error))
            raise
        finally:
            if process.poll() is None:
                try:
                    if episode_id:client.close(episode_id)
                    process.wait(timeout=8)
                except (ProtocolError,TransportFailure,OSError,subprocess.TimeoutExpired):
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=15)
            client.disconnect()
            result['frozen_inputs_preserved']=before==hashes(layout)
            result['passed']=result['passed'] and result['frozen_inputs_preserved']
            (output/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result['passed']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--port',type=int,default=8130)
    parser.add_argument('--ai-inputs-only',action='store_true')
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    if args.ai_inputs_only:
        journal=source if source.is_file() else source/'controller/controller.jsonl.gz'
        replies = recorded_replies(journal)
        with args.output.open('x',encoding='utf-8') as stream:
            json.dump({'matched_responses_and_errors':len(replies),'replies':replies},stream,ensure_ascii=False,indent=2)
        return 0 if replies else 1
    with file_lock(DEFAULT_OUTPUT/'locks/unreal-owner.lock'):
        if existing_unreal():raise RuntimeError('Another Unreal is running')
        return 0 if run(source,args.output.resolve(),args.port) else 1


if __name__=='__main__':
    raise SystemExit(main())
