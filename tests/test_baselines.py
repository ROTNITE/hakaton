from copy import deepcopy
import unittest

from controller.baselines import FixedWorkflow, Job, LocalReactive
from test_problem_builder import public_state


class BaselineTests(unittest.TestCase):
    def test_lost_carriers_target_requires_a_new_delivered_confirmation(self):
        state = public_state()
        state['targets'] = state['targets'][:1]
        target = state['targets'][0]
        failed = state['agents'][0]
        reserve = deepcopy(failed)
        reserve.update(id='reserve', position=[60., 10., .47])
        reserve['physical']['at_dock'] = False
        state['agents'].append(reserve)
        failed.update(status='failed', position=[72., 20., .47])
        failed['freshness'] = {'position': {'observed_at': 9.8}}
        state['time'] = 10.
        policy = FixedWorkflow()
        policy.reset_episode(state['episode_id'])
        policy.jobs[failed['id']] = Job('return', target['id'])
        first = policy.decide(state)
        index, investigation = next((i, c) for i, c in enumerate(first['commands']) if c['agent_id'] == reserve['id'])
        self.assertEqual(investigation['action'], 'follow_route')
        x, y, _ = investigation['parameters']['waypoints'][-1]
        self.assertAlmostEqual(x, 72.)
        self.assertAlmostEqual(y, 10.)
        self.assertEqual(policy.reconfirm_after, {target['id']: 9.8})
        policy.observe_response({'status': 'running', 'command_results': [{
            'decision_id': first['decision_id'], 'agent_id': reserve['id'], 'command_index': index,
            'validation_status': 'accepted', 'delivery_status': 'delivered', 'execution_status': 'completed'}]})

        state['time'] = 12.
        target.update(observed_at=11.7, position=[81., 10., .47])
        result = policy.decide(state)
        self.assertEqual(policy.jobs[reserve['id']].target, target['id'])
        self.assertTrue(any(c['agent_id'] == reserve['id'] and c['action'] == 'follow_route' for c in result['commands']))
        self.assertFalse(policy.reconfirm_after)

    def test_pickup_rechecks_current_public_confirmation(self):
        state = public_state()
        carrier = state['agents'][0]
        carrier['position'] = [77., 10., .47]
        target = state['targets'][0]
        target['status'] = 'suspected'
        policy = FixedWorkflow()
        policy.reset_episode(state['episode_id'])
        policy.jobs[carrier['id']] = Job('pickup', target['id'])
        commands = [c for c in policy.decide(state)['commands'] if c['agent_id'] == carrier['id']]
        self.assertEqual([c['action'] for c in commands], ['inspect'])

    def test_controls_issue_routes_with_only_the_fixed_scenario_selection(self):
        state=public_state()
        for policy,operation in ((FixedWorkflow(),'select'),(LocalReactive(),'keep')):
            with self.subTest(policy=type(policy).__name__):
                result=policy.decide(deepcopy(state))
                self.assertEqual(result['operation'],operation)
                self.assertTrue(any(command['action']=='follow_route' for command in result['commands']))

    def test_local_patrol_history_is_independent_for_each_agent(self):
        policy=LocalReactive()
        announced={'size_m':250,'road_axes_m':[25,75,125]}
        one={'id':'alpha','position':[20,20,25]}
        two={**one,'id':'β'}
        first=policy._scan_goal(one,announced)
        self.assertEqual(first,(25,25,25.))
        self.assertNotEqual(policy._scan_goal(one,announced),first)
        self.assertEqual(policy._scan_goal(two,announced),first)

    def test_completed_handover_clears_the_shared_service_position(self):
        state=public_state();policy=FixedWorkflow();policy.decide(deepcopy(state))
        carrier=state['agents'][0];aid=carrier['id'];home=carrier['position'][:]
        carrier['position']=[20,18.3,.54]
        carrier['physical'].update(carrying=True,at_dock=False,dock_position_m=home)
        policy.jobs[aid]=Job('handover',target='t/first')
        request=policy.decide(state)
        index=next(i for i,c in enumerate(request['commands']) if c['agent_id']==aid)
        self.assertEqual(request['commands'][index]['action'],'handover')
        self.assertEqual(policy.jobs[aid].next_phase,'park')
        policy.observe_response({'status':'running','command_results':[{
            'decision_id':request['decision_id'],'agent_id':aid,'command_index':index,
            'validation_status':'accepted','delivery_status':'delivered','execution_status':'completed'}]})
        carrier['physical']['carrying']=False
        state['targets'][0]['evacuation_state']='evacuated'
        result=policy.decide(state)
        command=next(c for c in result['commands'] if c['agent_id']==aid)
        self.assertEqual(command['action'],'follow_route')
        self.assertEqual(command['parameters']['waypoints'][-1][:2],home[:2])
        self.assertEqual(command['parameters']['waypoints'][-2][:2],[32,18])
        self.assertEqual(command['parameters']['waypoints'][-3][:2],[32,14])
        self.assertGreater(sum((x-y)**2 for x,y in zip(home[:2],[20,22])),25)
        self.assertIsNone(policy.jobs[aid].target)
        self.assertEqual(policy.jobs[aid].phase,'park')

    def test_occupied_return_goal_has_an_explicit_decision_trace(self):
        state=public_state();policy=FixedWorkflow();policy.decide(deepcopy(state))
        carrier=state['agents'][0];aid=carrier['id']
        carrier['position']=[80,10,.47];carrier['physical'].update(carrying=True,at_dock=False)
        other=deepcopy(carrier);other['id']='parked/other';other['position']=[20,18.3,.54]
        other['physical']['carrying']=False;state['agents'].append(other)
        policy.jobs[aid]=Job('return',target='t/first')
        request=policy.decide(state)
        failures=request['metaevolution']['workflow']['route_failures']
        failed=next(row for row in failures if row['agent_id']==aid)
        self.assertEqual(failed['phase'],'return')
        self.assertIn('no_known',failed['reason'])
        self.assertFalse(any(c['agent_id']==aid for c in request['commands']))
