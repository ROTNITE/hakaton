from copy import deepcopy
import unittest

from controller.baselines import FixedWorkflow
from controller.optimization import optimize_rescue,optimize_scout
from controller.problem_builder import ProblemBuilder


def public_state():
    world={'bounds':{'kind':'box','min':[0,0,-12],'max':[250,250,90]},
        'base':{'kind':'box','min':[0,0,-.2],'max':[65,40,.2]},'base_position':[20,22,0],
        'road_axes_m':[10,56,102,148,194,240],'road_width_m':8.5,'buildings':[],
        'navigation':{'kind':'road_surface_graph.v1','road_surface_z_m':.04,'base_surface_z_m':.11,
                      'sidewalk_surface_z_m':.23,'ground_clearance_m':.43,'max_step_m':.1}}
    def actor(identifier,kind,pose,speed):
        return {'id':identifier,'kind':kind,'position':pose,'status':'active','capabilities':['move','sense','carry'],
                'physical':{'speed_limit_m_s':speed,'unlimited_energy':True,'remaining_wh':220,
                            'capacity_wh':220,'radius_m':1.65 if kind=='aerial' else 1.45},
                'available_actions':[{'action':a} for a in ('move','follow_route','hold','observe','inspect','pickup','handover')]}
    agents=[actor('opaque:g/β','ground',[32,22,.728],3),actor('not-a-drone-prefix','aerial',[43.5,20,.31],10)]
    agents[0]['physical'].update(at_dock=True,dock_exit_waypoints=[[32,18,.728],[63,18,.728],[63,10,.728]])
    targets=[{'id':identifier,'kind':'person','status':'confirmed','position':[x,10,.06],
              'confidence':1,'observed_at':0,'priority':priority,'evacuation_state':'waiting'}
             for identifier,x,priority in (('t/first',80,1.),('second:no-prefix',100,1/3))]
    return {'protocol_version':'1.0','episode_id':'e','request_id':'r','time':0,
            'mission':{'termination':{'horizon':480}},'agents':agents,'targets':targets,
            'metaevolution':{'announced_map':world,'plan':{'accepted_configuration':{'scenario_ids':[],
             'parameters':{},'synthesized_scenario':None},'desired_role_assignments':{}}}}


class ProblemBuilderTests(unittest.TestCase):
    def test_parking_agent_cannot_reserve_work_while_an_idle_carrier_waits(self):
        state=public_state();parking=state['agents'][0]
        idle=deepcopy(parking);idle['id']='idle-rescuer';idle['position']=[35.5,22,.728]
        state['agents'].append(idle);parking['position']=[43.17,19.52,.54]
        parking['physical'].update(state='external_route',stop_reason='external_hold',route_finished=False)
        problem=ProblemBuilder(state['metaevolution']['announced_map']).rescue(
            state,{parking['id']:{'target_id':None,'phase':'park'}})
        self.assertEqual([c.id for c in problem.crew],['idle-rescuer'])
        plan=optimize_rescue(problem,7,population=8,generations=2)
        self.assertTrue(plan['routes']['idle-rescuer'])

    def test_hidden_extra_data_is_ignored_and_observation_is_not_modified(self):
        state=public_state();state['targets']=[]
        state['metaevolution']['announced_map']['people']=[{'id':'SECRET','position':[90,90,0]}]
        state['future_events']=[{'kind':'collapse','time':40}]
        before=deepcopy(state);builder=ProblemBuilder(state['metaevolution']['announced_map'])
        rescue=builder.rescue(state,{})
        self.assertEqual(rescue.n,0)
        scout=builder.scout(state)
        self.assertEqual(scout.problem.n,25)
        self.assertNotIn('SECRET',scout.positions)
        self.assertEqual(state,before)

    def test_opaque_renaming_and_array_permutation_keep_known_problem_objectives(self):
        state=public_state();builder=ProblemBuilder(state['metaevolution']['announced_map'])
        expected=optimize_rescue(builder.rescue(state,{}),7,population=8,generations=2)['selected_objectives']
        other=deepcopy(state);other['agents'].reverse();other['targets'].reverse()
        for i,a in enumerate(other['agents']):a['id']='arbitrary-'+str(i)
        for i,t in enumerate(other['targets']):t['id']='renamed-'+str(i)
        adapted=ProblemBuilder(other['metaevolution']['announced_map'])
        actual=optimize_rescue(adapted.rescue(other,{}),7,population=8,generations=2)['selected_objectives']
        self.assertEqual(actual,expected)

    def test_busy_carrier_finishes_existing_task_before_a_reserved_next_trip(self):
        state=public_state();carrier=state['agents'][0]
        carrier['position']=[80,10,.47];carrier['status']='busy';carrier['physical']['carrying']=True
        state['targets'][0]['evacuation_state']='loaded'
        builder=ProblemBuilder(state['metaevolution']['announced_map'])
        problem=builder.rescue(state,{carrier['id']:{'target_id':'t/first','phase':'return'}})
        self.assertEqual([t.id for t in problem.targets],['second:no-prefix'])
        self.assertGreater(problem.crew[0].ready_at,state['time'])
        self.assertEqual(problem.first,problem.trips)

    def test_finite_energy_and_completed_sectors_are_real_constraints(self):
        state=public_state();state['agents'][0]['physical'].update(unlimited_energy=False,remaining_wh=1)
        builder=ProblemBuilder(state['metaevolution']['announced_map'])
        plan=optimize_rescue(builder.rescue(state,{}),7,population=8,generations=2)
        self.assertEqual(list(plan['routes'].values()),[[]])
        scout=builder.scout(state,completed={'sector-0-0'})
        self.assertEqual(scout.problem.n,24)
        self.assertNotIn('sector-0-0',scout.positions)
        self.assertTrue(optimize_scout(scout.problem,7,population=8,generations=2)['pareto'])

    def test_common_executor_dispatches_independent_agents_in_one_step(self):
        state=public_state();policy=FixedWorkflow()
        request=policy.decide(state)
        self.assertEqual(len(request['commands']),2)
        self.assertEqual({c['agent_id'] for c in request['commands']},{a['id'] for a in state['agents']})
        for index,command in enumerate(request['commands']):
            self.assertEqual(policy.jobs[command['agent_id']].pending_index,index)


if __name__=='__main__':unittest.main()
