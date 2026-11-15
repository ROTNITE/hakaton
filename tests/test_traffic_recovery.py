from copy import deepcopy
import math
import unittest

from controller.baselines import FixedWorkflow,Job
from controller.navigation import RouteFailure
import test_ai_policy as ai_tests
from test_problem_builder import public_state


def blocked_state():
    state=public_state();agent=state['agents'][0];aid=agent['id']
    agent['position']=[80,10,.47]
    agent['physical'].update(carrying=True,cargo_target_id='t/first',stop_reason='yield_to_vehicle',
        stop_obstacle='parked-neighbour',active_command_id='old-route:0',route_finished=False,
        velocity_m_s=[0,0,0],intended_velocity_m_s=[-3,0,0])
    other=deepcopy(agent);other.update(id='parked-neighbour',position=[60,10,.47])
    other['physical'].update(carrying=False,cargo_target_id=None,stop_reason='',route_finished=True,
        active_command_id='finished',intended_velocity_m_s=[0,0,0])
    state['agents'].append(other)
    state['targets']=[{**state['targets'][0],'evacuation_state':'loaded'}]
    return state,agent,other,aid


def frame(state,time):
    state['time']=time
    for agent in state['agents']:
        agent['freshness']={'position':{'observed_at':time,'received_at':time,'source_id':agent['id']}}


