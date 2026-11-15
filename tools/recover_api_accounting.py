"""Recover earlier API metadata from preserved evidence, without making requests."""
from copy import deepcopy
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from controller.ai import LiveBudget,file_lock,atomic_json
from controller.accounting import TARIFF,normalize_usage,estimate_cost


def recover(directory,budget):
    traces=[json.loads(line) for line in (directory/'controller-planning.jsonl').open(encoding='utf-8')]
    verification=json.loads((directory/'verification.json').read_text(encoding='utf-8'))
    requests={r['request_id']:r for r in traces if r['type']=='ai_request' and r['mode']=='LIVE'}
    responses={r['request_id']:r for r in traces if r['type'] in ('ai_response','ai_error')}
    effects={r['request_id']:r for r in traces if r['type']=='local_action_applied'}
    commands={};completed=set()
    for line in (directory/'http.jsonl').open(encoding='utf-8'):
        exchange=json.loads(line)
        if exchange['kind']!='http_exchange':continue
        if exchange.get('body'):
            body=json.loads(exchange['body'])
            for index,command in enumerate(body.get('commands',())):
                for reqid,effect in effects.items():
                    if (command.get('agent_id')==effect['agent_id'] and command.get('action')=='follow_route' and
                        command.get('parameters',{}).get('waypoints')==effect.get('route')):
                        commands[reqid]=(body['decision_id'],index,command['agent_id'])
        if exchange.get('response'):
            response=json.loads(exchange['response'])
            for command in response.get('command_results',()):
                if command['execution_status']=='completed':completed.add((command['decision_id'],command['command_index'],command['agent_id']))
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output=budget.accounting_dir/'recoveries'/stamp;output.mkdir(parents=True,exist_ok=False)
    changed=[]
    with file_lock(budget.path.with_suffix(budget.path.suffix+'.lock')):
        raw=budget.path.read_bytes();data=budget._read();used=data['used'];ids=[r['id'] for r in data['requests']]
        (output/'ledger-before.json').write_bytes(raw)
        for row in data['requests']:
            request=requests.get(row['request_id']);response=responses.get(row['request_id'])
            if request is None or response is None or 'recovery' in row or 'normalized_usage' in row:continue
            if row['episode_id']!=request['episode_id']:raise ValueError('Episode mismatch in recovery evidence')
            result=response.get('result') or {};model=result.get('model')
            row.update(mode='LIVE',provider='deepseek',returned_model=model,requested_model=None,
                logical_request_id=row['request_id'],attempt=1,retry_of=None,backoff_s=None,
                context={'run_id':directory.name,'purpose':'native_acceptance','policy':verification.get('algorithm_pair')},
                usage_raw=None,usage_raw_unknown_reason='Original full usage/cache details were not saved before ADD-07.',
                request_settings=None,request_settings_unknown_reason='Not recorded by the earlier transport.',
                normalized_usage=normalize_usage(row.get('usage')),tariff=deepcopy(TARIFF),
                api_response_id=result.get('api_request_id'),http_status=200 if result else None,
                response_received=True if result else None,
                recovery={'version':'pre-ADD07-native-v1','evidence_directory':str(directory),
                    'trace_sha256':hashlib.sha256((directory/'controller-planning.jsonl').read_bytes()).hexdigest(),
                    'unknown_fields':['requested_model','raw_cache_usage','request_settings','provider_billing']})
            row['cost']={**estimate_cost(row['normalized_usage'],timestamp=row['reserved_utc'],model=model),
                         'reconstructed':True,'usage_completeness':'saved_numeric_subset',
                         'pricing_note':'First retrospective estimate using the official tariff checked on the same date; not a debit.'}
            accepted=response.get('validated',False);reason=response.get('rejection_reason',response.get('reason'))
            outcome={'json_valid':True if result else None,'schema_valid':not bool(reason and reason.startswith('AI_SCHEMA_INVALID')) if result else None,
                     'envelope_valid':accepted,'controller_validated':accepted,'controller_applied':False,
                     'physical_application':None,'rejection_reason':reason}
            if result and result['proposal']['action']=='KEEP':outcome['physical_application']='not_requested_keep'
            if row['request_id'] in effects:
                outcome['controller_applied']=True
                command=commands.get(row['request_id'])
                if command:
                    outcome['related_command_id']=command[0]+':'+str(command[1])
                    outcome['physical_application']='confirmed' if command in completed else 'not_confirmed'
            row['outcome']=outcome;changed.append(row['id'])
        if used!=data['used'] or ids!=[r['id'] for r in data['requests']]:raise AssertionError('Recovery changed the request counter')
        if changed:budget._save(data)
        after=budget.path.read_bytes()
    proof={'format':'metarescue.api-recovery.v1','changed_tickets':changed,'used_before':used,'used_after':data['used'],
           'ticket_order_preserved':ids==[r['id'] for r in data['requests']],
           'before_sha256':hashlib.sha256(raw).hexdigest(),'after_sha256':hashlib.sha256(after).hexdigest(),
           'new_api_requests':0,'source':str(directory)}
    atomic_json(output/'proof.json',proof)
    report=budget.report(output/'report',run_id=directory.name)
    return {'proof':str(output/'proof.json'),'report':report['directory'],'used':data['used'],'changed':len(changed)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    parser.add_argument('--budget',type=Path,default=Path('D:/MetaRescue-output/ai-budget.json'))
    args=parser.parse_args();print(json.dumps(recover(args.directory,LiveBudget(args.budget))))
    return 0


if __name__=='__main__':raise SystemExit(main())
