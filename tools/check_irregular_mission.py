"""Join autonomous 3D rescue outcomes, acknowledged commands and loaded movement."""
from collections import defaultdict
import argparse
import gzip
import json
import math
from pathlib import Path

from tools.native_archive import IndexedRecords, file_sha256


def read(path):
    return json.loads(path.read_bytes())


def verify(directory):
    mission=read(directory/'manifest.json')
    archive=read(directory/'native-archive-verification.json')
    controller=read(directory/'controller/manifest.json')
    world=read(directory/'world.private.json')
    native=Path(mission['native_archive'])
    assert mission['state']=='complete' and mission['episode_status']=='success'
    assert mission['frozen_inputs_preserved'] and mission['native_exit_code']==mission['controller_exit_code']==0
    assert archive['passed'] and archive['episode_id']==controller['episode_id']
    assert file_sha256(directory/'world.private.json')==mission['source_layout']['sha256']
    journal=directory/'controller'/controller['journal']
    assert file_sha256(journal)==controller['journal_sha256']
    with gzip.open(journal,'rt',encoding='utf-8') as stream:
        assert sum(1 for line in stream if json.loads(line))==controller['records']

    commands={};results=defaultdict(list);handovers={}
    for entry in IndexedRecords(native/'public').json_records():
        row=entry['payload'];kind=entry['record_type']
        if kind=='observation':
            assert not {'people','event_model','settings'}&set(row['metaevolution']['announced_map'])
        elif kind=='decision':
            for index,command in enumerate(row['commands']):
                if command['action']=='follow_route':
                    commands[f"{row['decision_id']}:{index}"]=command
        elif kind=='command_result' and row['delivery_status']=='delivered':
            results[f"{row['decision_id']}:{row['command_index']}"].append(row)
        elif kind=='target_state_changed' and row['evacuation_state']=='evacuated':
            assert row['id'] not in handovers,'duplicate handover'
            handovers[row['id']]={'time_s':entry['time'],'trace_id':entry['trace_id']}

    loaded=defaultdict(list)
    for entry in IndexedRecords(native/'truth').json_records():
        if entry['record_type']!='agent_telemetry':
            continue
        for agent in entry['payload']['agents']:
            physical=agent['physical']
            cargo,command=physical['cargo_target_id'],physical['active_command_id']
            if cargo and command in commands and command in results:
                loaded[cargo,command].append((agent['position'],physical['distance_m']))

    assert set(handovers)=={f"person-{p['id']}" for p in world['people']}
    for target,delivery in handovers.items():
        legs=[]
        for (cargo,command),samples in loaded.items():
            if cargo!=target:
                continue
            diagonal=0.
            for (a,_),(b,_) in zip(samples,samples[1:]):
                dx,dy=abs(a[0]-b[0]),abs(a[1]-b[1])
                step=math.hypot(dx,dy)
                if step>.06 and min(dx,dy)>.18*step:
                    diagonal+=step
            command_results=results[command]
            assert any(row['execution_status']=='in_progress' and row['validation_status']=='accepted'
                       for row in command_results),command
            legs.append({'command_id':command,'distance_m':samples[-1][1]-samples[0][1],
                         'sampled_diagonal_m':diagonal,'samples':len(samples),
                         'first_position_m':samples[0][0],'last_position_m':samples[-1][0],
                         'agent_id':commands[command]['agent_id'],'command_results':command_results,
                         'planned_waypoints_m':commands[command]['parameters']['waypoints']})
        delivery.update(legs=legs,loaded_distance_m=sum(leg['distance_m'] for leg in legs),
                        sampled_diagonal_m=sum(leg['sampled_diagonal_m'] for leg in legs))
        assert delivery['loaded_distance_m']>100 and delivery['sampled_diagonal_m']>12,target
        assert any(row['execution_status']=='completed' and row['updated_at']<delivery['time_s']
                   for leg in legs for row in leg['command_results']),target
    return {'passed':True,'scope':'autonomous physical 250m rescue and recorded oblique loaded travel',
            'city_format':world['format'],'episode_id':archive['episode_id'],'time_s':archive['time'],
            'deliveries':handovers,'controller_journal_sha256':controller['journal_sha256'],
            'controller_records':controller['records'],'source_layout_sha256':mission['source_layout']['sha256'],
            'rendering':mission['rendering']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mission',type=Path)
    args=parser.parse_args()
    proof=verify(args.mission)
    with (args.mission/'irregular-verification.json').open('x',encoding='utf-8') as stream:
        json.dump(proof,stream,indent=2)
    print(json.dumps({target:{k:round(v,2) for k,v in row.items() if isinstance(v,(int,float))}
                      for target,row in proof['deliveries'].items()}))