class TrafficRecoveryTests(unittest.TestCase):
    def test_shared_apron_releases_one_departure_at_a_time(self):
        state=public_state();first=state['agents'][0]
        nearest=deepcopy(first);nearest['id']='nearest-exit';nearest['position'][0]=35.5
        nearest['physical']['dock_exit_waypoints'][0][0]=35.5
        state['agents'].append(nearest)
        policy=FixedWorkflow()
        request=policy.decide(state)
        ground=[(i,c) for i,c in enumerate(request['commands']) if c['agent_id'] in (first['id'],nearest['id'])]
        self.assertEqual([c['agent_id'] for _,c in ground],[nearest['id']])
        self.assertEqual(policy.jobs[first['id']].phase,'choose')
        index,_=ground[0]
        frame(state,1)
        waiting=policy.decide(state)
        self.assertFalse(any(c['agent_id']==first['id'] for c in waiting['commands']))
        policy.observe_response({'status':'running','command_results':[
            {'agent_id':nearest['id'],'decision_id':request['decision_id'],'command_index':index,
             'execution_status':'completed'}]})
        nearest['position']=[63,10,.728];nearest['physical']['at_dock']=False
        frame(state,2)
        released=policy.decide(state)
        command=next(c for c in released['commands'] if c['agent_id']==first['id'])
        self.assertEqual(command['parameters']['waypoints'],first['physical']['dock_exit_waypoints'])
        self.assertTrue(policy.jobs[first['id']].using_dock_exit)

    def test_apron_projection_clears_the_parked_vehicles_braking_envelope(self):
        state, carrier, parked, aid = blocked_state()
        carrier['position'] = [45.9841, 23.9734, .518]
        parked['position'] = [42.5226, 21.8905, .518]
        state['agents'][1]['position'] = [54., 34., .31]
        announced = state['metaevolution']['announced_map']
        announced['road_graph'] = {
            'nodes': [{'id': str(i), 'position': [x, 10., 0.]} for i, x in enumerate((10., 41.654, 64.))],
            'edges': [{'from': str(i), 'to': str(i + 1), 'width_m': 8.5} for i in range(2)],
        }
        goal = [20., 18.3, .54]
        policy, _, _ = ai_tests.AIPolicyTests().create()
        try:
            policy.jobs[aid] = Job('return', 't/first')
            local, _, _ = policy._fresh_route(state, carrier, goal)
            fixed = FixedWorkflow()._route(announced, carrier, state['agents'], goal)
        finally:
            policy.close()
        self.assertEqual(local, fixed)
        self.assertEqual(local[-1], goal)
        self.assertGreater(local[0][0], carrier['position'][0])
        start, center = carrier['position'], parked['position']
        for a, b in zip([start, *local], local):
            dx, dy = b[0] - a[0], b[1] - a[1]
            fraction = ((center[0] - a[0]) * dx + (center[1] - a[1]) * dy) / (dx * dx + dy * dy)
            t = min(1., max(0., fraction))
            self.assertGreaterEqual(math.dist((a[0] + t * dx, a[1] + t * dy), center[:2]), 3.55)

    def test_loaded_detour_reserve_ends_at_the_handover_position_outside_the_container(self):
        state,agent,_,aid=blocked_state()
        state['metaevolution']['announced_map']['fixed_obstacles']=[{
            'id':'medical-container','bounds':{'kind':'box','min':[16.92,20.68,.08],
                                               'max':[23.08,23.33,3.34]}}]
        policy,_,_=ai_tests.AIPolicyTests().create()
        policy.reset_episode('e');policy.current_observation=state;policy.jobs[aid]=Job('return','t/first')
        try:
            points,distance,energy=policy._fresh_route(state,agent,[20,18.3,.54])
            self.assertEqual(points[-1],[20.,18.3,.54])
            self.assertAlmostEqual(energy,distance*.118+2)
            self.assertTrue(agent['physical']['carrying'])
        finally:policy.close()

    def test_local_parking_recovery_keeps_the_dock_axis_and_rejects_known_blockage(self):
        state=public_state();agent=state['agents'][0];aid=agent['id'];home=agent['position'][:]
        state['agents'][1]['position']=[43.5,35,25]
        agent['position']=[20,18.3,.54];agent['physical']['dock_position_m']=home
        policy,_,_=ai_tests.AIPolicyTests().create();policy.reset_episode('e');policy.current_observation=state
        policy.jobs[aid]=Job('park')
        points,_,_=policy._fresh_route(state,agent,home)
        self.assertEqual([p[:2] for p in points[-3:]],[[32,14],[32,18],[32,22]])
        policy.observed_blockers[aid]=[{'kind':'box','min':[31,17,0],'max':[33,19,2]}]
        with self.assertRaisesRegex(RouteFailure,'dock approach'):policy._fresh_route(state,agent,home)
        policy.close()

    def test_only_continuous_fresh_stationary_observations_enable_a_bypass(self):
        state,agent,other,aid=blocked_state();policy=FixedWorkflow()
        for time in range(6):
            frame(state,time);self.assertFalse(policy._stationary_yield(state,agent))
        frame(state,6);self.assertTrue(policy._stationary_yield(state,agent))
        other['physical']['intended_velocity_m_s']=[1,0,0]
        frame(state,7);self.assertFalse(policy._stationary_yield(state,agent))
        self.assertNotIn(aid,policy.static_yields)
        other['physical']['intended_velocity_m_s']=[0,0,0]
        frame(state,8);self.assertFalse(policy._stationary_yield(state,agent))
        frame(state,15);self.assertFalse(policy._stationary_yield(state,agent))
        other['freshness']['position']['observed_at']=10
        self.assertFalse(policy._stationary_yield(state,agent))
        self.assertNotIn(aid,policy.static_yields)

    def test_reciprocal_ground_yield_backs_off_one_vehicle_and_keeps_cargo_priority(self):
        state, carrier, peer, aid = blocked_state()
        peer['physical'].update(stop_reason='yield_to_vehicle', stop_obstacle=aid, intended_velocity_m_s=[3, 0, 0])
        policy = FixedWorkflow()
        for time in range(6):
            frame(state, time)
            self.assertFalse(policy._stationary_yield(state, carrier))
            self.assertFalse(policy._stationary_yield(state, peer))
        frame(state, 6)
        self.assertFalse(policy._stationary_yield(state, carrier))
        self.assertTrue(policy._stationary_yield(state, peer))
        self.assertIn((carrier['position'][:2], 1.45), policy._parked_ground_peers(peer, state['agents']))
        peer['physical']['velocity_m_s'] = [.3, 0, 0]
        frame(state, 7)
        self.assertFalse(policy._stationary_yield(state, peer))

    def test_yield_wait_requires_continuous_measurements_from_both_vehicles(self):
        state, carrier, peer, _ = blocked_state()
        policy = FixedWorkflow()
        # Every delivered position is at most two seconds old. The peer's
        # measurement gap is still three seconds, so the wait must restart.
        for now, peer_observed in enumerate((0, 1, 2, 2, 2, 5, 6, 7, 8, 9, 10, 11)):
            frame(state, now)
            peer['freshness']['position']['observed_at'] = peer_observed
            self.assertEqual(policy._stationary_yield(state, carrier), now == 11, f'time {now}')

    def test_replacement_route_requires_its_own_continuous_yield_wait(self):
        state,carrier,peer,_=blocked_state();policy=FixedWorkflow()
        for now in range(7):
            frame(state,now);self.assertEqual(policy._stationary_yield(state,carrier),now==6)
        # The previous deadlock timer must not cancel a newly delivered bypass
        # after one second, before the chassis has had time to turn and move.
        carrier['physical']['active_command_id']='replacement-route:0'
        for now in range(7,14):
            frame(state,now);self.assertEqual(policy._stationary_yield(state,carrier),now==13,f'time {now}')

    def test_mutual_yield_holds_loaded_peer_until_empty_carrier_has_cleared(self):
        state,carrier,peer,aid=blocked_state();policy=FixedWorkflow();policy.reset_episode('e')
        carrier['position']=[80,10,.47];peer['position']=[83.95,10,.47]
        peer['physical'].update(stop_reason='yield_to_vehicle',stop_obstacle=aid,
            intended_velocity_m_s=[3,0,0],active_command_id='peer-route:0')
        state['targets'].append(deepcopy(public_state()['targets'][1]))
        policy.jobs[aid]=Job('return','t/first','old-route','handover',0,'follow_route')
        policy.jobs[peer['id']]=Job('approach','second:no-prefix','peer-route','pickup',0,'follow_route')
        for now in range(7):frame(state,now);result=policy.decide(state)
        holds=[c for c in result['commands'] if c['action']=='hold']
        self.assertEqual({c['agent_id'] for c in holds},{aid,peer['id']})
        results=[]
        for i,c in enumerate(result['commands']):
            if c['action']=='hold':results.append({'decision_id':result['decision_id'],'agent_id':c['agent_id'],
                'command_index':i,'validation_status':'accepted','delivery_status':'delivered','execution_status':'completed'})
        policy.observe_response({'status':'running','command_results':results})
        for a in (carrier,peer):a['physical'].update(stop_reason='external_hold',intended_velocity_m_s=[0,0,0])
        frame(state,7);resumed=policy.decide(state)
        self.assertTrue(any(c['agent_id']==peer['id'] and c['action']=='follow_route' for c in resumed['commands']))
        self.assertFalse(any(c['agent_id']==aid for c in resumed['commands']))
        self.assertEqual(policy.jobs[aid].target,'t/first')
        self.assertEqual(policy.jobs[aid].phase,'return')
        # Stale far-away telemetry cannot release the held carrier.
        peer['position'][0]+=10;frame(state,10);peer['freshness']['position']['observed_at']=7
        stale=policy.decide(state);self.assertFalse(any(c['agent_id']==aid for c in stale['commands']))
        frame(state,11);released=policy.decide(state)
        self.assertTrue(any(c['agent_id']==aid and c['action']=='follow_route' for c in released['commands']))
        self.assertTrue(carrier['physical']['carrying'])
        policy.traffic_holds[aid]={'clearing_agent':peer['id'],'start':list(peer['position'])}
        peer['status']='failed';frame(state,12)
        self.assertEqual(policy._coordinate_ground_yields(state,{} )[0]['reason'],'clearing_agent_failed')
        policy.traffic_holds[aid]={'clearing_agent':peer['id'],'start':list(peer['position'])}
        policy.reset_episode('another-episode');self.assertFalse(policy.traffic_holds)

    def test_fixed_workflow_brakes_and_replans_without_losing_the_loaded_job(self):
        state,agent,other,aid=blocked_state();policy=FixedWorkflow();policy.reset_episode('e')
        policy.jobs[aid]=Job('return','t/first','old-route','handover',0,'follow_route')
        for time in range(7):
            frame(state,time);result=policy.decide(state)
            own=[c for c in result['commands'] if c['agent_id']==aid]
            self.assertEqual([c['action'] for c in own],['hold'] if time==6 else [])
        index=next(i for i,c in enumerate(result['commands']) if c['agent_id']==aid)
        policy.observe_response({'status':'running','command_results':[{
            'decision_id':result['decision_id'],'agent_id':aid,'command_index':index,
            'validation_status':'accepted','delivery_status':'delivered','execution_status':'completed'}]})
        frame(state,7);agent['physical'].update(stop_reason='external_hold',active_command_id=result['decision_id']+':'+str(index))
        resumed=policy.decide(state);command=next(c for c in resumed['commands'] if c['agent_id']==aid)
        self.assertEqual(command['action'],'follow_route')
        self.assertEqual(policy.jobs[aid].next_phase,'handover')
        self.assertEqual(policy.jobs[aid].target,'t/first')
        self.assertTrue(agent['physical']['carrying'])

    def test_local_uses_a_validated_detour_after_the_same_wait(self):
        state,agent,other,aid=blocked_state();policy,_,_=ai_tests.AIPolicyTests().create()
        policy.reset_episode('e');policy.current_observation=state
        policy.jobs[aid]=Job('return','t/first','old-route','handover',0,'follow_route')
        policy.route_intents[aid]={'goal':[20,18.3,.54],'next_phase':'handover'}
        for time in range(7):
            frame(state,time);commands=policy._recover(state)
            self.assertEqual([c[1]['action'] for c in commands],['hold'] if time==6 else [])
        recovery=policy.recoveries[aid]
        self.assertEqual(recovery['reason'],'stationary_vehicle_on_route')
        choices=policy._options(state,agent,recovery)
        self.assertEqual(choices[0]['action'],'DETOUR')
        self.assertTrue(choices[0]['route'])
        self.assertTrue(agent['physical']['carrying'])
        policy.close()


if __name__=='__main__':unittest.main()
