"""Join public wire poses to AI requests, replies and actual controller effects."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from contracts.protocol import strict_json,MAX_RESPONSE_BYTES


def analyze(directory):
    traces=[json.loads(line) for line in (directory/'controller-planning.jsonl').open(encoding='utf-8')]
    requests={t['request_id']:t for t in traces if t['type']=='ai_request'}
    episodes={r['episode_id'] for r in requests.values()};poses={}
    for line in (directory/'http.jsonl').open(encoding='utf-8'):
        record=json.loads(line)
        if record['kind']!='http_exchange' or not record.get('response'):continue
        response=strict_json(record['response'],maximum_bytes=MAX_RESPONSE_BYTES)
        observation=response.get('observation',response)
        if observation.get('episode_id') not in episodes or 'agents' not in observation:continue
        poses[(observation['episode_id'],round(observation['time'],7))]={a['id']:a for a in observation['agents']}
    rows=[]
    for trace in traces:
        if trace['type'] not in ('ai_response','ai_error'):continue
        request=requests[trace['request_id']];data=request['input'];start=data['based_on_time']
        finish=start+trace['delay_model_s'];episode=request['episode_id']
        before=poses.get((episode,round(start,7)),{});after=poses.get((episode,round(finish,7)),{})
        movements=[]
        for aid,a in before.items():
            if aid==request.get('agent_id') or aid not in after or not a.get('position') or not after[aid].get('position'):continue
            b=after[aid];pa,pb=a.get('physical',{}),b.get('physical',{})
            same_command=bool(pa.get('active_command_id')) and pa.get('active_command_id')==pb.get('active_command_id')
            movements.append({'agent_id':aid,'distance_between_samples_m':math.dist(a['position'],b['position']),
                              'same_inflight_command':same_command,'status_before':a['status'],'status_after':b['status']})
        rows.append({'request_id':trace['request_id'],'role':trace['role'],'agent_id':request.get('agent_id'),
            'start_model_s':start,'reply_model_s':finish,'delay_model_s':trace['delay_model_s'],
            'api_latency_s':trace.get('result',{}).get('latency_s'),'mode':trace.get('result',{}).get('mode',request['mode']),
            'validated':trace.get('validated',False),'rejection_reason':trace.get('rejection_reason',trace.get('reason')),
            'other_agent_movements':movements,'unaffected_motion_verified':any(
                m['same_inflight_command'] and m['distance_between_samples_m']>.2 for m in movements)})
    return {'format':'metarescue.ai-causality.v1','scope':'delivered public poses, not truth or interpolated motion',
        'requests':rows,'local_wait_without_swarm_freeze':any(r['role']=='local' and r['unaffected_motion_verified'] for r in rows),
        'applied_effects':[t for t in traces if t['type'] in ('local_action_applied','global_strategy_applied')],
        'input_sha256':{name:hashlib.sha256((directory/name).read_bytes()).hexdigest()
                        for name in ('http.jsonl','controller-planning.jsonl')}}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    args=parser.parse_args();result=analyze(args.directory)
    path=args.directory/'ai-causality.json'
    with path.open('x',encoding='utf-8') as handle:json.dump(result,handle,ensure_ascii=False,indent=2)
    print(json.dumps({'path':str(path),'requests':len(result['requests']),
                      'local_wait_without_swarm_freeze':result['local_wait_without_swarm_freeze']}))
    return 0


if __name__=='__main__':raise SystemExit(main())
