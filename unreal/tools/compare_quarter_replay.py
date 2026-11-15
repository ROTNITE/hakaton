"""Compare deterministic event tapes from two real runs; never compare Chaos bits."""
from pathlib import Path
import argparse
import json
from check_quarter_v3_run import read_json,read_rows


def compare(first,second):
    first,second=Path(first),Path(second)
    a=read_json(first/'Telemetry/environment-truth.json')
    b=read_json(second/'Telemetry/environment-truth.json')
    for field in ['seed','mode','window_s','horizon_s','probabilities_pct','dynamic_cell_size_m']:
        assert a[field]==b[field],('different experiment input',field)
    assert a['event_tape']==b['event_tape'],'same seed produced different event tape'
    def executed(folder):
        return [{k:v for k,v in row.items() if k!='world_revision'} for row in read_rows(folder/'Telemetry/events.jsonl')
                if row['type'] in {'environment_event','environment_attempt_rejected'}]
    assert executed(first)==executed(second),'actual executed event streams differ'
    before,after=read_json(first/'evidence-run.json'),read_json(second/'evidence-run.json')
    for field in ['time_step_mode','requested_fixed_fps']:
        assert before.get(field,'real_time' if field=='time_step_mode' else 0)==after.get(field,'real_time' if field=='time_step_mode' else 0),('different clock profiles',field)
    assert before['source_hashes_before']==after['source_hashes_before'],'runs used different source/binary/map revisions'
    for folder in [first,second]:assert read_json(folder/'verification.json')['passed'],'one native run failed verification'
    result={'passed':True,'scope':'same-input event tape and actual event stream; Chaos not compared',
            'first':str(first.resolve()),'second':str(second.resolve()),'seed':a['seed'],'tape_events':len(a['event_tape'])}
    (second/'replay-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('first',type=Path);parser.add_argument('second',type=Path)
    args=parser.parse_args();compare(args.first,args.second)
