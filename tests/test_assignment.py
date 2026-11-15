from copy import deepcopy
from itertools import product
import random
import unittest
from unittest.mock import patch

from controller.assignment import AssignmentError,assignment_seed,minimum_assignment
from controller.optimization import Crew,RescueProblem,Target,Trip,optimize_rescue
from controller.problem_builder import ProblemBuilder
from controller.strategies import propose
from test_problem_builder import public_state


def problem(costs,*,priorities=None,crew=None,**kwargs):
    targets=[Target('target/'+str(j),p) for j,p in enumerate(priorities or [1]*len(costs[0]))]
    return RescueProblem(targets,crew or [Crew('carrier/'+str(i)) for i in range(len(costs))],
        [[None if c is None else Trip(c,1) for c in row] for row in costs],horizon=1000,**kwargs)


class AssignmentTests(unittest.TestCase):
    def test_manual_example_and_dual_certificate(self):
        # Greedy claims (0,0) at 10, forcing the second carrier to pay 100.
        p=problem([[10,11],[12,100]])
        genome,audit=assignment_seed(p,p.heuristic('greedy'))
        self.assertEqual(genome,([1,0],[1,0]))
        self.assertEqual(audit['objective'],{'matched':2,'priority_units':2000000,
            'duration_us':23000000,'energy_uwh':2000000})
        self.assertEqual(audit['certificate']['primal_cost'],audit['certificate']['dual_cost'])
        self.assertEqual(audit['status'],'optimal')

    def test_sparse_hungarian_matches_exhaustive_optimum_and_duals(self):
        rng=random.Random(2039)
        for rows in range(1,5):
            for columns in range(rows,5):
                for _ in range(12):
                    costs=[[rng.randrange(-15,16) if rng.random()>.3 else None for _ in range(columns)] for _ in range(rows)]
                    # Dedicated zero-cost idle choices guarantee feasibility.
                    costs=[row+[0]*rows for row in costs]
                    choices=[(sum(costs[i][j] for i,j in enumerate(js)),js)
                        for js in product(range(columns+rows),repeat=rows)
                        if len(set(js))==rows and all(costs[i][j] is not None for i,j in enumerate(js))]
                    js,u,v,_=minimum_assignment(costs)
                    value=sum(costs[i][j] for i,j in enumerate(js))
                    self.assertEqual(value,min(choices)[0])
                    self.assertEqual(value,sum(u)+sum(v))
                    self.assertTrue(all(b<=0 for b in v))
                    self.assertTrue(all(u[i]+v[j]<=c for i,row in enumerate(costs) for j,c in enumerate(row) if c is not None))

    def test_lexicographic_cardinality_then_priority_then_time_then_energy(self):
        p=problem([[1,9,None],[1,None,100]],priorities=[100,1,1])
        _,audit=assignment_seed(p,p.heuristic('greedy'))
        self.assertEqual(audit['objective']['matched'],2)
        self.assertEqual(audit['objective']['priority_units'],101000000)
        self.assertEqual(audit['objective']['duration_us'],10000000)
        p=problem([[1,1]],priorities=[1,2]);g,_=assignment_seed(p,p.heuristic('greedy'))
        self.assertEqual(g[0][0],1)
        p=problem([[1,1]])
        p=RescueProblem(p.targets,p.crew,[[Trip(1,3),Trip(1,2)]],horizon=100)
        g,_=assignment_seed(p,p.heuristic('greedy'));self.assertEqual(g[0][0],1)

    def test_busy_energy_unreachable_deadline_and_horizon_exclude_pairs(self):
        p=problem([[1,1,1],[None,2,9]],crew=[Crew('busy',ready_at=5),Crew('free',usable_wh=.5)])
        _,a=assignment_seed(p,p.heuristic('greedy'));self.assertEqual(a['matches'],[])
        p=RescueProblem([Target('late',1,deadline=1),Target('beyond',1)], [Crew('x')],
            [[Trip(2,0),Trip(11,0)]],horizon=10)
        _,a=assignment_seed(p,p.heuristic('greedy'));self.assertEqual(a['candidate_pairs'],[])

    def test_unmatched_targets_remain_and_empty_or_incompatible_crew_are_safe(self):
        p=problem([[1,2,3]],available_now=[False]);base=p.heuristic('greedy')
        g,a=assignment_seed(p,base);self.assertEqual(g,base);self.assertEqual(a['matches'],[])
        p=problem([[1,2,3]]);g,a=assignment_seed(p,p.heuristic('greedy'))
        self.assertEqual(set(g[0]),{0,1,2});self.assertEqual(len(a['unmatched_target_ids']),2)
        p=RescueProblem([],[],[],horizon=10)
        self.assertEqual(assignment_seed(p,([],[]))[1]['status'],'empty')
        with self.assertRaises(ValueError):problem([[1]],available_now=[1])

    def test_empty_carrier_can_plan_before_conditional_handover_is_offered(self):
        state=public_state();ground=state['agents'][0]
        ground['available_actions']=[a for a in ground['available_actions'] if a['action']!='handover']
        p=ProblemBuilder(state['metaevolution']['announced_map']).rescue(state,{})
        _,audit=assignment_seed(p,p.heuristic('greedy'))
        self.assertEqual(len(audit['matches']),1)

    def test_only_delivered_state_used_and_permutation_is_deterministic(self):
        state=public_state();before=deepcopy(state);builder=ProblemBuilder(state['metaevolution']['announced_map'])
        p=builder.rescue(state,{});expected=assignment_seed(p,p.heuristic('greedy'))
        other=deepcopy(state);other['agents'].reverse();other['targets'].reverse()
        other['future_events']=[{'time':1,'secret':'not-observable'}]
        other['metaevolution']['announced_map']['people']=[{'id':'HIDDEN','position':[100,100,0]}]
        p=ProblemBuilder(other['metaevolution']['announced_map']).rescue(other,{})
        self.assertEqual(assignment_seed(p,p.heuristic('greedy')),expected)
        self.assertEqual(state,before)
        other['agents'][0 if other['agents'][0]['kind']=='ground' else 1]['capabilities'].remove('carry')
        p=ProblemBuilder(other['metaevolution']['announced_map']).rescue(other,{})
        self.assertEqual(assignment_seed(p,p.heuristic('greedy'))[1]['matches'],[])

    def test_assignment_seed_can_change_selected_nsga_plan_and_is_opt_in(self):
        p=problem([[10,11],[12,100]])
        old=optimize_rescue(p,1,population=4,generations=0)
        new=optimize_rescue(p,1,population=4,generations=0,initializer='assignment')
        self.assertNotIn('initializer',old)
        self.assertEqual(new['initializer']['status'],'optimal')
        self.assertTrue(new['initializer']['selected_genome_matches'])
        self.assertEqual(old['selected_objectives'][1],31)
        self.assertEqual(new['selected_objectives'][1],23)
        candidates=propose(p,7,population=4,generations=0,rescue_initializer='assignment')
        self.assertTrue(all(c['initializer']['method']=='assignment_lp_v1' for c in candidates))
        with self.assertRaises(ValueError):optimize_rescue(p,7,initializer='unknown')

    def test_deterministic_work_budget_falls_back_to_existing_seeds(self):
        with self.assertRaises(AssignmentError):minimum_assignment([[0,1],[0,1]],work_limit=0)
        p=problem([[10,11],[12,100]])
        old=optimize_rescue(p,7,population=4,generations=0)
        with patch('controller.assignment.minimum_assignment',side_effect=AssignmentError('work_limit')):
            new=optimize_rescue(p,7,population=4,generations=0,initializer='assignment')
        self.assertEqual(new['genome'],old['genome'])
        self.assertEqual(new['initializer']['status'],'fallback')
        self.assertEqual(new['initializer']['reason'],'work_limit')


if __name__=='__main__':unittest.main()
