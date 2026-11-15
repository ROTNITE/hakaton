"""Declared physical outcome metrics and comparable Pareto indicators."""
from __future__ import annotations

from collections import Counter
import math
import random
import statistics


VERSION='metarescue.audit-metrics.v4'


def percentile(values,fraction):
    ordered=sorted(values)
    if not ordered:return None
    index=(len(ordered)-1)*fraction
    low=math.floor(index);high=math.ceil(index)
    return ordered[low]+(ordered[high]-ordered[low])*(index-low)


def distribution(values):
    values=[float(value) for value in values if type(value) in (int,float) and math.isfinite(value)]
    return {'n':len(values),'mean':statistics.fmean(values) if values else None,
            'p50':percentile(values,.5),'p95':percentile(values,.95),
            'minimum':min(values) if values else None,'maximum':max(values) if values else None}


def nondominated(points):
    rows=sorted(set(tuple(float(value) for value in row) for row in points))
    if any(not all(math.isfinite(v) for v in row) for row in rows):raise ValueError('Finite objective values required')
    if len({len(row) for row in rows})>1:raise ValueError('Objective dimensions differ')
    return [row for row in rows if not any(other!=row and all(a<=b for a,b in zip(other,row)) for other in rows)]


def normalize(points,minimum,maximum):
    if len(minimum)!=len(maximum) or any(not low<high for low,high in zip(minimum,maximum)):
        raise ValueError('Predeclared finite normalization bounds required')
    if any(not math.isfinite(v) for v in (*minimum,*maximum)):raise ValueError('Invalid normalization bound')
    if any(len(row)!=len(minimum) for row in points):raise ValueError('Objective dimensions differ')
    return [[(value-low)/(high-low) for value,low,high in zip(row,minimum,maximum)] for row in points]


def hypervolume(points,reference):
    """Exact union of dominated boxes for minimization, up to four dimensions."""
    if not reference or len(reference)>4 or any(not math.isfinite(v) for v in reference):
        raise ValueError('Finite reference with 1..4 dimensions required')
    if any(len(row)!=len(reference) for row in points):raise ValueError('Objective dimensions differ')
    rows=[row for row in nondominated(points) if all(a<r for a,r in zip(row,reference))]
    def volume(rows,ref):
        if not rows:return 0.
        if len(ref)==1:return max(0,ref[0]-min(row[0] for row in rows))
        cuts=sorted({row[0] for row in rows}|{ref[0]});result=0.
        for left,right in zip(cuts,cuts[1:]):
            active=[row[1:] for row in rows if row[0]<=left]
            result+=(right-left)*volume(active,ref[1:])
        return result
    return volume(rows,tuple(reference))


def igd_plus(points,reference_front):
    """Minimization IGD+, on one declared problem with shared normalization."""
    if not reference_front:return None
    if not points:return None
    size=len(reference_front[0])
    if any(len(row)!=size or any(not math.isfinite(v) for v in row) for row in (*points,*reference_front)):
        raise ValueError('Finite, matching objective dimensions required')
    return statistics.fmean(min(math.sqrt(sum(max(a-r,0)**2 for a,r in zip(point,reference)))
                                for point in points) for reference in reference_front)


def paired_interval(pairs,*,seed=2039,samples=5000):
    """Bootstrap independent map means, after averaging optimizer repetitions."""
    by_map={}
    for world,left,right in pairs:
        if not all(type(v) in (int,float) and math.isfinite(v) for v in (left,right)):
            raise ValueError('Pair values must be measured finite numbers')
        by_map.setdefault(world,[]).append(left-right)
    means=[statistics.fmean(values) for _,values in sorted(by_map.items())]
    if not means:return {'maps':0,'pairs':0,'mean_difference':None,'ci95':None}
    rng=random.Random(seed)
    bootstrap=[statistics.fmean(rng.choices(means,k=len(means))) for _ in range(samples)]
    return {'maps':len(means),'pairs':len(pairs),'mean_difference':statistics.fmean(means),
            'ci95':[percentile(bootstrap,.025),percentile(bootstrap,.975)],
            'method':'map-cluster percentile bootstrap, optimizer repetitions averaged within map',
            'seed':seed,'bootstrap_samples':samples}


