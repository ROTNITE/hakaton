from copy import deepcopy
import json
from pathlib import Path
import unittest

from controller.advisor import Advisors
from controller.ai import Mock
from controller.ai_contracts import AIError
from controller.ai_policy import SupervisedPolicy
from controller.baselines import Job
from controller.decisions import decision
from controller.problem_builder import ProblemBuilder
from controller.scenarios import COORDINATION, COVERAGE, ScenarioCoordinator, configuration
from test_advisor import Deferred
from test_problem_builder import public_state


class AIPolicyTests(unittest.TestCase):
    def create(self,*,local_enabled=True):
        executor=Deferred();mail=Deferred();provider=Mock();advisors=Advisors(provider,executor=mail)
        policy=SupervisedPolicy(provider,advisors=advisors,executor=executor,local_enabled=local_enabled,
            population_scout=8,generations_scout=2,population_rescue=8,generations_rescue=2)
        return policy,executor,mail

    def test_new_episode_resets_application_counts_and_delivered_context(self):
        policy,_,_=self.create();policy.current_observation=public_state();policy.applied={'global':2,'local':4}
        policy.reset_episode('new-episode')
        self.assertEqual(policy.applied,{'global':0,'local':0});self.assertIsNone(policy.current_observation)

    def test_global_only_runs_planning_and_keeps_the_local_mailbox_empty(self):
        policy,executor,mail=self.create(local_enabled=False);state=public_state()
        policy.decide(state);executor.complete();state['time']=1
        result=policy.decide(state)
        self.assertTrue(any(command['action']=='follow_route' for command in result['commands']))
        self.assertFalse(result['metaevolution']['ai']['local_enabled'])
        self.assertFalse(policy.first_advisory_queue)
        self.assertEqual([args[0].role for _,_,args in mail.tasks],['global'])
        self.assertTrue(policy.automatic_route_recovery)

    def test_global_selection_changes_future_queue_without_interrupting_carried_person(self):
        policy,_,_=self.create();state=public_state();policy.reset_episode(state['episode_id']);policy.current_observation=state
        rover=state['agents'][0];aid=rover['id'];rover['physical']['carrying']=True
        policy.jobs[aid]=Job('return','already-loaded','old-route','handover',0,'follow_route')
        policy.rescue_queues={aid:['t/first','second:no-prefix']}
        base={'id':'balanced','routes':deepcopy(policy.rescue_queues),
              'forecast':{'saved':2,'priority_saved':4,'weighted_completion':600,'energy_Wh':100},
              'continuations':[{'saved':2,'priority_saved':4}]*3}
        better={**deepcopy(base),'id':'urgent','routes':{aid:['second:no-prefix','t/first']},
                'forecast':{**base['forecast'],'weighted_completion':500}}
        policy.latest_strategy_candidates=[base,better]
        policy.last_rescue_result={'based_agents':{aid:deepcopy(rover)}}
        policy._commit_global('urgent',state)
        self.assertEqual(policy.strategy_profile,'urgent');self.assertEqual(policy.ai_version,1)
        self.assertEqual(policy.jobs[aid].pending,'old-route');self.assertEqual(policy.jobs[aid].target,'already-loaded')
        self.assertTrue(rover['physical']['carrying']);self.assertEqual(policy.applied['global'],1)
        self.assertEqual(policy.rescue_queues[aid],['second:no-prefix','t/first'])
        self.assertEqual(policy.patrol_mode,'risk')

    def test_patrol_strategy_leaves_primary_and_active_flight_intact(self):
        policy,executor,_=self.create(local_enabled=False);state=public_state()
        policy.reset_episode(state['episode_id']);policy.current_observation=state
        policy.builder=ProblemBuilder(state['metaevolution']['announced_map'])
        drone=state['agents'][1]['id'];sector=next(iter(policy.builder.positions))
        policy.patrol_mode='risk'
        policy._schedule()
        primary=next(args for _,function,args in executor.tasks if function==policy._solve_scout)
        self.assertEqual(primary[-2:],(False,'coverage'))
        executor.complete();policy._poll()
        self.assertEqual(policy.last_scout_result['scout_mode'],'coverage')
        policy.completed_sectors=set(policy.builder.positions)
        policy.scout_active[drone]=sector;policy.scout_queues[drone]=[sector]
        policy.scout_goals[drone]=(25,25,25)
        policy.request_replan(planners=('scout',),reason='validated_global_patrol_profile')
        policy._schedule()
        patrol=next(args for future,function,args in executor.tasks if function==policy._solve_scout and not future.done())
        self.assertEqual(patrol[-2:],(True,'risk'));self.assertIn(sector,patrol[2])
        executor.complete();policy._poll()
        self.assertEqual(policy.last_scout_result['scout_mode'],'risk')
        self.assertEqual(policy.scout_queues[drone][0],sector)
        self.assertEqual(policy.scout_goals[drone],(25,25,25))

    def test_cooperative_hazard_revisit_is_scheduled_behind_existing_patrol(self):
        policy, executor, _ = self.create(local_enabled=False)
        state = public_state()
        policy.reset_episode(state['episode_id'])
        policy.current_observation = state
        rover, drone = state['agents']
        aid, scout = rover['id'], drone['id']
        state['zones'] = [{'type':'hazard','geometry':{'type':'box','min':[55, 3, 0],'max':[60, 8, 3]},
                           'received_at':0,'surface':{'active':True,'ground_blocked':False,
                                                      'surface_multiplier':1.,'visibility':.4}}]
        policy._update_navigation(state)
        policy.completed_sectors = set(policy.builder.positions)
        policy.scout_active = {scout:'sector-0-0'}
        policy.scout_goals = {scout:(47,25,25)}
        policy.scout_queues = {scout:['sector-0-0','sector-2-2']}
        policy.scan_altitudes = {scout:25}
        policy._schedule()
        executor.complete()
        policy._poll()
        cooperative = next(c for c in policy.latest_strategy_candidates if c['id']=='cooperative')
        self.assertTrue(cooperative['eligible'])
        self.assertEqual(cooperative['scout_tasks'][0]['sector_id'], 'sector-1-0')
        policy._commit_global('cooperative', state)
        policy._schedule()
        executor.complete()
        policy._poll()
        self.assertEqual(policy.scout_queues[scout][:2], ['sector-0-0','sector-1-0'])
        self.assertEqual(policy.scout_goals[scout], (47,25,25))
        self.assertEqual(policy.last_rescue_result['plan']['id'], 'cooperative')

    def test_last_primary_sector_exposes_already_delivered_hazards_to_global(self):
        policy, executor, mail = self.create(local_enabled=False)
        state = public_state()
        state['zones'] = [{'type':'hazard','geometry':{'type':'box','min':[55,3,0],'max':[60,8,3]},
                           'received_at':0,'surface':{'active':True,'ground_blocked':False,
                                                       'surface_multiplier':1.,'visibility':.4}}]
        policy.reset_episode(state['episode_id'])
        policy.current_observation = state
        policy._update_navigation(state)
        drone = state['agents'][1]
        aid, last_sector = drone['id'], 'sector-0-0'
        drone['position'] = [25,25,25]
        nearby = deepcopy(drone)
        nearby.update(id='nearby-scout',position=[75,12,25])
        state['agents'].append(nearby)
        policy.scan_altitudes = {aid:25, nearby['id']:25}
        policy.completed_sectors = set(policy.builder.positions) - {last_sector}
        policy.scout_active = {aid:last_sector}
        policy.scout_goals = {aid:(25,25,25)}
        policy.arrivals = {aid:(last_sector,0)}
        policy.scout_queues = {aid:[last_sector]}

        policy._schedule()
        executor.complete()
        policy._poll()
        self.assertTrue(any(policy.rescue_queues.values()))
        self.assertFalse(any(c['scout_tasks'] for c in policy.latest_strategy_candidates))
        queues = deepcopy(policy.rescue_queues)

        state['time'] = 3
        self.assertIsNone(policy._scan_goal(drone,state['metaevolution']['announced_map']))
        self.assertEqual(policy.completed_sectors, set(policy.builder.positions))
        self.assertEqual(policy.rescue_queues, queues)

        state['time'] = 4
        policy._schedule()
        self.assertIn('rescue', policy.futures)
        executor.complete()
        policy._poll()
        plan = next(c for c in policy.latest_strategy_candidates if c['id']=='cooperative')
        self.assertTrue(plan['eligible'])
        self.assertEqual(plan['scout_tasks'][0]['sector_id'],'sector-1-0')
        self.assertFalse(mail.tasks)

    def test_strategy_roles_wait_for_delivered_motion_and_confirm_revision(self):
        root=Path(__file__).resolve().parents[1]
        catalog=json.loads((root/'unreal/MetaRescue/Content/Scenario/core-scenarios-v1.json').read_bytes())['scenarios']
        coordinator=ScenarioCoordinator({'supported_scenarios':{s['id']:s for s in catalog}})
        policy,_,_=self.create(local_enabled=False);state=public_state()
        state['mission']['status']='active';state['targets']=[]
        rover,scout=state['agents'];spare=deepcopy(rover);spare['id']='spare'
        state['agents'].append(spare)
        active={rover['id']:'rescuer',spare['id']:'rescuer',scout['id']:'scout'}
        plan=state['metaevolution']['plan']
        plan.update(accepted_configuration=configuration([COVERAGE]),desired_role_assignments=active,plan_revision=7)
        policy.global_commit={'request_id':'global-case','participants':{rover['id']},'strategy_id':'urgent'}
        policy.jobs[rover['id']]=Job('return','on-board','route-to-base','handover',0,'follow_route')
        rover['physical']['carrying']=True
        self.assertEqual(coordinator.apply(state,decision(state),policy)['operation'],'keep')
        rover['physical']['active_command_id']='route-to-base:0'
        changed=coordinator.apply(state,decision(state),policy)
        self.assertEqual(changed['selected_configuration']['scenario_ids'],[COORDINATION])
        self.assertEqual(changed['role_assignments'],{rover['id']:'rescuer',scout['id']:'scout'})
        self.assertEqual(policy.jobs[rover['id']].pending,'route-to-base')
        plan['plan_revision']=8;spare.update(role='rescuer',configuration_revision=7)
        coordinator.observe({'observation':state})
        self.assertEqual([r['type'] for r in coordinator.drain()],['global_roles_proposed'])
        spare.update(role=None,configuration_revision=8)
        coordinator.observe({'observation':state})
        self.assertEqual([r['type'] for r in coordinator.drain()],['global_roles_delivered'])

    def test_global_rejects_fictitious_changes_loss_unknown_targets_and_depleted_energy(self):
        policy,_,_=self.create();state=public_state();policy.reset_episode(state['episode_id']);policy.current_observation=state
        aid=state['agents'][0]['id'];policy.rescue_queues={aid:['t/first']}
        base={'id':'balanced','routes':{aid:['t/first']},
              'forecast':{'saved':1,'priority_saved':3,'weighted_completion':100,'energy_Wh':10},
              'continuations':[{'saved':1,'priority_saved':3}]*3}
        better={**deepcopy(base),'id':'urgent','forecast':{**base['forecast'],'weighted_completion':80}}
        policy.latest_strategy_candidates=[base,better];policy.last_rescue_result={'based_agents':{aid:deepcopy(state['agents'][0])}}
        with self.assertRaisesRegex(AIError,'NO_ACTUAL_PLAN_CHANGE'):policy._commit_global('urgent',state)
        better['routes']={aid:['hidden-person']}
        with self.assertRaisesRegex(AIError,'TARGET_STATE_CHANGED'):policy._commit_global('urgent',state)
        better['routes']={aid:['second:no-prefix']};better['forecast']['saved']=0
        with self.assertRaisesRegex(AIError,'EXPECTED_RESCUE_LOSS'):policy._commit_global('urgent',state)
        better['forecast']['saved']=1;better['agent_requirements']={aid:{'energy_wh':20,'usable_wh':40}}
        state['agents'][0]['physical'].update(unlimited_energy=False,remaining_wh=10)
        with self.assertRaisesRegex(AIError,'RESOURCES_CHANGED'):policy._commit_global('urgent',state)

    def test_blocked_carrier_brakes_before_ai_then_executes_only_one_validated_detour(self):
        policy,executor,mail=self.create();state=public_state();state['time']=10
        policy.reset_episode(state['episode_id']);policy.current_observation=state
        rover,drone=state['agents'];aid=rover['id'];did=drone['id']
        rover['position']=[80,10,.47];rover['physical'].update(carrying=True,cargo_target_id='t/first',
            stop_reason='obstacle_on_route',active_command_id='old:0',velocity_m_s=[0,0,0],
            route_blocker={'kind':'box','min':[65,7,0],'max':[70,13,2]})
        state['targets'][0]['evacuation_state']='loaded'
        policy.jobs={aid:Job('return','t/first','old','handover',0,'follow_route'),did:Job('scan')}
        policy.route_intents[aid]={'goal':[20,18.3,.54],'next_phase':'handover'}
        policy.local_started={aid,did};policy.builder=ProblemBuilder(state['metaevolution']['announced_map'])
        policy.scout_queues={did:['sector-0-0']};policy.scan_positions={'sector-0-0':(25,25)};policy.scan_altitudes={did:25}
        first=policy.decide(state)
        self.assertEqual(next(c for c in first['commands'] if c['agent_id']==aid)['action'],'hold')
        self.assertEqual(next(c for c in first['commands'] if c['agent_id']==did)['action'],'follow_route')
        self.assertEqual(len(mail.tasks),0)  # emergency action precedes even submission
        job=policy.jobs[aid]
        policy.observe_response({'status':'running','time':11,'observation':state,'command_results':[
            {'decision_id':job.pending,'command_index':job.pending_index,'agent_id':aid,
             'execution_status':'completed','validation_status':'accepted','delivery_status':'delivered'}]})
        state['time']=11;rover['physical']['stop_reason']='external_hold'
        waiting=policy.decide(state);self.assertEqual(len(mail.tasks),1)
        self.assertFalse(any(c['agent_id']==aid for c in waiting['commands']))
        self.assertEqual(policy.jobs[aid].target,'t/first')
        mail.complete();state['time']=12;resumed=policy.decide(state)
        routes=[c for c in resumed['commands'] if c['agent_id']==aid]
        self.assertEqual(len(routes),1);self.assertEqual(routes[0]['action'],'follow_route')
        self.assertGreater(len(routes[0]['parameters']['waypoints']),2)
        self.assertEqual(policy.jobs[aid].next_phase,'handover');self.assertTrue(rover['physical']['carrying'])
        self.assertEqual(policy.applied['local'],1);self.assertNotIn(aid,policy.recoveries)

    def test_expired_local_choice_is_not_attributed_to_a_later_programmed_recovery(self):
        policy,_,_=self.create();state=public_state();state['time']=40
        policy.reset_episode(state['episode_id']);policy.current_observation=state
        rover=state['agents'][0];aid=rover['id'];rover['position']=[80,10,.47]
        rover['physical'].update(carrying=True,cargo_target_id='t/first',velocity_m_s=[0,0,0])
        policy.jobs[aid]=Job('return','t/first');policy.local_started={a['id'] for a in state['agents']}
        policy.route_intents[aid]={'goal':[20,18.3,.54],'next_phase':'handover'}
        policy.recoveries[aid]={'intent':deepcopy(policy.route_intents[aid]),'stage':'resume','ai_validated':True,
            'valid_until':35,'choice':'DETOUR','request_id':'expired-request','attempt':0}
        result=policy.decide(state)
        self.assertTrue(any(c['agent_id']==aid and c['action']=='follow_route' for c in result['commands']))
        self.assertEqual(policy.applied['local'],0)
        self.assertTrue(any(t['type']=='local_decision_expired' for t in policy.drain_traces()))

    def test_applied_local_hold_and_escalation_keep_their_outcomes_if_route_remains_blocked(self):
        for action, physical_application in (('HOLD', 'retained_hold'), ('ESCALATE', 'coordination_signal')):
            with self.subTest(action=action):
                policy, _, _ = self.create()
                state = public_state()
                policy.reset_episode(state['episode_id'])
                policy.current_observation = state
                carrier = state['agents'][0]
                aid = carrier['id']
                carrier['position'] = [80, 10, .47]
                carrier['physical'].update(carrying=True, cargo_target_id='t/first', stop_reason='external_hold')
                policy.jobs[aid] = Job('return', 't/first')
                policy.observed_blockers[aid] = [{'kind':'box', 'min':[18, 17, 0], 'max':[22, 20, 2]}]
                policy.recoveries[aid] = {'intent':{'goal':[20, 18.3, .54], 'next_phase':'handover'},
                    'stage':'decided', 'choice':action, 'candidate':{'hold_s':3}, 'ai_validated':True,
                    'valid_until':20, 'request_id':'applied-request', 'budget_ticket':'ticket', 'attempt':0}
                account = []
                policy._account = lambda ticket, **values: account.append((ticket, values))
                for now in (10, 12, 13, 21):
                    state['time'] = now
                    self.assertEqual(policy._recover(state), [])
                self.assertEqual(len(account), 1)
                ticket, outcome = account[0]
                self.assertEqual(ticket, 'ticket')
                self.assertTrue(outcome['controller_validated'] and outcome['controller_applied'])
                self.assertEqual(outcome['physical_application'], physical_application)
                self.assertEqual(policy.applied['local'], 1)
                self.assertEqual(policy.jobs[aid].target, 't/first')
                self.assertTrue(carrier['physical']['carrying'])
                traces = [row['type'] for row in policy.drain_traces()]
                self.assertIn('local_safe_fallback_hold', traces)
                self.assertNotIn('local_decision_expired', traces)

    def test_rejected_local_detour_does_not_get_credit_for_later_fallback(self):
        policy, _, _ = self.create()
        state = public_state()
        policy.reset_episode(state['episode_id'])
        policy.current_observation = state
        carrier = state['agents'][0]
        aid = carrier['id']
        carrier['position'] = [80, 10, .47]
        carrier['physical'].update(carrying=True, cargo_target_id='t/first', stop_reason='external_hold')
        policy.jobs[aid] = Job('return', 't/first')
        goal = [20, 18.3, .54]
        original, _, _ = policy._fresh_route(state, carrier, goal)
        policy.observed_blockers[aid] = [{'kind':'box', 'min':[18, 17, 0], 'max':[22, 20, 2]}]
        policy.recoveries[aid] = {'intent':{'goal':goal, 'next_phase':'handover'},
            'stage':'resume', 'choice':'DETOUR', 'candidate':{'route':original}, 'ai_validated':True,
            'valid_until':20, 'request_id':'detour-request', 'budget_ticket':'ticket', 'attempt':0}
        account = []
        policy._account = lambda ticket, **values: account.append((ticket, values))
        state['time'] = 10
        self.assertEqual(policy._recover(state), [])
        policy.observed_blockers.clear()
        state['time'] = 13
        self.assertEqual(policy._recover(state), [(aid, {'agent_id':aid, 'action':'follow_route',
            'parameters':{'waypoints':original}}, 'handover')])
        self.assertEqual(account, [('ticket', {'controller_validated':False,
                                              'rejection_reason':'AI_ROUTE_REVALIDATION_FAILED'})])
        self.assertEqual(policy.applied['local'], 0)
        self.assertNotIn(aid, policy.issued_tickets)

    def test_first_local_advisories_survive_mailbox_pressure_while_agents_move(self):
        policy,executor,mail=self.create();policy.advisors.max_local=1;state=public_state()
        for i in range(2):
            drone=deepcopy(state['agents'][1]);drone['id']='extra-'+str(i);drone['position'][0]+=10*(i+1)
            state['agents'].append(drone)
        policy.decide(state);executor.complete();state['time']=1;result=policy.decide(state)
        self.assertEqual(len(result['commands']),4)
        self.assertTrue(policy.first_advisory_queue)
        for tick in range(2,8):
            mail.complete();state['time']=tick
            # Still executing the same long routes: no completion or new dispatch.
            following=policy.decide(state);self.assertFalse(following['commands'])
        self.assertFalse(policy.first_advisory_queue)
        local_ids={args[0].data['agent_id'] for _,_,args in mail.tasks if args[0].role=='local'}
        self.assertEqual(local_ids,{a['id'] for a in state['agents']})


if __name__=='__main__':unittest.main()
