"""Independent public-HTTP controller. Fixed workflow is a control specimen."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from contracts.protocol import ProtocolError,validate_episode_response
from contracts.protocol import strict_json
from controller.accounting import digest
from controller.baselines import BASELINES,FixedWorkflow,LocalReactive
from controller.client import EnvironmentClient,TransportFailure
from controller.communication_log import CommunicationLog
from controller.health import HealthServer
from controller.policy import EvolutionPolicy,PAIRS
from controller.ai import DeepSeek,LiveBudget,Mock,Off,load_replay
from controller.ai_contracts import AIError
from controller.ai_policy import SupervisedPolicy
from controller.scenarios import ScenarioCoordinator
from controller.decisions import decision
from controller.operator_directives import OperatorDirectives
from controller.operator_input import OperatorInput
from controller.operational import OperationalControl
from controller.portable import PortablePolicy


_MISSION_STATUS = {'active': 'running', 'completed': 'success', 'failed': 'failed', 'safe_stopped': 'safe_stopped'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment',default='http://127.0.0.1:8130')
    parser.add_argument('--health-port',type=int,default=8131)
    parser.add_argument('--seed',type=int,default=2026)
    parser.add_argument('--policy',choices=[*BASELINES,*PAIRS],default='nsga2_nsga2')
    parser.add_argument('--optimizer-seed',type=int,default=2026)
    parser.add_argument('--scout-population',type=int,default=40)
    parser.add_argument('--scout-generations',type=int,default=32)
    parser.add_argument('--rescue-population',type=int,default=26)
    parser.add_argument('--rescue-generations',type=int,default=17)
    parser.add_argument('--rescue-initializer',choices=('heuristic','assignment'),default='heuristic',
                        help='Optional one-wave linear assignment seed for rescue NSGA-II')
    parser.add_argument('--strategy-candidates',action='store_true',help='Evaluate the five genuine strategic alternatives')
    parser.add_argument('--contest-coordination',action='store_true',help='Execute the declared contest scenario library')
    parser.add_argument('--ai-mode',choices=['OFF','MOCK','LIVE','REPLAY'],default='OFF')
    parser.add_argument('--ai-scope',choices=['global','global_local'],default='global_local')
    parser.add_argument('--ai-key-file',type=Path,default=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'MetaRescue/secrets.env')
    parser.add_argument('--ai-key-environment',default='DEEPSEEK_API_KEY')
    parser.add_argument('--ai-budget',type=Path,default=Path(os.environ.get('METARESCUE_LIVE_BUDGET','D:/MetaRescue-output/ai-budget.json')))
    parser.add_argument('--ai-replay',type=Path)
    parser.add_argument('--ai-tariff',type=Path,help='Versioned verified pricing snapshot; prior records retain their own snapshot')
    parser.add_argument('--attach',action='store_true',help='Use an existing episode instead of owning reset')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--run-id',help='Stable runner-owned ID; otherwise a new UUID is assigned')
    parser.add_argument('--control-file',type=Path,help='Optional local operator gate, sampled between external steps')
    parser.add_argument('--control-session',help='Required identity of the operator gate')
    parser.add_argument('--operator-file',type=Path,help='Optional episode-bound structured human requirements')
    args=parser.parse_args()
    # Validate the origin before it is persisted in the run manifest.
    EnvironmentClient(args.environment)
    if args.ai_mode!='OFF' and args.policy in BASELINES:parser.error('AI requires an evolutionary policy')
    if args.contest_coordination and args.policy in BASELINES:parser.error('Scenario coordination requires an evolutionary policy')
    if args.rescue_initializer!='heuristic' and (args.policy not in PAIRS or PAIRS[args.policy][1]!='nsga2'):
        parser.error('Assignment initialization requires NSGA-II rescue')
    if args.ai_mode=='REPLAY' and args.ai_replay is None:parser.error('--ai-replay is required for REPLAY')
    if bool(args.control_file)!=bool(args.control_session):parser.error('--control-file and --control-session are required together')
    if any(not 4<=value<=256 for value in (args.scout_population,args.rescue_population)) or any(
        not 1<=value<=256 for value in (args.scout_generations,args.rescue_generations)):
        parser.error('NSGA-II populations must be 4..256 and generations 1..256')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output=(args.output or Path(os.environ.get('METARESCUE_OUTPUT','D:/MetaRescue-output'))/'controller-runs'/stamp).resolve()
    output.mkdir(parents=True,exist_ok=False)
    partial=output/'controller.jsonl.gz.part'
    run_id=args.run_id or uuid.uuid4().hex
    manifest={'format':'metarescue.controller-run.v1','policy':args.policy,'state':'incomplete','ai_mode':args.ai_mode,'run_id':run_id,
              'ai_scope':args.ai_scope if args.ai_mode!='OFF' else None,
              'contest_coordination':args.contest_coordination,
              'optimizer':{'seed':args.optimizer_seed,'scout_population':args.scout_population,'scout_generations':args.scout_generations,
                           'rescue_population':args.rescue_population,'rescue_generations':args.rescue_generations,
                           'rescue_initializer':args.rescue_initializer},
              'environment':args.environment,'journal':partial.name,'records':0}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    record_count=0
    episode_id=None
    with gzip.open(partial,'xb',compresslevel=3) as journal,HealthServer(args.health_port) as health:
        def record(kind,payload):
            nonlocal record_count
            data={'record_type':kind,'episode_id':episode_id,'wall_utc':datetime.now(timezone.utc).isoformat(),
                  'payload':payload}
            journal.write((json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n').encode('utf-8'))
            journal.flush();record_count+=1
        def audit(item):
            # No HTTP authorization headers enter this client. Preserve invalid
            # wire bytes losslessly without guessing a replacement character.
            import base64
            converted={}
            for key,value in item.items():
                if isinstance(value,bytes):
                    converted[key]={'encoding':'base64','data':base64.b64encode(value).decode('ascii'),
                                    'sha256':hashlib.sha256(value).hexdigest()}
                else:converted[key]=value
            record('http_exchange',converted)
        client=EnvironmentClient(args.environment,timeout_s=60,audit=audit)
        context={'run_id':run_id,'purpose':'mission','policy':args.policy,'world_seed':args.seed,
                 'optimizer_seed':args.optimizer_seed,'config_sha256':digest({'policy':args.policy,'seed':args.seed,
                    'optimizer_seed':args.optimizer_seed,'ai_mode':args.ai_mode,'ai_scope':args.ai_scope,
                    'budgets':[args.scout_population,args.scout_generations,args.rescue_population,args.rescue_generations],
                    'strategy_candidates':args.strategy_candidates,'contest_coordination':args.contest_coordination,
                    **({'rescue_initializer':args.rescue_initializer} if args.rescue_initializer!='heuristic' else {})})}
        provider=(DeepSeek(LiveBudget(args.ai_budget),key_file=args.ai_key_file,key_environment=args.ai_key_environment,
                           context=context,tariff=strict_json(args.ai_tariff.read_bytes()) if args.ai_tariff else None)
                  if args.ai_mode=='LIVE' else Mock() if args.ai_mode=='MOCK' else
                  load_replay(args.ai_replay) if args.ai_mode=='REPLAY' else Off())
        budgets={'population_scout':args.scout_population,'generations_scout':args.scout_generations,
                 'population_rescue':args.rescue_population,'generations_rescue':args.rescue_generations,
                 'rescue_initializer':args.rescue_initializer}
        policy=(FixedWorkflow() if args.policy=='fixed_workflow' else
                LocalReactive() if args.policy=='local_reactive' else
                SupervisedPolicy(provider,pair=args.policy,seed=args.optimizer_seed,local_enabled=args.ai_scope=='global_local',**budgets)
                if args.ai_mode!='OFF' else
                EvolutionPolicy(pair=args.policy,seed=args.optimizer_seed,strategy_candidates=args.strategy_candidates,**budgets))
        coordinator=None
        control=OperationalControl(args.control_file,session_id=args.control_session) if args.control_file else None
        last_control=None;operator_stopped=False
        try:
            capabilities=client.capabilities();record('capabilities',capabilities)
            communications=CommunicationLog(capabilities)
            operator_requirements=OperatorDirectives(capabilities)
            operator_input=OperatorInput(args.operator_file,capabilities) if args.operator_file else None
            if operator_input:health.update(operator_input_file=str(args.operator_file))
            if args.ai_mode=='LIVE' and capabilities.get('time_model',{}).get('wall_pacing')!='realtime':
                raise ValueError('LIVE AI requires an environment launched with --realtime')
            if args.attach:
                observation=client.observation()
                mission_status=observation['mission']['status']
                if mission_status not in _MISSION_STATUS:raise ValueError('Unrecognized attached mission status')
                response={'status':_MISSION_STATUS[mission_status],'observation':observation}
            else:response=client.reset(seed=args.seed)
            observation = response['observation']
            episode_id = observation['episode_id']
            manifest['episode_id']=episode_id
            extensions=capabilities.get('extensions')
            declared=observation.get('metaevolution')
            # Unknown optional fields are Core input, but only advertised extensions activate our planner.
            advertised=isinstance(extensions,list) and 'metarescue.announced_map.v1' in extensions
            announced=declared.get('announced_map') if advertised and isinstance(declared,dict) else None
            portable=not isinstance(announced,dict) or not announced
            if not portable and args.contest_coordination:
                plan=declared.get('plan')
                portable=('metaevolution.plan_confirmation.v1' not in extensions or
                          not isinstance(plan,dict) or not plan)
            if portable:
                if isinstance(policy, EvolutionPolicy):
                    policy.close()
                policy = PortablePolicy(capabilities, args.policy)
            elif args.contest_coordination:
                coordinator=ScenarioCoordinator(capabilities)
            manifest['policy_profile'] = 'core_1_0' if portable else 'metarescue'
            record('policy_profile', {'name': manifest['policy_profile']})
            record('observation',observation)
            for item in communications.observe(observation):record('agent_communication',item)
            health.update(status='ready',episode_id=episode_id,policy=args.policy,
                                                          time=observation['time'],episode_status=response['status'])
            rejections = 0
            while response['status']=='running':
                gate=control.take() if control else 'advance'
                if control:
                    state=control.snapshot()
                    if state!=last_control:
                        record('operator_control',state);last_control=state
                    health.update(control=state,status='paused' if gate=='wait' else 'stopping' if gate=='stop' else 'ready')
                if gate=='wait':
                    time.sleep(.05)
                    continue
                started=time.perf_counter();observation=response['observation']
                if gate=='stop':
                    request=decision(observation,operation='keep' if operator_stopped else 'safe_stop',previous=policy.previous)
                    request['explanation']['reason_codes']=['operator_safe_stop']
                    operator_stopped=True
                else:
                    observation=operator_requirements.prepare(observation)
                    if operator_requirements.changed and isinstance(policy,EvolutionPolicy):
                        policy.current_observation=observation
                        policy.request_replan(reason='delivered_operator_requirement_changed')
                    if coordinator:coordinator.prepare(observation,policy)
                    request=policy.decide(observation)
                    if coordinator:request=coordinator.apply(observation,request,policy)
                    operator_requirements.apply(observation,request)
                    if operator_input:
                        operator_input.append(response['observation'],request)
                        for item in operator_input.drain():record('operator_input',item)
                record('decision',{'decision':request,'planning_wall_s':time.perf_counter()-started})
                health.update(last_decision={'decision_id':request['decision_id'],'time':request['time'],
                    'operation':request['operation'],'reason_codes':request['explanation']['reason_codes'],
                    'scenario_ids':request['selected_configuration']['scenario_ids'],'command_count':len(request['commands'])})
                wire=client.prepare_step(request)
                # Each retry uses this one immutable serialized request.
                rejected = False
                for attempt in range(3):
                    try:
                        response=client.submit(wire)
                        try:validate_episode_response(response,step=True)
                        except ProtocolError as error:
                            raise TransportFailure('Inconsistent StepResponse: '+str(error),state_may_have_changed=True) from error
                        break
                    except TransportFailure as error:
                        record('uncertain_step',{'decision_id':request['decision_id'],'attempt':attempt,
                            'state_may_have_changed':error.state_may_have_changed,'error':str(error)})
                        health.update(status='degraded',reason='awaiting_exact_step_retry')
                        if attempt==2:raise
                    except ProtocolError as error:
                        recoverable = ('INVALID_COMMAND', 'INVALID_SCENARIO', 'CONSTRAINT_VIOLATION', 'RESOURCE_EXHAUSTED', 'INVALID_REQUEST')
                        if not portable or gate == 'stop' or rejections >= 3 or error.code not in recoverable:
                            raise
                        fresh = client.observation()
                        if (fresh['episode_id'] != episode_id or fresh['mission']['status'] not in _MISSION_STATUS or
                                error.code == 'INVALID_REQUEST' and fresh['time'] == observation['time']):
                            raise
                        record('observation',fresh)
                        for item in communications.observe(fresh):record('agent_communication',item)
                        rejections += 1
                        policy.reject(fresh['time'], error.code)
                        record('environment_rejection', {'decision_id': request['decision_id'], 'code': error.code,
                                                          'time': fresh['time'], 'attempt': rejections})
                        response = {**response, 'observation': fresh, 'time': fresh['time'],
                                    'status': _MISSION_STATUS[fresh['mission']['status']]}
                        rejected = True
                        break
                if rejected:
                    continue
                rejections = 0
                if control:control.complete()
                if gate!='stop':
                    policy.observe_response(response)
                    operator_requirements.observe(response)
                    if operator_input:
                        operator_input.observe(response)
                        for item in operator_input.drain():record('operator_input',item)
                if coordinator and gate!='stop':
                    coordinator.observe(response)
                    for item in coordinator.drain():record('scenario_trace',item)
                if isinstance(policy,EvolutionPolicy):
                    for item in policy.drain_traces():record('planning_trace',item)
                record('step_response',response)
                for item in communications.observe(response['observation']):record('agent_communication',item)
                health.update(status='ready',time=response['time'],episode_status=response['status'])
                if isinstance(policy,EvolutionPolicy):
                    builder=policy.builder
                    bounds=builder.map['bounds'] if builder else None
                    covered=[{'id':sector.id,'min':[bounds['min'][0]+sector.column*50,bounds['min'][1]+sector.row*50,.08],
                              'max':[min(bounds['max'][0],bounds['min'][0]+(sector.column+1)*50),
                                     min(bounds['max'][1],bounds['min'][1]+(sector.row+1)*50),.08]}
                             for sector in builder.sectors if sector.id in policy.completed_sectors] if builder else []
                    health.update(planning={'scout_pending':'scout' in policy.futures,'rescue_pending':'rescue' in policy.futures,
                        'scout_round':policy.patrol_round,'completed_sectors':len(policy.completed_sectors),
                        'strategy':policy.strategy_profile,'covered_regions':covered,'total_sectors':len(builder.sectors) if builder else 0})
                if coordinator:health.update(scenario={'id':coordinator.program_id,
                    'state':coordinator.program.current if coordinator.program else None})
                if isinstance(policy,SupervisedPolicy):health.update(ai={**policy.advisors.status(),'local_enabled':policy.local_enabled,
                                                                       'applied':dict(policy.applied)})
            manifest['state']='complete';manifest['episode_status']=response['status']
            manifest['metrics']=response['observation']['metrics']
        except BaseException as error:
            manifest['state']='failed';manifest['error_type']=type(error).__name__;manifest['error']=str(error)
            record('controller_failure',{'type':type(error).__name__,'message':str(error)})
            raise
        finally:
            if isinstance(policy,EvolutionPolicy):
                policy.close()
                for item in policy.drain_traces():record('planning_trace',item)
            if episode_id:
                try:record('close_response',client.close(episode_id))
                except (ProtocolError,TransportFailure,OSError) as error:manifest['close_error']=str(error)
            client.disconnect()
            historical=policy.advisors.historical_tickets if isinstance(policy,SupervisedPolicy) else ()
            try:
                report=LiveBudget(args.ai_budget).report(output/'api-usage',run_id=run_id,historical_tickets=historical)
                manifest['api_accounting']={'directory':report['directory'],'budget':report['summary']['budget'],
                                            'new_live_run_id':run_id,'mode':args.ai_mode}
            except (OSError,AIError,ValueError) as error:
                manifest.update(state='failed',api_accounting_error=type(error).__name__+': '+str(error))
            if isinstance(policy,SupervisedPolicy) and policy.advisors.historical_tickets:
                manifest['historical_replay_tickets']=sorted(policy.advisors.historical_tickets)
                manifest['replay_new_api_cost']='0'
            manifest['records']=record_count
            (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    final=output/'controller.jsonl.gz';partial.rename(final)
    manifest['journal']=final.name
    journal_digest=hashlib.sha256()
    with final.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):journal_digest.update(chunk)
    manifest['journal_sha256']=journal_digest.hexdigest()
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'evidence':str(output),'status':manifest.get('episode_status'),
                      'archive_state':manifest['state'],'metrics':manifest.get('metrics')},ensure_ascii=False))
    return 0 if manifest['state']=='complete' else 1


if __name__=='__main__':raise SystemExit(main())