def coordination_audit(decisions, observations, roles, outcomes):
    """Join submitted changes to the Core step response, role ACK and command result."""
    accepted = Counter()
    entries = []
    for decision in decisions:
        identifier = decision['decision_id']
        operation = decision['operation']
        before_ids = decision['explanation'].get('observation_refs', ())
        before = [observations[key] for key in before_ids if key in observations]
        after = observations.get(decision['request_id'], {})
        revision = after.get('revision')
        confirmed = (type(revision) is int and bool(before) and all(
            type(item.get('revision')) is int and item['revision'] < revision for item in before)
            and after.get('accepted_configuration') == decision['selected_configuration'])
        if confirmed:
            accepted[operation] += 1
        role_links = {
            agent: roles.get((revision, agent, role)) if confirmed else None
            for agent, role in decision['role_assignments'].items()
        }
        command_links = [outcomes.get((identifier, i)) for i in range(len(decision['commands']))]
        has_result = bool(role_links or command_links) and all(role_links.values()) and all(command_links)
        audited = bool(confirmed and before_ids and len(before) == len(before_ids)
                       and decision['explanation'].get('reason_codes') and decision.get('candidate_evaluations')
                       and decision.get('constraint_checks') and has_result)
        entries.append({'decision_id': identifier, 'operation': operation,
                        'observation_ids': list(before_ids), 'step_observation_id': decision['request_id'] if after else None,
                        'accepted_revision': revision if confirmed else None, 'role_confirmation': role_links,
                        'command_outcomes': command_links, 'strictly_joined': audited})
    return accepted, entries


