"""Five v0.5.2 policy alternatives and three known-state continuations.

Adapted from strategy_engine.py. These estimates never simulate hidden events.
An AI may select an offered ID; it cannot supply its own evaluation numbers.
"""
from dataclasses import replace

from controller.optimization import PROFILE_SEED_OFFSETS,RescueProblem,optimize_rescue

PROFILES={
    'balanced':{'time_weight':1.,'energy_weight':.12,'priority_mode':'normal','scout_mode':'coverage'},
    'urgent':{'time_weight':1.25,'energy_weight':.06,'priority_mode':'urgent','scout_mode':'risk'},
    'throughput':{'time_weight':2.25,'energy_weight':.04,'priority_mode':'equal','scout_mode':'coverage'},
    'energy_saver':{'time_weight':.65,'energy_weight':4.,'priority_mode':'normal','scout_mode':'efficient'},
    'cooperative':{'time_weight':1.6,'energy_weight':.2,'priority_mode':'urgent','scout_mode':'hazard_support'},
}


def continuation_forecast(tasks,targets,now,horizon):
    scenarios=[]
    for name,multiplier,weight in (('nominal',1.,.45),('delay_10pct',1.10,.35),('delay_25pct',1.25,.20)):
        saved=0;priority=0.;completion=0.;energy=0.
        for assignments in tasks:
            for j,start,finish,trip in assignments:
                adjusted=now+(finish-now)*multiplier
                energy+=trip.energy_wh*multiplier
                if adjusted<=horizon:
                    saved+=1;priority+=targets[j].priority;completion+=targets[j].priority*adjusted
        scenarios.append({'scenario':name,'weight':weight,'saved':saved,'priority_saved':round(priority,3),
                          'weighted_completion':round(completion,2),'energy_Wh':round(energy,2)})
    expected={key:round(sum(s[key]*s['weight'] for s in scenarios),3)
              for key in ('saved','priority_saved','weighted_completion','energy_Wh')}
    return scenarios,expected


def forecast_utility(expected):
    return expected['priority_saved']*100000+expected['saved']*8000-expected['weighted_completion']*.7-expected['energy_Wh']*.65


def worthwhile(candidate,baseline,minimum_gain=.002):
    if candidate['id']==baseline['id']:return False,'BASELINE'
    a,b=candidate['forecast'],baseline['forecast']
    if a['priority_saved']+1e-4<b['priority_saved'] or a['saved']+1e-4<b['saved']:
        return False,'EXPECTED_RESCUE_LOSS'
    if a['priority_saved']>b['priority_saved']+.001 or a['saved']>b['saved']+.001:return True,'MORE_RESCUES'
    if (candidate['id']=='cooperative' and candidate.get('information_gain',0)>0 and candidate.get('scout_tasks') and
        a['weighted_completion']<=b['weighted_completion']*1.04 and a['energy_Wh']<=b['energy_Wh']*1.08):
        return True,'CONFIRMED_HAZARD_INFORMATION_GAIN'
    time_gain=b['weighted_completion']-a['weighted_completion'];energy_gain=b['energy_Wh']-a['energy_Wh']
    if time_gain>max(2.,minimum_gain*max(1,b['weighted_completion'])) and a['energy_Wh']<=b['energy_Wh']*1.10:
        return True,'FASTER_RESPONSE'
    same_rescues_all=all(ca['priority_saved']>=cb['priority_saved'] and ca['saved']>=cb['saved']
                         for ca,cb in zip(candidate['continuations'],baseline['continuations']))
    if same_rescues_all and energy_gain>max(4.,.08*max(1,b['energy_Wh'])) and a['weighted_completion']<=b['weighted_completion']*1.12:
        return True,'ENERGY_SAVING_WITH_BOUNDED_DELAY'
    if energy_gain>max(4.,.025*max(1,b['energy_Wh'])) and a['weighted_completion']<=b['weighted_completion']*1.04:
        return True,'ENERGY_SAVING'
    return False,'NO_MEASURABLE_GAIN'


def propose(problem,seed,*,population=26,generations=17,cooperative_scout_tasks=(),rescue_initializer='heuristic'):
    if not problem.n or not problem.m:return []
    proposals=[]
    for profile,parameters in PROFILES.items():
        mode=parameters['priority_mode']
        targets=[replace(t,priority=3*t.priority if t.priority>=3 else t.priority) if mode=='urgent' else
                 replace(t,priority=1) if mode=='equal' else t for t in problem.targets]
        working=RescueProblem(targets,problem.crew,problem.trips,horizon=problem.horizon,
                              now=problem.now,first_trips=problem.first,available_now=problem.available_now)
        plan=optimize_rescue(working,seed+int(problem.now*100)+PROFILE_SEED_OFFSETS[profile],
                            population=population,generations=generations,policy=profile,initializer=rescue_initializer)
        raw,tasks=problem.simulate(plan['genome'])
        continuations,forecast=continuation_forecast(tasks,problem.targets,problem.now,problem.horizon)
        scout_tasks=list(cooperative_scout_tasks) if profile=='cooperative' else []
        if scout_tasks:
            extra=sum(task['estimated_energy_wh'] for task in scout_tasks)
            forecast['energy_Wh']=round(forecast['energy_Wh']+extra,3)
            for row in continuations:row['energy_Wh']=round(row['energy_Wh']+extra,3)
        proposals.append({'id':profile,'policy':profile,'policy_weights':{k:v for k,v in parameters.items() if k.endswith('_weight')},
            'scout_mode':parameters['scout_mode'],'routes':plan['routes'],'genome':plan['genome'],
            'forecast':forecast,'continuations':continuations,'nominal_objectives':list(raw),
            'scout_tasks':scout_tasks,'information_gain':len(scout_tasks),'utility':forecast_utility(forecast),
            'agent_requirements':{c.id:{'energy_wh':sum(trip.energy_wh for _,_,_,trip in tasks[r]),
                'ready_at':c.ready_at,'usable_wh':c.usable_wh,'target_ids':[problem.targets[j].id for j,_,_,_ in tasks[r]]}
                for r,c in enumerate(problem.crew)},
            'pareto':plan['pareto'],'stats':plan['stats'],'estimated_from':'delivered_targets_and_known_geometry_only'})
        if 'initializer' in plan:proposals[-1]['initializer']=plan['initializer']
    for p in proposals:p['eligible'],p['gate_reason']=worthwhile(p,proposals[0])
    return proposals
