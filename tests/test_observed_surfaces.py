from copy import deepcopy
import math
import unittest

from controller.baselines import FixedWorkflow,Job
from controller.navigation import NavigationMap,observed_surfaces
from controller.policy import EvolutionPolicy
from test_evolution_policy import DeferredExecutor,accepted
from test_problem_builder import public_state


def zone(x,y,*,blocked=False,cost=1.,visibility=1.,received=1.):
    return {'id':f'cell-{x}-{y}','received_at':received,
            'geometry':{'type':'box','min':[x,y,-.15],'max':[x+5,y+5,1.2]},
            'surface':{'active':True,'ground_blocked':blocked,
                       'surface_multiplier':cost,'visibility':visibility}}


class ObservedSurfaceTests(unittest.TestCase):
    def test_public_road_block_forces_detour_but_does_not_block_flight(self):
        state=public_state()
        state.update(time=2,zones=[zone(90,5,blocked=True),zone(90,10,blocked=True)])
        announced=state['metaevolution']['announced_map']
        start,goal=(76.13,10,.47),(134.21,10,.47)
        nav=NavigationMap(announced,surfaces=observed_surfaces(state))
        self.assertFalse(nav.clear(start,goal,1.45,1.1))
        self.assertTrue(nav.clear(start,goal,1.65,.4,aerial=True))
        detour=nav.road_route(start,goal)
        self.assertEqual(detour.points[0],start)
        self.assertEqual(detour.points[-1],goal)
        self.assertGreater(detour.distance_m,math.dist(start,goal)+50)
        self.assertTrue(all(nav.clear(a,b,1.45,1.1) for a,b in zip(detour.points,detour.points[1:])))
        # Absence from the next delivered snapshot removes the resolved zone.
        state['zones']=[]
        clear=NavigationMap(announced,surfaces=observed_surfaces(state)).road_route(start,goal)
        self.assertLess(clear.distance_m,detour.distance_m)

    def test_dynamic_cost_combines_with_declared_surface_and_ignores_future(self):
        state=public_state()
        current=zone(90,10,cost=2.25,visibility=.52,received=1)
        state.update(time=2,zones=[current,zone(95,10,cost=9,received=3)])
        announced=state['metaevolution']['announced_map']
        announced['surfaces']=[{'bounds':{'kind':'box','min':[90,10,0],'max':[95,15,.2]},'cost':1.4}]
        current['expires_at']=1.5 # expiry is not a delivered observation of clearance
        nav=NavigationMap(announced,surfaces=observed_surfaces(state))
        self.assertAlmostEqual(nav.cost((89,12,.47),(96,12,.47)),2+5*1.4*2.25)
        self.assertLess(nav.sector_visibility((92.5,12.5)),1)
        reversed_zones=deepcopy(state)
        reversed_zones['zones'].reverse()
        reversed_zones['zones'][1]['id']='renamed'
        self.assertEqual(observed_surfaces(state),observed_surfaces(reversed_zones))

    def test_surface_update_invalidates_workers_and_avoids_future_truth(self):
        executor=DeferredExecutor()
        policy=EvolutionPolicy(executor=executor,population_scout=8,generations_scout=2,
                               population_rescue=8,generations_rescue=2)
        initial=public_state()
        first=policy.decide(initial)
        current=accepted(initial,first,2)
        current['zones']=[zone(90,10,blocked=True)]
        current['event_model']={'events':[zone(50,5,blocked=True)]}
        executor.complete()
        policy.decide(current)
        self.assertEqual(len(policy.planning_surfaces),1)
        self.assertEqual(len(executor.tasks),4)
        self.assertEqual({t['planner'] for t in policy.drain_traces() if t.get('reason')=='new_replan_request'},
                         {'scout','rescue'})

    def test_automatic_braking_keeps_the_loaded_job(self):
        policy=FixedWorkflow()
        state=public_state()
        first=policy.decide(state)
        current=accepted(state,first,2)
        rover=current['agents'][0]
        job=policy.jobs[rover['id']]=Job('return','t/first','old-route','handover',0,'follow_route')
        rover['physical'].update(carrying=True,cargo_target_id='t/first',stop_reason='hazard_on_route',
                                 active_command_id='old-route:0')
        request=policy.decide(current)
        self.assertIn({'agent_id':rover['id'],'action':'hold','parameters':{}},request['commands'])
        self.assertEqual(job.target,'t/first')
        self.assertEqual(job.phase,'return')
        self.assertIsNone(job.next_phase)


if __name__=='__main__':unittest.main()
