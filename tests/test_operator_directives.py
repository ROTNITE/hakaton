from copy import deepcopy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from controller.baselines import FixedWorkflow, Job
from controller.decisions import decision
from controller.operator_directives import FORMAT, OperatorDirectives
from test_problem_builder import public_state
from test_scenario_program import CAPABILITIES, COALITION
from controller.scenarios import ScenarioCoordinator


class OperatorDirectiveTests(unittest.TestCase):
    def setUp(self):
        self.state = public_state()
        self.state['time'] = 2
        self.state['agents'].append({'id':'human/непрозрачный', 'kind':'operator', 'status':'active',
                                    'position':None, 'available_actions':[], 'communication':{'reachable':True}})
        self.state['agents'][0]['available_actions'].append({'action':'send_message'})
        self.handler = OperatorDirectives({'extensions':[FORMAT]})

    def order(self, action, **values):
        return {'format':FORMAT, 'id':'req/α', 'revision':1, 'source':'human/непрозрачный',
                'action':action, 'status':'active', 'reason':'operator requirement',
                'issued_at':1, 'updated_at':1, 'expires_at':30, **values}

    def put(self, *orders):
        self.state['mission']['directives'] = list(orders)
        return self.handler.prepare(self.state)

    def test_priority_changes_future_choice_without_mutating_observation_or_loaded_job(self):
        self.state['targets'][0]['priority'] = 2/3
        order = self.order('set_priority', target_id='second:no-prefix', priority=3)
        self.state['mission']['directives'] = [order]
        before = deepcopy(self.state)
        state = self.handler.prepare(self.state)
        policy = FixedWorkflow()
        chosen = policy._choose_target(state['agents'][0], state['targets'])
        self.assertEqual(chosen['id'], 'second:no-prefix')
        self.assertEqual(self.state, before)
        self.assertEqual(self.state['targets'][1]['priority'], 1/3)
        # An active loaded trip remains reserved independently of future priority.
        aid = self.state['agents'][0]['id']
        policy.reset_episode('e')
        job = policy.jobs[aid] = Job('return', 't/first', 'in-flight', 'handover', 0, 'follow_route')
        state['agents'][0]['physical']['carrying'] = True
        state['agents'][0]['physical']['cargo_target_id'] = 't/first'
        policy.decide(state)
        self.assertEqual((job.target, job.pending, job.phase), ('t/first', 'in-flight', 'return'))

    def test_explicitly_lowered_priority_does_not_outrank_an_ordinary_urgent_target(self):
        state = self.put(self.order('set_priority', target_id='t/first', priority=1))
        state['targets'][1]['priority'] = 1
        policy = FixedWorkflow()
        self.assertEqual(policy._choose_target(state['agents'][0], state['targets'])['id'], 'second:no-prefix')

    def test_pending_cancelled_future_and_expired_holds_do_not_stop_agent(self):
        aid = self.state['agents'][0]['id']
        for fields in ({'status':'pending_confirmation'}, {'status':'cancelled'},
                       {'issued_at':3, 'updated_at':3}, {'expires_at':2}):
            with self.subTest(fields=fields):
                state = self.put(self.order('hold', agent_id=aid, **fields))
                self.assertEqual(FixedWorkflow.hold_orders(state), {})
        self.put(self.order('hold', agent_id=aid))
        self.assertEqual(set(FixedWorkflow.hold_orders(self.state)), {aid})

    def test_clarification_is_requested_without_inventing_a_target(self):
        self.put(self.order('message', status='needs_clarification', text='somewhere near the old house'))
        self.assertEqual(self.handler.checks[0]['outcome'], 'request_clarification')
        request = decision(self.state)
        self.handler.apply(self.state, request)
        feedback = request['commands'][0]
        self.assertEqual(feedback['action'], 'send_message')
        self.assertEqual(feedback['parameters']['payload']['interpretation'], 'request_clarification')
        self.assertEqual(feedback['parameters']['recipient_id'], 'human/непрозрачный')
        self.assertEqual(self.state['targets'], public_state()['targets'])

    def test_feedback_requires_delivered_execution_ack_and_is_not_repeated_on_retry(self):
        self.put(self.order('message', status='needs_clarification'))
        request = decision(self.state)
        self.handler.apply(self.state, request)
        result = {'decision_id':request['decision_id'], 'command_index':0,
                  'agent_id':request['commands'][0]['agent_id'],
                  'delivery_status':'delivered', 'execution_status':'in_progress'}
        self.handler.observe({'command_results':[result]})
        self.assertEqual(next(iter(self.handler.feedback.values()))['state'], 'submitted')
        retry = decision(self.state)
        self.handler.apply(self.state, retry)
        self.assertEqual(retry['commands'], [])
        result['execution_status'] = 'completed'
        self.handler.observe({'command_results':[result]})
        self.assertEqual(next(iter(self.handler.feedback.values()))['state'], 'delivered')
        self.state['time'] = 29
        request = decision(self.state)
        self.handler.apply(self.state, request)
        self.assertEqual(request['commands'], [])

    def test_revisions_cancel_and_order_permutation_restore_base_priorities(self):
        older = self.order('set_priority', target_id='second:no-prefix', priority=1)
        newer = self.order('set_priority', id='req/β', updated_at=2, target_id='second:no-prefix', priority=3)
        first = self.put(newer, older)
        second = self.put(older, newer)
        self.assertEqual(first['targets'], second['targets'])
        self.assertEqual(second['targets'][1]['priority'], 1)
        self.assertEqual(self.handler.checks[0]['outcome'], 'superseded_priority')
        newer.update(status='cancelled', revision=2)
        self.assertEqual(self.put(newer)['targets'], self.state['targets'])
        self.assertTrue(self.handler.changed)

    def test_restriction_requires_a_real_delivered_zone(self):
        self.put(self.order('restrict_zone', zone_id='operator-zone-α'))
        self.assertEqual(self.handler.checks[0]['outcome'], 'awaiting_published_restriction')
        self.assertNotIn('zones', self.state)
        self.state['zones'] = [{'id':'operator-zone-α', 'type':'restricted'}]
        self.handler.prepare(self.state)
        self.assertEqual(self.handler.checks[0]['outcome'], 'applied_restriction')

    def test_hold_during_loading_reports_the_real_safe_boundary(self):
        aid = self.state['agents'][0]['id']
        state = self.put(self.order('hold', agent_id=aid))
        policy = FixedWorkflow()
        policy.reset_episode('e')
        job = policy.jobs[aid] = Job('pickup', 't/first', 'loading', 'return', 0, 'pickup')
        request = policy.decide(state)
        self.handler.apply(state, request)
        row = request['metaevolution']['operator_interpretation']['requirements'][0]
        self.assertEqual(row['outcome'], 'waiting_for_safe_service_boundary')
        self.assertFalse(any(c['agent_id']==aid and c['action']=='hold' for c in request['commands']))
        self.assertEqual((job.target, job.phase, job.pending), ('t/first', 'pickup', 'loading'))

    def test_missing_extension_unverified_source_and_unavailable_radio_are_safe(self):
        unknown = OperatorDirectives({})
        self.state['mission']['directives'] = [self.order('set_priority', target_id='t/first', priority=1)]
        self.assertIs(unknown.prepare(self.state), self.state)
        self.state['mission']['directives'][0]['source'] = 'invented-source'
        self.handler.prepare(self.state)
        self.assertEqual(self.handler.checks[0]['outcome'], 'unverified_operator_source')
        self.put(self.order('message', status='needs_clarification'))
        for agent in self.state['agents']:
            agent['available_actions'] = []
        request = decision(self.state)
        self.handler.apply(self.state, request)
        self.assertEqual(request['commands'], [])
        self.assertEqual(self.handler.feedback, {})

    def test_unverified_formatted_hold_is_logged_but_cannot_stop_an_agent(self):
        state = self.put(self.order('hold', source='invented-source', agent_id=self.state['agents'][0]['id']))
        self.assertEqual(self.handler.checks[0]['outcome'], 'unverified_operator_source')
        self.assertEqual(FixedWorkflow.hold_orders(state), {})

    def test_pending_hold_reference_remains_available_for_human_confirmation(self):
        state=self.put(self.order('hold',agent_id=self.state['agents'][0]['id'],status='pending_confirmation'))
        self.assertEqual(state['mission']['directives'][0]['id'],'req/α')
        self.assertEqual(FixedWorkflow.hold_orders(state),{})

    def test_episode_reset_clears_feedback_and_private_looking_extras_are_ignored(self):
        self.state['private_operator_commands'] = [{'action':'evacuate', 'target_id':'hidden'}]
        self.put(self.order('message', status='needs_clarification'))
        request = decision(self.state)
        self.handler.apply(self.state, request)
        self.assertTrue(self.handler.feedback)
        self.state['episode_id'] = 'new-e'
        self.state['mission']['directives'] = []
        self.handler.prepare(self.state)
        self.assertEqual(self.handler.feedback, {})
        self.assertFalse(self.handler.changed)

    def test_active_scenario_program_cannot_bypass_an_operator_hold(self):
        aid=self.state['agents'][0]['id']
        state=self.put(self.order('hold',agent_id=aid))
        state['mission']['status']='active'
        state['metaevolution']['plan']['accepted_configuration']['scenario_ids']=[COALITION]
        state['metaevolution']['plan']['plan_revision']=1
        for actor in state['agents']:actor.setdefault('communication',{'reachable':True})
        policy=SimpleNamespace(completed_sectors=set(),builder=None,jobs={},scenario_reserved=set())
        coordinator=ScenarioCoordinator(CAPABILITIES)
        propose=Mock(return_value=[{'agent_id':aid,'action':'move','parameters':{'target':[90,10,.47]}}])
        coordinator.program=SimpleNamespace(reserved_agents={aid},propose=propose,bind=Mock(),drain=lambda:[],outcome=None)
        coordinator.program_id=COALITION
        coordinator.prepare(state,policy)
        request=decision(state)
        result=coordinator.apply(state,request,policy)
        propose.assert_not_called()
        self.assertEqual(result['commands'],[])


if __name__ == '__main__':
    unittest.main()
