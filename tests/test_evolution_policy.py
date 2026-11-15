from concurrent.futures import Future
from copy import deepcopy
import time
import unittest
from unittest.mock import patch

from controller.policy import EvolutionPolicy,PAIRS
from controller.baselines import Job
from controller.problem_builder import ProblemBuilder
from test_problem_builder import public_state


class DeferredExecutor:
    def __init__(self):self.tasks=[]
    def submit(self,function,*args):
        future=Future();self.tasks.append((future,function,args));return future
    def complete(self):
        for future,function,args in self.tasks:
            if not future.done():
                try:future.set_result(function(*args))
                except BaseException as error:future.set_exception(error)


def accepted(state,request,at):
    current=deepcopy(state);current['time']=at;current['request_id']='frame-'+str(at)
    current['metaevolution']['plan']['accepted_configuration']=request['selected_configuration']
    current['metaevolution']['plan']['desired_role_assignments']=request['role_assignments']
    return current


class EvolutionPolicyTests(unittest.TestCase):
    def create(self,pair='nsga2_nsga2',**kwargs):
        executor=DeferredExecutor()
        policy=EvolutionPolicy(pair=pair,seed=7,executor=executor,population_scout=8,generations_scout=2,
                               population_rescue=8,generations_rescue=2,**kwargs)
        return policy,executor

    def test_assignment_seed_reaches_committed_rescue_plan_and_commands(self):
        policy,executor=self.create(rescue_initializer='assignment')
        state=public_state();request=policy.decide(state);executor.complete()
        current=accepted(state,request,1);policy.observe_response({'status':'running','observation':current,'time':1,'command_results':[]})
        command=policy.decide(current)
        audit=policy.last_rescue_result['plan']['initializer']
        self.assertEqual(audit['status'],'optimal')
        self.assertTrue(audit['matches'])
        aid=state['agents'][0]['id']
        self.assertTrue(any(c['agent_id']==aid for c in command['commands']))
        self.assertEqual(policy.jobs[aid].target,policy.last_rescue_result['plan']['routes'][aid][0])
        with self.assertRaises(ValueError):self.create(pair='greedy_greedy',rescue_initializer='assignment')

    def test_parking_completion_replans_rescue_availability_immediately(self):
        policy,_=self.create();state=public_state();policy.decide(state);aid=state['agents'][0]['id']
        policy.jobs[aid]=Job('park',pending='parking-command',next_phase='choose',action='follow_route')
        policy.observe_response({'status':'running','observation':state,'time':1,'command_results':[{
            'decision_id':'parking-command','agent_id':aid,'command_index':0,
            'validation_status':'accepted','delivery_status':'delivered','execution_status':'completed'}]})
        self.assertEqual(policy.jobs[aid].phase,'choose')
        self.assertEqual(policy.replan_requested,{'rescue'})
        self.assertTrue(any(t.get('reason')=='service_availability_changed' for t in policy.drain_traces()))

    def test_pending_optimizers_do_not_block_step_generation(self):
        policy,executor=self.create();state=public_state();began=time.perf_counter()
        request=policy.decide(state)
        self.assertLess(time.perf_counter()-began,1)
        self.assertEqual(len(executor.tasks),2)
        self.assertFalse(any(f.done() for f,_,_ in executor.tasks))
        self.assertEqual(request['commands'],[])
        current=accepted(state,request,1)
        policy.observe_response({'status':'running','observation':current,'time':1,'command_results':[]})
        self.assertEqual(policy.current_observation['time'],1)
        second=policy.decide(current)
        self.assertEqual(second['operation'],'keep')
        self.assertEqual(second['commands'],[])

    def test_both_nsga_results_dispatch_real_commands_with_opaque_ids(self):
        policy,executor=self.create();state=public_state();first=policy.decide(state)
        current=accepted(state,first,1)
        policy.observe_response({'status':'running','observation':current,'time':1,'command_results':[]})
        executor.complete();request=policy.decide(current)
        self.assertEqual(len(request['commands']),2)
        summaries=request['metaevolution']['optimization']['planners']
        self.assertEqual(set(summaries),{'scout','rescue'})
        self.assertTrue(all(v['stats']['evaluations']>0 for v in summaries.values()))
        self.assertEqual(set(c['agent_id'] for c in request['commands']),set(a['id'] for a in state['agents']))
        self.assertTrue(any(t['type']=='planning_result_committed' for t in policy.drain_traces()))

    def test_cancelled_sector_remains_pending_for_the_next_attempt(self):
        policy,executor=self.create();state=public_state();first=policy.decide(state)
        current=accepted(state,first,1);executor.complete();request=policy.decide(current)
        drone=next(a for a in state['agents'] if a['kind']=='aerial');job=policy.jobs[drone['id']]
        sector=policy.scout_active[drone['id']]
        response={'status':'running','observation':current,'time':2,'command_results':[
            {'decision_id':job.pending,'agent_id':drone['id'],'command_index':job.pending_index,
             'validation_status':'accepted','delivery_status':'delivered','execution_status':'cancelled'}]}
        policy.observe_response(response)
        self.assertNotIn(sector,policy.completed_sectors)
        self.assertIn(sector,policy.scout_queues[drone['id']])

    def test_late_result_is_discarded_and_all_five_pairs_use_the_same_executor(self):
        for pair in PAIRS:
            with self.subTest(pair=pair):
                policy,executor=self.create(pair);state=public_state();first=policy.decide(state)
                current=accepted(state,first,40);executor.complete();request=policy.decide(current)
                self.assertEqual(request['commands'],[])
                self.assertTrue(any(t['type']=='planning_result_discarded' for t in policy.drain_traces()))

    def test_scout_replan_keeps_current_sector_until_observed_dwell_completes(self):
        policy,executor=self.create();state=public_state();first=policy.decide(state)
        current=accepted(state,first,1);executor.complete();policy.decide(current)
        aid=next(a['id'] for a in state['agents'] if a['kind']=='aerial')
        sector=policy.scout_active[aid];goal=(*policy.scan_positions[sector],policy.scan_altitudes[aid])
        # A replacement plan deliberately excludes the already executing sector.
        replacement=policy._solve_scout(policy.builder,current,{sector},False)
        replacement['altitudes'][aid]+=10
        future=Future();future.set_result(replacement)
        policy.futures['scout']={'future':future,'time':1,'generation':policy.generation};policy._poll()
        self.assertIn(sector,policy.scan_positions)
        self.assertEqual(policy.scout_queues[aid][0],sector)
        job=policy.jobs[aid]
        policy.observe_response({'status':'running','observation':current,'time':2,'command_results':[
            {'decision_id':job.pending,'agent_id':aid,'command_index':job.pending_index,
             'validation_status':'accepted','delivery_status':'delivered','execution_status':'completed'}]})
        after=deepcopy(current);after['time']=5
        drone=next(a for a in after['agents'] if a['id']==aid);drone['position']=list(goal)
        drone.setdefault('freshness',{})['position']={'observed_at':5}
        policy.decide(after)
        self.assertIn(sector,policy.completed_sectors)

    def test_failed_scout_with_no_future_queue_releases_its_unfinished_sector(self):
        policy,executor=self.create();state=public_state();first=policy.decide(state)
        current=accepted(state,first,1);executor.complete();policy.decide(current)
        aid=next(a['id'] for a in state['agents'] if a['kind']=='aerial');sector=policy.scout_active[aid]
        policy.scout_queues.pop(aid)
        next(a for a in current['agents'] if a['id']==aid)['status']='failed'
        policy.current_observation=current;policy._schedule()
        self.assertNotIn(aid,policy.scout_active);self.assertNotIn(sector,policy.completed_sectors)

    def test_previously_selected_profile_is_rejected_when_new_forecast_loses_rescues(self):
        policy,_=self.create(strategy_candidates=True);state=public_state();policy.strategy_profile='energy'
        choices=[{'id':'balanced','routes':{},'stats':{},'eligible':False,'gate_reason':'BASELINE'},
                 {'id':'energy','routes':{},'stats':{},'eligible':False,'gate_reason':'EXPECTED_RESCUE_LOSS'}]
        with patch('controller.policy.propose',return_value=choices):
            result=policy._solve_rescue(ProblemBuilder(state['metaevolution']['announced_map']),state,{})
        self.assertEqual(result['plan']['id'],'balanced')

    def test_new_episode_does_not_inherit_old_global_strategy(self):
        policy,_=self.create();policy.current_observation=public_state();policy.strategy_profile='energy';policy.reset_episode('next-episode')
        self.assertEqual(policy.strategy_profile,'balanced')
        with self.assertRaises(ValueError):policy.request_replan(reason='old_observation_is_not_current')

    def test_profile_is_captured_at_submission_and_superseded_worker_cannot_commit(self):
        policy,executor=self.create(strategy_candidates=True);state=public_state();first=policy.decide(state)
        future=policy.futures['rescue']['future'];policy.strategy_profile='energy';executor.complete()
        self.assertEqual(future.result()['plan']['id'],'balanced')
        policy.decide(accepted(state,first,1))
        self.assertIsNone(policy.last_rescue_result)
        self.assertEqual(policy.futures['rescue']['strategy_profile'],'energy')
        self.assertTrue(any(t.get('reason')=='strategy_superseded' for t in policy.drain_traces()))

    def test_repeated_replan_triggers_keep_worker_count_bounded(self):
        policy,executor=self.create();state=public_state();first=policy.decide(state)
        for _ in range(50):policy.request_replan(reason='known_environment_change')
        self.assertEqual(len(executor.tasks),2)
        executor.complete();request=policy.decide(accepted(state,first,1))
        self.assertEqual(request['commands'],[])
        self.assertEqual(len(executor.tasks),4)
        self.assertEqual({entry['revision'] for entry in policy.futures.values()},{50})
        self.assertEqual(policy.replan_requested,set())
        self.assertEqual(sum(t.get('reason')=='new_replan_request' for t in policy.drain_traces()),2)


if __name__=='__main__':unittest.main()
