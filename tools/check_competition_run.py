"""Verify actual synthesized phase effects against the controller journal."""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.native_archive import IndexedRecords, file_sha256


def check(directory,expect,*,library=False):
    run=json.loads((directory/'manifest.json').read_bytes())
    assert run['state']=='complete' and run['frozen_inputs_preserved'] and run['native_exit_code']==run['controller_exit_code']==0
    native=Path(run['native_archive'])
    controller=json.loads((directory/'controller/manifest.json').read_bytes())
    journal=directory/'controller'/controller['journal']
    assert file_sha256(journal)==controller['journal_sha256']
    phases={};plans=[];outcome=None;results={}
    with gzip.open(journal,'rt',encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line);value=row['payload'];kind=row['record_type']
            if kind=='decision':
                decision=value['decision']
                if decision['operation']!='keep':plans.append(decision)
            elif kind=='scenario_trace' and value['type']=='scenario_phase_dispatch':
                phases[value['phase']]=(value['decision_id']+':'+str(value['command_indices'][0]),value['time'])
            elif kind=='scenario_trace' and value['type']=='scenario_outcome':outcome=value
            elif kind=='step_response':
                for result in value['command_results']:results[result['command_id']]=result
    assert outcome and outcome['outcome']==expect,outcome
    assert any(row['operation']==('switch' if library else 'synthesize') and
        row['selected_configuration']['scenario_ids']==(['temporary_coalition'] if library else ['relay_briefing_and_aid_v1']) for row in plans)
    assert any(row['operation']=='switch' and row['time']>=outcome['time'] for row in plans)
    if expect=='success':
        assert tuple(phases)==(('position_relay','enable_relay','approach_target','deliver_aid') if library else
                               ('position_relay','enable_relay','brief_executor','approach_target','deliver_aid'))
        assert all(results[identifier]['execution_status']=='completed' for identifier,_ in phases.values())
        for previous,current in zip(phases.values(),tuple(phases.values())[1:]):
            assert results[previous[0]]['updated_at']<=current[1]+1.e-8
    truth={}
    for row in IndexedRecords(native/'truth').json_records():
        kind=row['record_type']
        if kind in ('relay_changed','peer_message_delivered','aid_transferred'):
            truth.setdefault(kind,[]).append(row)
    if expect=='success':
        relay,transfer=(truth[key] for key in ('relay_changed','aid_transferred'))
        assert len(relay)==len(transfer)==1
        assert relay[0]['payload']['command_id']==phases['enable_relay'][0]
        assert transfer[0]['payload']['command_id']==phases['deliver_aid'][0]
        assert transfer[0]['payload']['target_id']==outcome['target_id']
        if library:assert not truth.get('peer_message_delivered')
        else:
            message=truth['peer_message_delivered'];assert len(message)==1
            assert message[0]['payload']['message_id']==phases['brief_executor'][0]
            assert message[0]['time']<transfer[0]['time']
        assert transfer[0]['time']<outcome['time']
    else:
        assert not truth.get('aid_transferred')
        assert any(row['operation']=='switch' and row['selected_configuration']['scenario_ids']==['safe_degradation'] for row in plans)
    report={'verified':True,'scope':'native autonomous '+('library' if library else 'synthesized')+' coalition',
            'run':run['name'],'episode_id':controller['episode_id'],
            'outcome':outcome,'phases':phases,'physical_effects':{key:rows for key,rows in truth.items()},
            'native_episode_status':run['episode_status'],'evacuation_metrics':run['metrics']}
    with (directory/'competition-verification.json').open('x',encoding='utf-8') as stream:
        json.dump(report,stream,indent=2,ensure_ascii=False)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    parser.add_argument('--expect',choices=('success','safe_degradation'),required=True)
    parser.add_argument('--library',action='store_true')
    args=parser.parse_args()
    print(json.dumps(check(args.run,args.expect,library=args.library),ensure_ascii=False))
