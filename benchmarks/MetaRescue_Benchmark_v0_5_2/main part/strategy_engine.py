"""Knowledge-only, short-horizon cooperative strategy proposals for Global AI.

Candidate forecasts are *counterfactual estimates*, not hidden-world rollouts. They
never read World.people, terrain_at(t), event tapes, or the future. Five alternative
operating policies are run through actual Rescue NSGA-II optimizations; simulated
continuations vary only the uncertainty of travel times (not unknown events).
"""
from __future__ import annotations
from dataclasses import replace
import math
from rescue import prepare, get_plan, eval_plan

PROFILE_SEED_OFFSETS = {'balanced':0,'urgent':101,'throughput':211,'energy_saver':307,'cooperative':419}

PROFILES = {
    'balanced': {'time_weight': 1.0, 'energy_weight': .12, 'priority_mode':'normal', 'scout_mode':'coverage'},
    'urgent': {'time_weight': 1.25, 'energy_weight': .06, 'priority_mode':'urgent', 'scout_mode':'risk'},
    'throughput': {'time_weight': 2.25, 'energy_weight': .04, 'priority_mode':'equal', 'scout_mode':'coverage'},
    'energy_saver': {'time_weight': .65, 'energy_weight': 4.0, 'priority_mode':'normal', 'scout_mode':'efficient'},
    'cooperative': {'time_weight': 1.6, 'energy_weight': .2, 'priority_mode':'urgent', 'scout_mode':'hazard_support'},
}


def prioritize(people, mode):
    """AI changes objective weights, never actual victim attributes."""
    if mode == 'urgent':
        return [replace(p,priority=3*p.priority if p.priority>=3 else p.priority) for p in people]
    if mode == 'equal':
        return [replace(p,priority=1) for p in people]
    return list(people)


def continuation_forecast(tasks, people, now, horizon):
    """Three known-state travel scenarios; no privileged future information.

    The slowdown is hypothetical and applied consistently to all policies. A
    long horizon is assessed on the same known victims and currently idle robots.
    """
    scenarios=[]
    for name, multiplier, weight in [('nominal',1.,.45),('delay_10pct',1.10,.35),('delay_25pct',1.25,.20)]:
        saved=0; weighted=0.;completion=0.;energy=0.
        for r, assignments in enumerate(tasks):
            for j,start,finish,tr in assignments:
                adjusted=now+(finish-now)*multiplier
                energy+=tr['energy']*multiplier
                if adjusted <= horizon:
                    saved+=1; weighted+=people[j].priority
                    completion+=people[j].priority*adjusted
        scenarios.append({'scenario':name,'weight':weight,'saved':saved,
            'priority_saved':round(weighted,3),'weighted_completion':round(completion,2),
            'energy_Wh':round(energy,2)})
    expected={
        'saved':round(sum(s['saved']*s['weight'] for s in scenarios),3),
        'priority_saved':round(sum(s['priority_saved']*s['weight'] for s in scenarios),3),
        'weighted_completion':round(sum(s['weighted_completion']*s['weight'] for s in scenarios),3),
        'energy_Wh':round(sum(s['energy_Wh']*s['weight'] for s in scenarios),3),
    }
    return scenarios,expected


def forecast_utility(expected):
    """Uniform comparison across plans; saving victims dominates minor costs."""
    return (expected['priority_saved']*100_000 + expected['saved']*8_000
            - expected['weighted_completion']*.7 - expected['energy_Wh']*.65)


def worthwhile(candidate, baseline, minimum_gain=0.002):
    """Prevent decorative or harmful global plan commits.

    Forecasts are uncertain: this gate only verifies a *predicted*, meaningful
    advantage and can never guarantee the real outcome. Major safety incidents
    are handled independently by deterministic safety rules.
    """
    if candidate['id']==baseline['id']:return False,'BASELINE'
    a=candidate['forecast'];b=baseline['forecast']
    if a['priority_saved']+1e-4<b['priority_saved'] or a['saved']+1e-4<b['saved']:
        return False,'EXPECTED_RESCUE_LOSS'
    if a['priority_saved']>b['priority_saved']+.001 or a['saved']>b['saved']+.001:
        return True,'MORE_RESCUES'
    # A joint scout+rescuer coalition can be worthwhile for its information
    # gain even without immediate rescue ETA improvement. The tasks must be
    # grounded in currently confirmed hazard sectors and cost-bounded.
    if (candidate['id']=='cooperative' and candidate.get('information_gain',0)>0
        and candidate.get('scout_tasks') and a['weighted_completion']<=b['weighted_completion']*1.04
        and a['energy_Wh']<=b['energy_Wh']*1.08):
        return True,'CONFIRMED_HAZARD_INFORMATION_GAIN'
    time_gain=b['weighted_completion']-a['weighted_completion']
    energy_gain=b['energy_Wh']-a['energy_Wh']
    if time_gain>max(2.,minimum_gain*max(1,b['weighted_completion'])) and a['energy_Wh'] <= b['energy_Wh']*1.10:
        return True,'FASTER_RESPONSE'
    # Energy-first trade-off is legitimate if every modelled continuation
    # preserves rescue count AND the time penalty stays bounded.
    same_rescues_all=all(ca['priority_saved']>=cb['priority_saved'] and ca['saved']>=cb['saved']
                         for ca,cb in zip(candidate['continuations'],baseline['continuations']))
    if (same_rescues_all and energy_gain>max(4.,.08*max(1,b['energy_Wh']))
            and a['weighted_completion']<=b['weighted_completion']*1.12):
        return True,'ENERGY_SAVING_WITH_BOUNDED_DELAY'
    if energy_gain>max(4.,.025*max(1,b['energy_Wh'])) and a['weighted_completion']<=b['weighted_completion']*1.04:
        return True,'ENERGY_SAVING'
    return False,'NO_MEASURABLE_GAIN'


