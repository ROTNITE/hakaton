"""Exact one-wave linear assignment, used only as an optional NSGA-II seed.

Kuhn's primal/dual assignment method; integer shortest augmenting paths.
No world, event tape, simulator or external solver is available here.
"""
from decimal import Decimal,ROUND_HALF_UP


class AssignmentError(ValueError):
    pass


def minimum_assignment(costs,*,work_limit=1000000):
    """Assign each row to a distinct column; None means a forbidden edge.

    Returns columns, row/column dual potentials and relaxation count.
    A zero-cost dummy column per row makes a partial assignment feasible.
    The bounded integer algorithm is deterministic, including ties.
    """
    n=len(costs);m=len(costs[0]) if n else 0
    if m<n or any(len(row)!=m for row in costs):raise AssignmentError('matrix_shape')
    if any(c is not None and type(c) is not int for row in costs for c in row):
        raise AssignmentError('integer_cost_required')
    u=[0]*(n+1);v=[0]*(m+1);owner=[0]*(m+1);work=0
    for row in range(1,n+1):
        owner[0]=row;column=0;used=[False]*(m+1)
        distance=[None]*(m+1);previous=[0]*(m+1)
        while True:
            used[column]=True;i=owner[column];delta=None;next_column=0
            for j in range(1,m+1):
                if used[j]:continue
                work+=1
                if work>work_limit:raise AssignmentError('work_limit')
                c=costs[i-1][j-1]
                if c is not None:
                    reduced=c-u[i]-v[j]
                    if distance[j] is None or reduced<distance[j]:
                        distance[j]=reduced;previous[j]=column
                if distance[j] is not None and (delta is None or distance[j]<delta):
                    delta=distance[j];next_column=j
            if delta is None:raise AssignmentError('no_feasible_assignment')
            for j in range(m+1):
                if used[j]:u[owner[j]]+=delta;v[j]-=delta
                elif distance[j] is not None:distance[j]-=delta
            column=next_column
            if not owner[column]:break
        while column:
            predecessor=previous[column];owner[column]=owner[predecessor];column=predecessor
    selected=[-1]*n
    for j in range(1,m+1):
        if owner[j]:selected[owner[j]-1]=j-1
    if len(set(selected))!=n or any(j<0 or costs[i][j] is None for i,j in enumerate(selected)):
        raise AssignmentError('invalid_assignment')
    primal=sum(costs[i][j] for i,j in enumerate(selected))
    if (primal!=sum(u[1:])+sum(v[1:]) or any(b>0 for b in v[1:]) or
        any(u[i+1]+v[j+1]>c for i,rs in enumerate(costs) for j,c in enumerate(rs) if c is not None)):
        raise AssignmentError('invalid_optimality_certificate')
    return selected,u[1:],v[1:],work


def _units(value):
    return int((Decimal(str(value))*1000000).to_integral_value(rounding=ROUND_HALF_UP))


def assignment_seed(problem,fallback):
    """Lexicographically maximize count, priority, then minimize time/energy.

    Only an available carrier's first complete out-and-back trip participates.
    Later tasks retain the existing heuristic assignments. NSGA-II may improve
    or discard this seed; this is not a global dynamic-mission optimum.
    """
    if problem.m>64 or problem.n>128:raise AssignmentError('problem_size_limit')
    rows=sorted((i for i,c in enumerate(problem.crew) if problem.available_now[i] and c.ready_at<=problem.now),
                key=lambda i:problem.crew[i].id)
    columns=sorted(range(problem.n),key=lambda j:problem.targets[j].id)
    candidates=[];edges={}
    for r in rows:
        crew=problem.crew[r]
        for j in columns:
            target=problem.targets[j];trip=problem.first[r][j]
            if trip is None:continue
            finish=problem.now+trip.duration_s
            if finish>problem.horizon or (target.deadline is not None and finish>target.deadline):continue
            if crew.usable_wh is not None and trip.energy_wh>crew.usable_wh+1e-9:continue
            values=(_units(target.priority),_units(trip.duration_s),_units(trip.energy_wh))
            edges[r,j]=values
            candidates.append({'crew_id':crew.id,'target_id':target.id,'priority_units':values[0],
                               'duration_us':values[1],'energy_uwh':values[2]})
    audit={'method':'assignment_lp_v1','status':'empty','quantization':1000000,
           'candidate_pairs':candidates,'matches':[],'unmatched_target_ids':[t.id for t in problem.targets],
           'objective':{'matched':0,'priority_units':0,'duration_us':0,'energy_uwh':0},'certificate':None}
    genome=(fallback[0][:],fallback[1][:])
    if not rows or not problem.n:return genome,audit
    count=len(rows)
    energy_bound=count*max((e for _,_,e in edges.values()),default=0)
    time_weight=energy_bound+1
    cost_bound=count*max((t for _,t,_ in edges.values()),default=0)*time_weight+energy_bound
    priority_weight=cost_bound+1
    count_weight=count*max((p for p,_,_ in edges.values()),default=0)*priority_weight+cost_bound+1
    costs=[]
    for r in rows:
        row=[]
        for j in columns:
            if (r,j) not in edges:row.append(None);continue
            p,t,e=edges[r,j];row.append(-count_weight-p*priority_weight+t*time_weight+e)
        costs.append(row+[0]*count)
    selected,u,v,work=minimum_assignment(costs)
    matches=[];assigned=set()
    for i,col in enumerate(selected):
        if col>=len(columns):continue
        r,j=rows[i],columns[col];assigned.add(j);genome[1][j]=r
        p,t,e=edges[r,j]
        matches.append(j)
        audit['matches'].append({'crew_id':problem.crew[r].id,'target_id':problem.targets[j].id})
        for key,value in (('matched',1),('priority_units',p),('duration_us',t),('energy_uwh',e)):
            audit['objective'][key]+=value
    genome=(matches+[j for j in genome[0] if j not in assigned],genome[1])
    audit.update(status='optimal',unmatched_target_ids=[t.id for j,t in enumerate(problem.targets) if j not in assigned],
        relaxations=work,certificate={'primal_cost':str(sum(costs[i][j] for i,j in enumerate(selected))),
            'dual_cost':str(sum(u)+sum(v)),'row_ids':[problem.crew[r].id for r in rows],
            'target_columns':[problem.targets[j].id for j in columns],'dummy_columns':count,
            'row_potentials':[str(x) for x in u],'column_potentials':[str(x) for x in v],
            'count_weight':str(count_weight),'priority_weight':str(priority_weight),'time_weight':str(time_weight)})
    return genome,audit