def outcome_metrics(truth,public,controller):
    """Consume streams once. Hidden truth is used only after the saved episode."""
    final=None;telemetry=0;frame_times=[];memory=[]
    disturbances = []
    truth_records = 0
    for row in truth:
        truth_records += 1
        if row['record_type']=='truth_snapshot':
            final=row
        elif row['record_type'] in ('contest_event_started', 'environment_event_applied'):
            payload = row['payload']
            if payload.get('kind') not in ('new_target', 'appearance'):
                disturbances.append({'event_id': payload.get('event_id', payload.get('id')),
                                     'kind': payload.get('kind', payload.get('type')), 'at_s': row['time'],
                                     'trace_id': row.get('trace_id')})
        elif row['record_type']=='agent_telemetry':telemetry+=1
        elif row['record_type']=='render_profile':
            profile=row['payload']
            frame_times.extend(profile.get('frame_ms',()))
            if isinstance(profile.get('working_set_mb'),(int,float)):memory.append(profile['working_set_mb'])
    found={};delivered={};results={};events={};quality=[];delays=[]
    public_records = messages = 0
    observations, role_confirmations, command_outcomes = {}, {}, {}
    transitions = []
    for row in public:
        public_records += 1
        kind=row['record_type'];payload=row['payload']
        if kind in ('target_detected','target_state_changed') and isinstance(payload.get('id'),str):
            identifier=payload['id'];found.setdefault(identifier,payload.get('observed_at',row['time']))
            if payload.get('evacuation_state')=='evacuated':
                delivered.setdefault(identifier,payload.get('observed_at',row['time']))
        elif kind in ('command_result', 'internal_control_result'):
            key = payload['decision_id'], payload['command_index']
            if kind == 'command_result':
                results[key] = payload
            if (payload['delivery_status'] == 'delivered' and payload['validation_status'] == 'accepted'
                    and payload['execution_status'] in ('completed', 'failed', 'cancelled')):
                command_outcomes[key] = {'command_id': payload['command_id'], 'trace_id': row.get('trace_id'),
                                         'execution_status': payload['execution_status']}
        elif kind == 'decision' and payload['operation'] != 'keep':
            transitions.append(payload)
        elif kind == 'message_delivered':
            messages += 1
        elif kind=='event':events[(payload['id'],payload['status'])]=payload
        elif kind=='observation':
            q=payload.get('observation_quality',{});quality.append(q)
            delays.append(q.get('maximum_delay',0))
            observation_id = payload.get('request_id')
            plan = payload.get('metaevolution', {}).get('plan', {})
            revision = plan.get('plan_revision', plan.get('revision'))
            if observation_id:
                observations[observation_id] = {'revision': revision,
                                                'accepted_configuration': plan.get('accepted_configuration')}
                for agent, ack in plan.get('agent_acknowledgements', {}).items():
                    if ack.get('freshness', {}).get('state') == 'current':
                        key = ack.get('plan_revision'), agent, ack.get('role')
                        role_confirmations.setdefault(key, observation_id)
    planning=[];fronts=0;scenario_outcomes=[];ai_requests={};ai_responses={};optimizer_wall=[];decisions=0
    for row in controller:
        kind=row['record_type'];payload=row['payload']
        if kind=='decision':
            decisions+=1;planning.append(payload['planning_wall_s'])
        elif kind=='scenario_trace' and payload.get('type')=='scenario_outcome':scenario_outcomes.append(payload)
        elif kind=='planning_trace':
            trace_type=payload.get('type')
            if trace_type=='planning_result_committed':
                plan=payload.get('result',{}).get('plan',payload.get('plan',{}))
                fronts+=len(plan.get('pareto',()))
                stats=plan.get('stats',{})
                wall=stats.get('wall_s')
                if wall is None and type(stats.get('wall_ms')) in (int,float):wall=stats['wall_ms']/1000
                if wall is not None:optimizer_wall.append(wall)
            elif trace_type=='ai_request':
                role=payload.get('role','unknown');ai_requests[role]=ai_requests.get(role,0)+1
            elif trace_type=='ai_response':
                role=payload.get('role','unknown');ai_responses[role]=ai_responses.get(role,0)+1
    if final is None:
        return {'version':VERSION,'complete':False,'unverified':['native truth snapshot missing']}
    cutoff=final['time']
    all_targets=final['payload']['targets']
    targets=[target for target in all_targets if target.get('available_at',0)<=cutoff+1e-9]
    agents=final['payload']['agents'];total=len(targets)
    rescued=[target for target in targets if target['rescued']]
    weights_complete=all(type(target.get('priority')) in (int,float) for target in targets)
    denominator=sum(t['priority'] for t in targets) if weights_complete else None
    numerator=sum(t['priority'] for t in rescued) if weights_complete else None
    m1=numerator/denominator if denominator else None
    def threshold(fraction):
        need=math.ceil(total*fraction)
        return sorted(found.values())[need-1] if need and len(found)>=need else None
    energy=sum(agent['physical']['consumed_wh'] for agent in agents)
    distance=sum(agent['physical']['distance_m'] for agent in agents)
    failures=sum(result['execution_status']=='failed' for result in results.values())
    rejections=sum(result['validation_status']=='rejected' for result in results.values())
    handovers = sorted(delivered.values())
    for event in disturbances:
        at = event['at_s']
        event['next_handover_delay_s'] = next((t-at for t in handovers if t >= at), None)
    first_disturbance = min((event['at_s'] for event in disturbances), default=None)
    post_disturbance = (sum(t >= first_disturbance for t in handovers)
                        if first_disturbance is not None else None)
    accepted, audit = coordination_audit(transitions, observations, role_confirmations, command_outcomes)
    contacts = [agent['physical'].get('vehicle_contacts') for agent in agents]
    vehicle_contacts = sum(contacts) if contacts and all(type(value) is int for value in contacts) else None
    return {'version':VERSION,'complete':True,'cutoff_s':cutoff,'registered_targets':total,
            'not_yet_available_targets':len(all_targets)-total,
            'rescued':len(rescued),'rescued_fraction':len(rescued)/total if total else None,
            'M1':{'value':m1,'numerator':numerator,'denominator':denominator,'weight_basis':'final registered target priority',
                  'completion_basis':'physical evacuated flag at cutoff','official_score':None},
            'M2': {'physical_disturbances': disturbances, 'post_disturbance_handovers': post_disturbance,
                   'post_disturbance_handover_fraction': post_disturbance/total if post_disturbance is not None and total else None,
                   'rejected_commands': rejections, 'failed_commands': failures, 'official_score': None},
            'M3': {'energy_wh': energy, 'distance_m': distance, 'delivered_message_records': messages,
                   'decisions': decisions, 'planning_wall_s': distribution(planning), 'official_score': None},
            'M4': {'submitted_transitions': dict(Counter(item['operation'] for item in audit)),
                   'accepted_transitions': dict(accepted), 'program_outcomes': scenario_outcomes,
                   'vehicle_contacts': vehicle_contacts, 'official_score': None},
            'M5':{'value':None,'status':'external cross-team implementations not connected'},
            'M6': {'strictly_joined_transitions': sum(item['strictly_joined'] for item in audit),
                   'accepted_transitions': sum(accepted.values()), 'public_records': public_records,
                   'truth_records': truth_records, 'transitions': audit, 'official_score': None},
            'M7': {'public_observations': len(quality), 'truth_telemetry': telemetry,
                   'render_profile_samples': len(frame_times), 'official_score': None},
            'official_total':None,'found':len(found),'first_detected_s':min(found.values(),default=None),
            'found_50_s':threshold(.5),'found_90_s':threshold(.9),
            'first_handover_s':min(delivered.values(),default=None),'last_handover_s':max(delivered.values(),default=None),
            'energy_wh':energy,'distance_m':distance,'telemetry_records':telemetry,
            'command_failures':failures,'command_rejections':rejections,
            'event_records':len(events),'decision_count':decisions,'decision_wall_s':distribution(planning),
            'optimizer_wall_s':distribution(optimizer_wall),'pareto_points':fronts,
            'render_frame_ms':distribution(frame_times),'working_set_mb':distribution(memory),
            'maximum_delivered_delay_s':max(delays,default=None),
            'mean_stale_ratio':statistics.fmean(q.get('stale_data_ratio',0) for q in quality) if quality else None,
            'mean_unknown_ratio':statistics.fmean(q.get('unknown_state_ratio',0) for q in quality) if quality else None,
            'ai_requests':ai_requests,'ai_responses':ai_responses,'scenario_outcomes':scenario_outcomes,
            'unverified':([] if weights_complete else ['priority unavailable in this historical archive'])+
                         ([] if frame_times else ['native render frame profile unavailable'])}