class StrategyEngine:
    """Builds 3-5 genuine NSGA-II rescue plans from delivered/known state only."""
    def __init__(self, world):
        self.world=world

    def propose(self, now, pending_people, available_robots, terrain, knowledge_hazard_sectors=(),
                scout_positions=None, scout_complete=False, ready_times=None):
        w=self.world
        people=list(pending_people)
        # Stable bounded forecast complexity at 150x150 / 600 victims.
        people=sorted(people,key=lambda p:(-p.priority,math.dist((p.x,p.y),(1,1)),p.id))[:min(30, max(14,len(available_robots)*2))]
        if not people or not available_robots:
            return []
        real_people,trips=prepare(w,people,terrain=terrain)
        ready_times=ready_times or {}
        available=[max(now,ready_times.get(r,now)) if r in available_robots else w.horizon+1
                   for r in range(w.n_rescuers)]
        proposals=[]
        for profile, params in PROFILES.items():
            working=prioritize(real_people,params['priority_mode'])
            # The optimizer runs the same population budget with distinct
            # deterministic seeds and operating-policy objective weights.
            genome,stats=get_plan(w,working,trips,'nsga2',
                                  w.seed+int(now*100)+PROFILE_SEED_OFFSETS[profile],
                                  now=now,available=available,small=True,policy=profile)
            raw,tasks=eval_plan(genome,real_people,trips,now=now,available=available,horizon=w.horizon)
            continuations,forecast=continuation_forecast(tasks,real_people,now,w.horizon)
            assignments=[]
            for r,items in enumerate(tasks):
                if r not in available_robots or not items:continue
                j,start,finish,tr=items[0]
                if not math.isfinite(finish) or finish>w.horizon:continue
                assignments.append({'robot_id':f'ground_{r+1:02d}',
                                    'target_id':real_people[j].id,'ready_at':round(start,2),
                                    'eta':round(finish,2)})
            # Cooperative mode forms a concrete scout/rescuer task group around
            # a *confirmed* hazard, not an unobserved or guessed sector.
            scout_tasks=[]; scout_extra_energy=0.
            if profile=='cooperative' and scout_complete and scout_positions and knowledge_hazard_sectors:
                hazards=sorted(set(knowledge_hazard_sectors))
                for sec in hazards[:2]:
                    r=min(range(len(scout_positions)), key=lambda i:math.dist(scout_positions[i],w.center(sec)))
                    if any(q['agent_id']==f'drone_{r+1:02d}' for q in scout_tasks):continue
                    scout_tasks.append({'agent_id':f'drone_{r+1:02d}','sector_id':sec})
                    scout_extra_energy+=.69*math.dist(scout_positions[r],w.center(sec))+.55
            if scout_tasks:
                forecast['energy_Wh']=round(forecast['energy_Wh']+scout_extra_energy,3)
                for row in continuations:row['energy_Wh']=round(row['energy_Wh']+scout_extra_energy,3)
            proposals.append({
                'id':profile,'policy':profile,'policy_weights':{k:v for k,v in params.items() if k.endswith('_weight')},
                'scout_mode':params['scout_mode'],'assignments':assignments[:min(4,len(assignments))],
                'scout_tasks':scout_tasks,
                'information_gain':len(scout_tasks),
                'forecast':forecast,'continuations':continuations,
                'nominal_objectives':list(map(lambda n:round(n,3),raw)),
                'utility':round(forecast_utility(forecast),3),
                'estimated_from':'observed_targets_and_known_terrain_only',
                'compute_ms':stats.get('wall_ms',0.)})
        baseline=proposals[0]
        for p in proposals:
            p['eligible'],p['gate_reason']=worthwhile(p,baseline)
        return proposals
