"""Exercise the real C++ HTTP environment using only public controller inputs."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contracts.protocol import ProtocolError, encode, validate_observation
from controller.client import EnvironmentClient, PreparedRequest
from environment.main import DEFAULT_OUTPUT, existing_unreal, native_command
from controller.baselines import FixedWorkflow
from controller.policy import EvolutionPolicy,PAIRS
from controller.ai import DeepSeek,LiveBudget,Mock,Off,load_replay
from controller.ai_policy import SupervisedPolicy
from tools.native_archive import IndexedRecords,verify_archive
from tools import core_contest_check
from tools import core_city_check
from tools import core_event_check
from tools import core_radio_check
from tools import core_resource_check
from tools import core_scenario_check
from tools import core_annex_check
from tools import core_interop_check
from tools import core_archive_check
from tools import core_operator_check


def source_hashes(layout):
    files = list((ROOT/'unreal/MetaRescue/Source').rglob('*'))
    files += list((ROOT/'unreal/MetaRescue/Config').glob('*.ini'))
    for module in ('controller','contracts','environment'):
        files.extend((ROOT/module).rglob('*.py'))
    files += [ROOT/'unreal/MetaRescue/Binaries/Win64/UnrealEditor-MetaRescue.dll',layout,Path(__file__),
              ROOT/'tools/native_archive.py',ROOT/'tools/core_event_check.py',ROOT/'tools/core_resource_check.py',
              ROOT/'tools/core_radio_check.py',ROOT/'tools/core_contest_check.py',ROOT/'tools/core_city_check.py',
              ROOT/'tools/core_scenario_check.py',ROOT/'tools/core_annex_check.py',ROOT/'tools/core_interop_check.py',
              ROOT/'tools/core_archive_check.py',ROOT/'tools/core_operator_check.py']
    content=ROOT/'unreal/MetaRescue/Content'
    files.extend((content/'Scenario').glob('*.json'))
    files.append(content/'Maps/RescueQuarter.umap')
    world=json.loads(layout.read_bytes())
    if world.get('competition'):
        files.extend((content/'RescueAssets/Competition').glob('*.uasset'))
    if world.get('format') in ('rescue-city-2.1','rescue-city-2.2'):
        files.extend((content/'RescueAssets/CityV2').rglob('*.uasset'))
    def checksum(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream,'sha256').hexdigest()
    return {str(p.resolve()): checksum(p)
            for p in files if p.is_file()}


def decision(observation, *, commands=(), operation='keep', selected=None, roles=None):
    plan = observation['metaevolution']['plan']
    accepted = deepcopy(plan['accepted_configuration'])
    assignments = deepcopy(plan['desired_role_assignments'])
    return {'protocol_version': '1.0', 'episode_id': observation['episode_id'],
            'decision_id': uuid.uuid4().hex, 'request_id': uuid.uuid4().hex,
            'time': observation['time'], 'operation': operation,
            'previous_configuration': {'scenario_ids': accepted['scenario_ids'],
                                       'role_assignments': assignments},
            'selected_configuration': selected if selected is not None else accepted,
            'candidate_evaluations': [], 'role_assignments': roles if roles is not None else assignments,
            'commands': list(commands), 'constraint_checks': [],
            'explanation': {'observation_refs': [observation['request_id']],
                            'reason_codes': ['independent_native_protocol_probe'],
                            'expected_effects': [], 'confidence': 1.0}}


def check(client, *, ledger_steps=0, seed=2026):
    evidence = []
    reset_id = uuid.uuid4().hex
    reset = client.reset(seed=seed, request_id=reset_id)
    observation = reset['observation']
    assert reset['time'] == 0
    baseline = deepcopy(observation)
    for _ in range(10):
        current = client.observation()
        current['request_id'] = baseline['request_id']
        assert current == baseline, 'GET changed a paused public snapshot'
    evidence.append('ten_gets_leave_time_physics_and_public_knowledge_unchanged')

    drone = next(a for a in observation['agents'] if a['kind'] == 'aerial')
    original_position = drone['position']
    target = [*original_position[:2], original_position[2]+8]
    selected = {'scenario_ids': ['coverage_search'], 'parameters': {}, 'synthesized_scenario': None}
    roles = {a['id']: 'scout' if a['kind'] == 'aerial' else 'rescuer' for a in observation['agents']}
    first = decision(observation, commands=[{'agent_id': drone['id'], 'action': 'move',
                                             'parameters': {'target': target}}],
                     operation='select', selected=selected, roles=roles)
    prepared = client.prepare_step(first)
    response = client.step(first)
    first_response=deepcopy(response)
    assert response['time'] == 1
    assert client.submit(prepared) == response, 'exact step retry differs'
    observation = response['observation']
    for _ in range(6):
        response = client.step(decision(observation))
        observation = response['observation']
    moved = next(a for a in observation['agents'] if a['id'] == drone['id'])
    assert moved['position'][2] > original_position[2]+4, 'C++ body did not climb'
    assert moved['physical']['distance_m'] > 4
    assert moved['physical']['consumed_wh'] > 0
    assert moved['resources']['energy']['value'] == 1, 'unlimited profile drained its battery'
    evidence.append('public_move_causes_measured_physical_climb_and_consumption')

    # Stop a live climb rather than only holding an already finished route.
    position=moved['position']
    response=client.step(decision(observation,commands=[{'agent_id':drone['id'],'action':'move',
        'parameters':{'target':[*position[:2],position[2]+20]}}]))
    response=client.step(decision(response['observation'],commands=[{'agent_id':drone['id'],'action':'hold','parameters':{}}]))
    hold_z=next(a for a in response['observation']['agents'] if a['id']==drone['id'])['position'][2]
    for _ in range(5):response=client.step(decision(response['observation']))
    held_z=next(a for a in response['observation']['agents'] if a['id']==drone['id'])['position'][2]
    assert abs(held_z-hold_z)<1, ('hold did not freeze active flight altitude',hold_z,held_z)
    observation=response['observation']
    evidence.append('hold_during_climb_freezes_altitude_instead_of_resuming_old_route')

    # A timed-out client may issue the same serialized step concurrently.
    concurrent = client.prepare_step(decision(observation))
    def submit_same():
        peer = EnvironmentClient('http://127.0.0.1:'+str(client.target.port), timeout_s=90)
        try:
            return peer.submit(concurrent)
        finally:
            peer.disconnect()
    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = list(pool.map(lambda _: submit_same(), range(2)))
    assert one == two and one['time'] == observation['time']+1
    observation = validate_observation(one['observation'])
    evidence.append('concurrent_identical_request_advances_exactly_once')

    def rejected(request, expected):
        before = client.observation()['time']
        try:
            client.submit(request)
        except ProtocolError as error:
            assert error.code == expected, (error.code, expected)
        else:
            raise AssertionError('Invalid request was accepted')
        assert client.observation()['time'] == before

    conflict = deepcopy(first)
    conflict['request_id'] = uuid.uuid4().hex
    rejected(client.prepare_step(conflict), 'INVALID_REQUEST')
    stale = decision(observation)
    stale['time'] -= 1
    stale_wire = client.prepare_step(stale)
    rejected(stale_wire, 'INVALID_REQUEST')
    rejected(stale_wire, 'INVALID_REQUEST')
    rejected(PreparedRequest('POST', '/v1/environment/step',
             b'{"protocol_version":"1.0","time":0,"time":1}'), 'INVALID_REQUEST')
    malformed = decision(observation, commands=[{'agent_id': drone['id'], 'action': 'move',
                                                 'parameters': {'target': [True, 2, 3]}}])
    rejected(client.prepare_step(malformed), 'INVALID_COMMAND')
    evidence.append('conflict_stale_duplicate_key_boolean_point_rejected_without_time')

    commands = [{'agent_id': drone['id'], 'action': 'hold', 'parameters': {}},
                {'agent_id': 'unannounced-id', 'action': 'hold', 'parameters': {}}]
    grouped = decision(observation, commands=commands)
    grouped['metaevolution'] = {'command_groups': [{'id': 'dependent', 'command_indices': [0, 1]}]}
    rejected(client.prepare_step(grouped), 'INVALID_COMMAND')
    partial = decision(observation, commands=commands)
    response = client.step(partial)
    assert response['time'] == observation['time']+1
    current_results = [r for r in response['command_results'] if r['decision_id'] == partial['decision_id']]
    assert len(current_results) == 2
    assert current_results[0]['validation_status'] == 'accepted'
    assert current_results[1]['validation_status'] == 'rejected'
    observation = response['observation']
    evidence.append('dependent_group_atomic_and_independent_partial_acceptance')

    conflicting=[{'agent_id':drone['id'],'action':'hold','parameters':{}} for _ in range(2)]
    rejected(client.prepare_step(decision(observation,commands=conflicting)),'INVALID_COMMAND')
    batch=[{'agent_id':drone['id'],'action':'observe','parameters':{'radius':20}} for _ in range(33)]
    atomic_overflow=decision(observation,commands=batch)
    atomic_overflow['metaevolution']={'command_groups':[{'id':'all-or-none','command_indices':list(range(33))}]}
    rejected(client.prepare_step(atomic_overflow),'INVALID_COMMAND')
    bounded=decision(observation,commands=batch);response=client.step(bounded)
    batch_results=[r for r in response['command_results'] if r['decision_id']==bounded['decision_id']]
    assert sum(r['validation_status']=='accepted' for r in batch_results)==32
    assert sum(r['validation_status']=='rejected' for r in batch_results)==1
    observation=response['observation']
    for _ in range(3):
        response=client.step(decision(observation));observation=response['observation']
    assert len(response['command_results'])==0,'finished command history was resent'
    evidence.append('same_batch_queue_budget_and_command_result_deltas')

    for _ in range(ledger_steps):
        response = client.step(decision(observation, commands=[{'agent_id': drone['id'], 'action': 'hold', 'parameters': {}}]))
        assert len(response['command_results'])<=2,'command history grew instead of returning deltas'
        observation = response['observation']
    if ledger_steps:
        evidence.append('additional_sequential_commands_'+str(ledger_steps))
        current_time=observation['time']
        assert client.submit(prepared)==first_response,'old disk replay differs'
        assert client.observation()['time']==current_time,'old retry advanced physics'
        evidence.append('old_response_retrieved_from_disk_without_new_transition')

    # Disk pagination is complete, deterministic and contains no private telemetry.
    cursor=0;traces=set();public_count=0
    while True:
        page=client.logs(observation['episode_id'],cursor=cursor)
        repeated=client.logs(observation['episode_id'],cursor=cursor)
        assert {k:v for k,v in page.items() if k!='request_id'}=={k:v for k,v in repeated.items() if k!='request_id'},'GET logs is not stable'
        records=page['records']
        if not records:break
        assert page['next_cursor']==cursor+len(records)
        for record in records:
            assert record['trace_id'] not in traces,'repeated public page record'
            assert record['record_type'] not in ('agent_telemetry','target_became_observable','local_command_received','truth_snapshot','event_configuration')
            traces.add(record['trace_id'])
        cursor=page['next_cursor'];public_count+=len(records)
    assert public_count>0 and client.observation()['time']==observation['time']
    evidence.append('full_stable_disk_public_pagination_without_truth_or_time_change_'+str(public_count))
    try:client.logs('not-the-current-episode')
    except ProtocolError as error:assert error.code=='UNKNOWN_EPISODE'
    else:raise AssertionError('GET logs accepted another episode ID')

    # Repeating the last reset returns its historical response, not a rewind.
    assert client.reset(seed=seed, request_id=reset_id) == reset
    assert client.observation()['time'] == observation['time']
    reset_two = client.reset(seed=seed)
    assert reset_two['episode_id'] != reset['episode_id'] and reset_two['time'] == 0
    rejected(PreparedRequest('POST', '/v1/environment/reset',
             encode({'protocol_version': '1.0', 'request_id': reset_id, 'seed': seed,
                     'mission': {'id': 'search_and_rescue', 'parameters': {}}})), 'INVALID_REQUEST')
    observation = reset_two['observation']
    stop = decision(observation, operation='safe_stop')
    response = client.step(stop)
    stop_response=deepcopy(response)
    for _ in range(15):
        if response['status'] != 'running':
            break
        response = client.step(decision(response['observation']))
    assert response['status'] == 'safe_stopped', response['status']
    assert client.step(stop)==stop_response,'terminal retry changed the historical response'
    last_time = response['time']
    for _ in range(3):
        assert client.observation()['time'] == last_time
    rejected(client.prepare_step(decision(response['observation'])), 'INVALID_REQUEST')
    evidence.append('reset_deduplication_new_episode_and_physical_safe_stop')
    final = client.reset(seed=seed)
    result = client.close(final['episode_id'])
    assert result['status'] == 'failed' and result['closed']
    evidence.append('closing_active_episode_reports_failed_and_preserves_time')
    return {'passed': True, 'scope': 'native static Core slice, physical climb and protocol; no rescue-delivery verdict',
            'checks': evidence, 'safe_stop_time': last_time, 'close': result,
            'expected_archive_statuses':{reset['episode_id']:'failed',reset_two['episode_id']:'safe_stopped',final['episode_id']:'failed'}}


def check_clock(client,*,seed=2026,realtime=False):
    response=client.reset(seed=seed);observation=response['observation']
    drone=next(a for a in observation['agents'] if a['kind']=='aerial')
    latency=drone['communication']['latency'];horizon=observation['mission']['termination']['horizon']
    assert 2<horizon<3,'Clock fixture must have a fractional horizon between 2 and 3 seconds'
    request=decision(observation,commands=[{'agent_id':drone['id'],'action':'move',
        'parameters':{'target':[*drone['position'][:2],drone['position'][2]+20]}}],operation='select',
        selected={'scenario_ids':['coverage_search'],'parameters':{},'synthesized_scenario':None},roles={drone['id']:'scout'})
    began=time.perf_counter();response=client.step(request);wall=[time.perf_counter()-began]
    result=next(r for r in response['command_results'] if r['decision_id']==request['decision_id'] and r['command_index']==0)
    assert abs(result['updated_at']-2*latency)<1e-9,('Ack rounded to a frame instead of its delivery boundary',result['updated_at'],2*latency)
    times=[response['time']]
    for _ in range(2):
        began=time.perf_counter();response=client.step(decision(response['observation']));wall.append(time.perf_counter()-began);times.append(response['time'])
    assert times==[1,2,horizon],times
    assert response['status']=='time_limit'
    if realtime:assert min(wall[:2])>.9,('Realtime full steps ran ahead of wall',wall)
    episode=response['observation']['episode_id'];before=response['observation']
    for _ in range(5):
        current=client.observation();current['request_id']=before['request_id'];assert current==before
    client.close(episode)
    return {'passed':True,'scope':'native fractional clock, command/ack boundaries and terminal horizon',
        'times':times,'ack_time':result['updated_at'],'latency_s':latency,'step_wall_s':wall,'realtime':realtime,
        'expected_archive_statuses':{episode:'time_limit'}}


def check_workflow(client,*,seed=2026,verify_curb_repro=False,algorithm_pair=None,optimizer_seed=2026,planning_audit=None,
                   ai_mode='OFF',ai_tariff=None,ai_replay=None,inject_shortcut=False,realtime=False,force_replan=False):
    repro=None;preflight_episodes={}
    if verify_curb_repro:
        response=client.reset(seed=seed)
        preflight_episodes[response['episode_id']]='failed'
        old=FixedWorkflow(prefer_roads=False)
        for _ in range(180):
            request=old.decide(response['observation']);response=client.step(request);old.observe_response(response)
            blocked=next((a for a in response['observation']['agents'] if a['kind']=='ground' and
                a['physical']['stop_reason']=='obstacle_on_route' and 'Paving' in a['physical']['stop_obstacle']),None)
            if blocked is not None:
                repro={'time':response['time'],'position':blocked['position'],
                       'stop_obstacle':blocked['physical']['stop_obstacle'],
                       'active_waypoint':blocked['physical']['active_waypoint']}
                print(json.dumps({'reproduced_curb_block':repro}),flush=True)
                break
        assert repro is not None,'Expected raised-paving blocker was not reproduced; inspect actual geometry'
    capabilities=client.capabilities()
    if ai_mode=='LIVE':assert capabilities['time_model']['wall_pacing']=='realtime'
    pacing_preflight=[]
    if realtime:
        probe=client.reset(seed=seed)
        preflight_episodes[probe['episode_id']]='failed'
        for _ in range(4):
            began=time.perf_counter();probe=client.step(decision(probe['observation']))
            pacing_preflight.append(time.perf_counter()-began)
        assert min(pacing_preflight)>.9,('REALTIME_PREFLIGHT_FAILED',pacing_preflight)
        print(json.dumps({'realtime_preflight_step_wall_s':pacing_preflight}),flush=True)
    response=client.reset(seed=seed)
    if ai_mode=='LIVE':
        provider=DeepSeek(LiveBudget(DEFAULT_OUTPUT/'ai-budget.json'),
            key_file=Path(os.environ['LOCALAPPDATA'])/'MetaRescue/secrets.env',tariff=ai_tariff,
            context={'episode_id':response['observation']['episode_id'],'fixture':'loaded_rescue'})
    elif ai_mode=='REPLAY':provider=load_replay(ai_replay)
    elif ai_mode=='MOCK':provider=Mock()
    else:provider=Off()
    policy=(SupervisedPolicy(provider,pair=algorithm_pair or 'nsga2_nsga2',seed=optimizer_seed) if ai_mode!='OFF' else
            EvolutionPolicy(pair=algorithm_pair,seed=optimizer_seed) if algorithm_pair else FixedWorkflow())
    iterations=0;planners_used={};max_ramp=0.;loaded_masses=set();injected=False;ai_events=[];step_times=[]
    replanned=False;replan_at=None;scout_completions=[];active_at_replan={}
    try:
        while response['status']=='running' and iterations<1100:
            if force_replan and not replanned and any(s not in policy.completed_sectors for s in policy.scout_active.values()) and any(a.get('physical',{}).get('carrying') for a in response['observation']['agents']):
                policy.request_replan(reason='native_loaded_replan_acceptance');replanned=True;replan_at=response['time']
                active_at_replan=dict(policy.scout_active)
                if planning_audit:planning_audit({'type':'fixture_replan_trigger','time':replan_at,
                    'active_scout_sectors':dict(policy.scout_active),'loaded_agents':[a['id'] for a in response['observation']['agents'] if a['physical']['carrying']]})
            request=policy.decide(response['observation'])
            if inject_shortcut and not injected:
                agents={a['id']:a for a in response['observation']['agents']}
                for command in request['commands']:
                    a=agents[command['agent_id']]
                    if a['kind']=='ground' and a['physical']['carrying'] and command['action']=='follow_route':
                        goal=command['parameters']['waypoints'][-1]
                        command['parameters']['waypoints']=[[56.,10.,a['position'][2]],goal]
                        injected=True
                        if planning_audit:planning_audit({'type':'fixture_fault_injection','time':response['time'],
                            'agent_id':a['id'],'cargo_target_id':a['physical']['cargo_target_id'],'command':command})
                        break
            step_started=time.perf_counter()
            response=client.step(request)
            step_times.append(time.perf_counter()-step_started)
            policy.observe_response(response)
            if isinstance(policy,EvolutionPolicy):
                for record in policy.drain_traces():
                    if planning_audit:planning_audit(record)
                    if record['type']=='sector_completed':scout_completions.append(record)
                    if record['type'] in ('ai_response','ai_error','local_action_applied','global_strategy_applied','local_immediate_brake'):
                        ai_events.append(record)
                    if record['type']=='planning_result_committed':
                        stats=record['result']['plan']['stats']
                        if stats.get('evaluations',0)>0:
                            planners_used[record['planner']]=stats
            for a in response['observation']['agents']:
                physical=a['physical'];max_ramp=max(max_ramp,physical.get('ramp_deployment',0))
                if physical['carrying']:loaded_masses.add(physical['mass_kg'])
            iterations+=1
            if iterations%10==0:
                print(json.dumps({'time':response['time'],'metrics':response['metrics'],
                    'jobs':{a:vars(j) for a,j in policy.jobs.items()},
                    'agents':[{k:a[k] for k in ('id','position','status','physical')} for a in response['observation']['agents']],
                    'failures':policy.failures[-3:]},ensure_ascii=False),flush=True)
    finally:
        if isinstance(policy,EvolutionPolicy):
            policy.close()
            for record in policy.drain_traces():
                if planning_audit:planning_audit(record)
                if record['type']=='ai_response':ai_events.append(record)
    observation=response['observation']
    assert response['status']=='success', ('workflow did not complete',response['status'],response['time'],policy.failures[-3:])
    assert observation['metrics']['confirmed_evacuations']==3, observation['metrics']
    # Agent telemetry may precede the base's final handover acknowledgement.
    # Physical custody is checked from the closed native truth archive below.
    assert max_ramp>.98, ('loading mechanism not observed',max_ramp)
    assert any(abs(m-320)<.1 for m in loaded_masses), ('actual loaded mass not observed',loaded_masses)
    if realtime:assert min(step_times[:-1])>.9,('realtime advanced too fast',min(step_times))
    if inject_shortcut:
        assert injected,'No loaded command was injected'
        assert any(r['type']=='local_immediate_brake' and r.get('cargo_target_id') for r in ai_events), 'No loaded emergency brake'
        assert any(r['type']=='local_action_applied' and r.get('action')=='DETOUR' for r in ai_events),'No validated local detour'
    if ai_mode!='OFF':
        assert any(r['type']=='ai_response' and r['role']=='local' for r in ai_events),'No local AI response'
        assert any(r['type']=='ai_response' and r['role']=='global' for r in ai_events),'No global AI response'
    if algorithm_pair:
        assert set(planners_used)=={'scout','rescue'}, planners_used
        for name,kind in zip(('scout','rescue'),PAIRS[algorithm_pair]):
            if kind=='nsga2':assert 'effective_seed' in planners_used[name],planners_used[name]
    if force_replan:
        assert replanned,'Loaded carrier and active Scout were not observed together'
        completed_after={r['sector_id'] for r in scout_completions if r['time']>replan_at}
        assert set(active_at_replan.values())<=completed_after,'Active sectors were lost during loaded replanning'
    logs=client.logs(observation['episode_id'])
    assert logs['records'], 'Public causal journal is empty'
    client.close(observation['episode_id'])
    return {'passed':True,'scope':'native public-only rescue fixture; AI '+ai_mode,
            'time':response['time'],'metrics':observation['metrics'],'steps':iterations,
            'terminal_public_carrying':[a['id'] for a in observation['agents'] if a['physical']['carrying']],
            'controller_failures':policy.failures,'curb_reproduction':repro,'algorithm_pair':algorithm_pair or 'fixed_workflow',
            'planners_used':planners_used,'max_ramp_deployment':max_ramp,'loaded_masses_kg':sorted(loaded_masses),
            'ai_mode':ai_mode,'ai_applied':getattr(policy,'applied',None),'ai_response_count':sum(r['type']=='ai_response' for r in ai_events),
            'loaded_fault_injected':injected,'forced_replan_at':replan_at,'active_sectors_at_replan':active_at_replan,
            'scout_completions_after_replan':sum(r['time']>replan_at for r in scout_completions) if replan_at is not None else None,
            'realtime':realtime,'realtime_preflight_step_wall_s':pacing_preflight,
            'expected_archive_statuses':preflight_episodes,
            'step_wall_s_min':min(step_times),'step_wall_s_max':max(step_times)}


def verify_workflow_terminal(result, output_root):
    archive, = [row for row in result['native_archives'] if row['status']=='success']
    records=IndexedRecords(output_root/'core-runs'/archive['episode_id']/'truth')
    final=next(records.json_records(start=len(records)-1))
    assert final['record_type']=='truth_snapshot' and final['payload']['phase']=='close'
    assert final['time']==result['time'],'Terminal physical time differs from public result'
    state=final['payload']
    carrying=[a['id'] for a in state['agents'] if a['physical']['carrying']]
    assert not carrying,('Cargo remains physically attached after success',carrying)
    rescued=[t['id'] for t in state['targets'] if t['rescued']]
    assert len(rescued)==result['metrics']['confirmed_evacuations'],'Physical and confirmed evacuations differ'
    result['terminal_truth']={'episode_id':archive['episode_id'],'time':final['time'],
                              'rescued_targets':rescued,'carrying_agents':carrying}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('layout', type=Path)
    parser.add_argument('--port', type=int, default=8130)
    parser.add_argument('--name')
    parser.add_argument('--ledger-steps', type=int, default=0)
    parser.add_argument('--seed', type=int, default=2026)
    parser.add_argument('--workflow',action='store_true')
    parser.add_argument('--clock',action='store_true',help='Short fractional command/clock fixture')
    parser.add_argument('--events',action='store_true',help='Repeat the authored native event and surface fixture')
    parser.add_argument('--resources',action='store_true',help='Finite batteries and stationary charging acceptance')
    parser.add_argument('--radio',action='store_true',help='Native relay and packet delivery acceptance')
    parser.add_argument('--contest-events',action='store_true',help='Native contest disturbance and public event catalog')
    parser.add_argument('--city-collider',action='store_true',help='Native CityV2 collision and aerial clearance fixtures')
    parser.add_argument('--maximum-fleet',action='store_true',help='Native CityV2 maximum-fleet physical departure')
    parser.add_argument('--scenarios',action='store_true',help='Native scenario operations and delayed role confirmation')
    parser.add_argument('--interop',action='store_true',help='Independent public HTTP client and in-process reset acceptance')
    parser.add_argument('--archive-io',action='store_true',help='Inject a Windows manifest write failure and verify fail-closed execution')
    parser.add_argument('--operator-directives',action='store_true',help='Native operator lifecycle and delivered controller feedback')
    parser.add_argument('--capture-events',action='store_true',help='Save native event screenshots in each fixture episode')
    parser.add_argument('--capture-overview',action='store_true',help='Save an overhead image at each external step')
    parser.add_argument('--verify-curb-repro',action='store_true')
    parser.add_argument('--algorithm-pair',choices=PAIRS)
    parser.add_argument('--optimizer-seed',type=int,default=2026)
    parser.add_argument('--ai-mode',choices=['OFF','MOCK','LIVE','REPLAY'],default='OFF')
    parser.add_argument('--ai-tariff',type=Path)
    parser.add_argument('--ai-replay',type=Path)
    parser.add_argument('--inject-shortcut',action='store_true')
    parser.add_argument('--force-replan',action='store_true',help='Exercise a loaded carrier and an active Scout during a public-state replan')
    parser.add_argument('--realtime',action='store_true')
    parser.add_argument('--headless',action='store_true',help='Native physics without GPU rendering')
    args = parser.parse_args()
    if args.ai_mode=='LIVE' and not args.realtime:parser.error('LIVE requires --realtime')
    if (args.ai_mode=='REPLAY')!=(args.ai_replay is not None):parser.error('--ai-replay requires and is required by REPLAY')
    if args.ai_tariff is not None and args.ai_mode!='LIVE':parser.error('--ai-tariff requires LIVE')
    ai_inputs=[p.resolve(strict=True) for p in (args.ai_tariff,args.ai_replay) if p is not None]
    def ai_hashes():return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in ai_inputs}
    if args.force_replan and (not args.workflow or not args.algorithm_pair):parser.error('--force-replan requires --workflow --algorithm-pair')
    if args.clock and (args.workflow or args.ledger_steps or args.ai_mode!='OFF'):parser.error('--clock is an AI-free separate fixture')
    if args.events and (args.clock or args.workflow or args.ledger_steps or args.ai_mode!='OFF'):
        parser.error('--events is an AI-free separate fixture')
    if args.resources and (args.events or args.clock or args.workflow or args.ledger_steps or args.ai_mode!='OFF'):
        parser.error('--resources is an AI-free separate fixture')
    if args.radio and (args.resources or args.events or args.clock or args.workflow or args.ledger_steps or args.ai_mode!='OFF'):
        parser.error('--radio is an AI-free separate fixture')
    if args.contest_events and (args.radio or args.resources or args.events or args.clock or args.workflow or args.ledger_steps or args.ai_mode!='OFF'):
        parser.error('--contest-events is an AI-free separate fixture')
    if args.city_collider and (args.contest_events or args.radio or args.resources or args.events or args.clock or
                             args.workflow or args.ledger_steps or args.ai_mode!='OFF'):
        parser.error('--city-collider is an AI-free separate fixture')
    if args.maximum_fleet and (args.city_collider or args.contest_events or args.radio or args.resources or
                              args.events or args.clock or args.workflow or args.ledger_steps or args.ai_mode!='OFF'):
        parser.error('--maximum-fleet is an AI-free separate fixture')
    if args.scenarios and (args.maximum_fleet or args.city_collider or args.contest_events or args.radio or args.resources or
                           args.events or args.clock or args.workflow or args.ledger_steps or args.ai_mode!='OFF'):
        parser.error('--scenarios is an AI-free separate fixture')
    if args.interop and (args.scenarios or args.maximum_fleet or args.city_collider or args.contest_events or
                         args.radio or args.resources or args.events or args.clock or args.workflow or args.ledger_steps or args.ai_mode!='OFF'):
        parser.error('--interop is an AI-free separate fixture')
    if args.archive_io and (os.name!='nt' or args.interop or args.scenarios or args.maximum_fleet or args.city_collider or
        args.contest_events or args.radio or args.resources or args.events or args.clock or args.workflow or
        args.ledger_steps or args.ai_mode!='OFF' or args.capture_events or args.capture_overview):
        parser.error('--archive-io is a separate AI-free Windows fixture')
    if args.operator_directives and (args.archive_io or args.interop or args.scenarios or args.maximum_fleet or args.city_collider or
        args.contest_events or args.radio or args.resources or args.events or args.clock or args.workflow or
        args.ledger_steps or args.ai_mode!='OFF'):
        parser.error('--operator-directives is a separate AI-free fixture')
    if args.capture_events and not args.events:parser.error('--capture-events requires --events')
    if (args.capture_events or args.capture_overview) and args.headless:parser.error('Frame capture requires rendering')
    assert not existing_unreal(), 'Another Unreal is running'
    stamp = args.name or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    if Path(stamp).name!=stamp or stamp in ('.','..') or any(char in stamp for char in ':/\\'):
        parser.error('--name must be one directory name')
    output = (DEFAULT_OUTPUT/'core-acceptance'/stamp).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_layout=args.layout.resolve(strict=True)
    private_bytes=source_layout.read_bytes();args.layout=output/'world.private.json';args.layout.write_bytes(private_bytes)
    (output/'source-layout.json').write_text(json.dumps({'path':str(source_layout),
        'sha256':hashlib.sha256(private_bytes).hexdigest()},indent=2),encoding='utf-8')
    before = source_hashes(args.layout) | ai_hashes()
    (output/'inputs.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    command = native_command(layout=args.layout, port=args.port, output=output, headless=args.headless,
                             exit_on_close=not args.interop,realtime=args.realtime)
    owner_exit=output/'owner-exit.request' if args.interop else None
    if owner_exit is not None:command.append('-MRCoreExitRequestFile='+str(owner_exit))
    if args.capture_events:command.append('-MRCoreCaptureEvents')
    if args.capture_overview:command.append('-MRCoreCaptureOverview')
    startup = subprocess.STARTUPINFO() if os.name == 'nt' else None
    if startup:
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    result = {'passed': False}
    began=time.perf_counter()
    audit_file = (output/'http.jsonl').open('w', encoding='utf-8')
    planning_file=(output/'controller-planning.jsonl').open('w',encoding='utf-8')
    def planning_audit(record):
        planning_file.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n');planning_file.flush()
    def audit(record):
        record = {k: v.decode('utf-8', errors='replace') if isinstance(v, bytes) else v for k, v in record.items()}
        audit_file.write(json.dumps(record, ensure_ascii=False)+'\n')
        audit_file.flush()
    with (output/'stdout.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, startupinfo=startup)
        client = EnvironmentClient('http://127.0.0.1:'+str(args.port), timeout_s=90, audit=audit)
        try:
            deadline = time.monotonic()+240
            while time.monotonic()<deadline:
                if process.poll() is not None:
                    raise RuntimeError('Native process exited during startup: '+str(process.returncode))
                try:
                    if client.health()['status'] == 'ready':
                        break
                except (OSError, RuntimeError, ProtocolError):
                    pass
                time.sleep(.25)
            else:
                raise TimeoutError('Native Core did not become ready in 240s')
            if args.operator_directives:
                result=core_operator_check.drive(client,json.loads(private_bytes),decision)
            elif args.archive_io:
                result=core_archive_check.drive(client,DEFAULT_OUTPUT,decision,seed=args.seed)
            elif args.interop:
                result=core_interop_check.drive(args.port,args.seed)
                result['native_pid']=process.pid
            elif args.events:
                world=json.loads(private_bytes)
                result=core_event_check.drive(client,world,decision)
            elif args.resources:
                result=core_resource_check.drive(client,json.loads(private_bytes),decision)
            elif args.radio:
                result=core_radio_check.drive(client,json.loads(private_bytes),decision)
            elif args.contest_events:
                world=json.loads(private_bytes)
                result=core_contest_check.drive(client,world,decision)
            elif args.city_collider:
                world=json.loads(private_bytes)
                driver={'core-air-clearance-v1':core_city_check.drive_aerial,
                        'core-dock-parking-v1':core_city_check.drive_parking,
                        'core-loaded-bypass-v1':core_city_check.drive_loaded_bypass}.get(world.get('fixture',{}).get('id'),core_city_check.drive)
                result=driver(client,world,decision)
            elif args.maximum_fleet:
                result=core_city_check.drive_maximum(client,json.loads(private_bytes),decision)
            elif args.scenarios:
                world=json.loads(private_bytes)
                run_check={'core-team-actions-v1':core_scenario_check.drive_actions,
                           'core-competition-annex-v1':core_annex_check.drive,
                           'core-competition-services-v1':core_annex_check.drive_services}.get(world['fixture']['id'],core_scenario_check.drive)
                result=run_check(client,world,decision)
            elif args.clock:
                result=check_clock(client,seed=args.seed,realtime=args.realtime)
            elif args.workflow:
                result=check_workflow(client,seed=args.seed,verify_curb_repro=args.verify_curb_repro,
                    algorithm_pair=args.algorithm_pair,optimizer_seed=args.optimizer_seed,planning_audit=planning_audit,
                    ai_mode=args.ai_mode,ai_tariff=json.loads(args.ai_tariff.read_bytes()) if args.ai_tariff else None,
                    ai_replay=args.ai_replay,inject_shortcut=args.inject_shortcut,realtime=args.realtime,force_replan=args.force_replan)
            else:result=check(client,ledger_steps=args.ledger_steps,seed=args.seed)
            if not args.interop:
                result['native_exit_code']=process.wait(timeout=30)
                assert result['native_exit_code']==0, ('Native exit',result['native_exit_code'])
            ids=list(dict.fromkeys(re.findall(r'MR_CORE episode ([0-9A-Fa-f]{32}) journal ',(output/'stdout.log').read_text(encoding='utf-8',errors='replace'))))
            assert ids,'No native journal references in engine output'
            if args.interop:
                assert len(ids)==4 and ids==result['episode_ids'],('Interop native/public episode IDs differ',ids,result['episode_ids'])
            result['native_archives']=[verify_archive(DEFAULT_OUTPUT/'core-runs'/eid,require_complete=False) if args.archive_io
                                      else verify_archive(DEFAULT_OUTPUT/'core-runs'/eid) for eid in ids]
            for archive in result['native_archives']:
                expected=result.get('expected_archive_statuses',{}).get(archive['episode_id'],'success' if args.workflow else None)
                if expected:assert archive['status']==expected,('Archived terminal status changed',archive['episode_id'],archive['status'],expected)
                if args.clock:
                    truth=list(IndexedRecords(DEFAULT_OUTPUT/'core-runs'/archive['episode_id']/'truth').json_records())
                    snapshots=[r for r in truth if r['record_type']=='truth_snapshot']
                    assert any(r['time']==result['times'][-1] and r['payload']['phase']=='terminal' for r in snapshots)
                    assert archive['files']['truth']['record_types']['agent_telemetry']==int(result['times'][-1]*10)
                    assert archive['resident_indices']['agent_command_digests']==0,'Finished Core commands retained local history'
            if args.workflow:verify_workflow_terminal(result,DEFAULT_OUTPUT)
            if args.events:core_event_check.verify(result,world,DEFAULT_OUTPUT,capture=args.capture_events)
            if args.resources:core_resource_check.verify(result,DEFAULT_OUTPUT)
            if args.radio:core_radio_check.verify(result,DEFAULT_OUTPUT)
            if args.contest_events:core_contest_check.verify(result,world,DEFAULT_OUTPUT)
            if args.city_collider and world.get('fixture',{}).get('id')=='core-loaded-bypass-v1':
                core_city_check.verify_loaded_bypass(result,DEFAULT_OUTPUT)
            if args.scenarios and 'aid_command_id' in result:core_scenario_check.verify_actions(result,DEFAULT_OUTPUT)
            if args.archive_io:core_archive_check.verify(result,DEFAULT_OUTPUT)
            if args.operator_directives:core_operator_check.verify(result,DEFAULT_OUTPUT)
            if args.interop:
                core_interop_check.verify(result,DEFAULT_OUTPUT)
                if process.poll() is not None:
                    raise RuntimeError(f'Persistent native exited before owner shutdown: {process.returncode}')
                owner_exit.touch(exist_ok=False)
                result['native_shutdown']='owner_exit_request'
                result['native_exit_code']=process.wait(timeout=30)
                assert result['native_exit_code']==0, ('Native exit',result['native_exit_code'])
        except BaseException as error:
            result['passed'] = False
            result['error_type'] = type(error).__name__
            result['error'] = str(error)
            raise
        finally:
            client.disconnect()
            if process.poll() is None:
                process.terminate()
                result['forced_owner_cleanup'] = True
                process.wait(timeout=30)
            result.setdefault('native_exit_code',process.returncode)
            audit_file.close()
            planning_file.close()
            result['frozen_inputs_preserved'] = before == (source_hashes(args.layout) | ai_hashes())
            result['passed'] = result['passed'] and result['frozen_inputs_preserved']
            result['rendering']='null_rhi' if args.headless else 'offscreen'
            result['wall_elapsed_s']=time.perf_counter()-began
            (output/'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
