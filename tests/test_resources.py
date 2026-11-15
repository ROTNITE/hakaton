from copy import deepcopy
import unittest

from contracts.protocol import ProtocolError
from controller.baselines import FixedWorkflow,Job
from controller.policy import EvolutionPolicy
from controller.problem_builder import usable_energy
from environment.config import Settings
from environment.layout import generate
from test_evolution_policy import DeferredExecutor
from test_problem_builder import public_state


def contest_state():
    state=public_state()
    state['infrastructure']=[{'id':'power','kind':'charging_station','status':'active','position':[20,13,0],
        'charger':{'kind':'ground','docking_distance_m':4.,'remaining_wh':100}}]
    rover=state['agents'][0]
    rover['position']=[20,13,.54]
    rover['physical'].update(at_dock=False,unlimited_energy=False,remaining_wh=1,capacity_wh=6,reserve_wh=1.5)
    rover['available_actions'].append({'action':'charge'})
    return state


class ResourceTests(unittest.TestCase):
    def test_contest_declares_compatible_pad_and_validates_settings(self):
        with self.assertRaises(ProtocolError):Settings.parse({'ground_battery_wh':True})
        with self.assertRaises(ProtocolError):Settings.parse({'energy_reserve_fraction':.85})
        world=generate(Settings.parse({'resource_profile':'contest','scouts':2,'rescuers':2,'people':3}))
        stations=[n for n in world['infrastructure'] if 'charger' in n]
        self.assertEqual(len(stations),3)
        for agent in (a for a in world['spawns'] if a['kind']=='aerial'):
            pad=next(n for n in stations if n['charger'].get('agent_id')==agent['id'])
            self.assertEqual(pad['position'],agent['position'])

    def test_charge_preserves_job_and_does_not_reserve_shared_port_twice(self):
        state=contest_state();policy=FixedWorkflow();policy.reset_episode(state['episode_id'])
        rover=state['agents'][0];aid=rover['id'];job=policy.jobs[aid]=Job('approach','t/first')
        second=deepcopy(rover);second.update(id='second_rover',position=[23.5,13,.54]);state['agents'].append(second)
        request=policy.decide(state)
        self.assertIn({'agent_id':aid,'action':'charge','parameters':{'station_id':'power'}},request['commands'])
        self.assertFalse(any(c['agent_id']==second['id'] for c in request['commands']))
        self.assertEqual(job.charge_station,'power')
        policy.observe_response({'status':'running','command_results':[{'decision_id':job.pending,'agent_id':aid,
            'command_index':job.pending_index,'execution_status':'completed'}]})
        self.assertIsNone(job.charge_station)
        self.assertEqual((job.phase,job.target),('approach','t/first'))

    def test_recharge_route_completion_is_not_scout_sector_completion(self):
        state=public_state();policy=EvolutionPolicy(executor=DeferredExecutor());policy.decide(state)
        aid=state['agents'][1]['id'];policy.scout_active[aid]='sector-0-0'
        job=policy.jobs[aid]=Job('scan',pending='trip',action='follow_route',charge_station='pad')
        def completed(decision):
            policy.observe_response({'status':'running','time':1,'command_results':[{'decision_id':decision,'agent_id':aid,
                'command_index':0,'execution_status':'completed'}]})
        completed('trip')
        self.assertNotIn(aid,policy.arrivals)
        self.assertEqual(policy.scout_active[aid],'sector-0-0')
        job.pending='charge';job.action='charge';completed('charge')
        self.assertIsNone(job.charge_station)
        self.assertEqual(policy.replan_requested,{'scout','rescue'})

    def test_planner_uses_declared_reserve_and_offline_cargo_stays_reserved(self):
        state=contest_state();rover=state['agents'][0];policy=FixedWorkflow();policy.reset_episode(state['episode_id'])
        rover['physical'].update(remaining_wh=4,reserve_wh=2.5)
        self.assertEqual(usable_energy(rover),1.5)
        job=policy.jobs[rover['id']]=Job('return','t/first');rover['status']='offline'
        policy.decide(state)
        self.assertEqual(job.target,'t/first')
        rover['status']='failed';rover['physical'].update(carrying=False,remaining_wh=0)
        policy.decide(state)
        self.assertIsNone(job.target)

    def test_lost_ack_waits_for_fresh_execution_and_keeps_cargo_assignment(self):
        state=public_state();policy=FixedWorkflow();policy.decide(state)
        rover=state['agents'][0];aid=rover['id'];rover.update(position=[20,18.3,.54],status='busy')
        rover['physical'].update(carrying=True,cargo_target_id='t/first',route_finished=True,active_command_id='return:0')
        job=policy.jobs[aid]=Job('return','t/first','return','handover',0,'follow_route')
        policy.observe_response({'status':'running','command_results':[{'decision_id':'return','agent_id':aid,
            'command_index':0,'execution_status':'unknown','validation_status':'accepted','delivery_status':'delivered','updated_at':10}]})
        state['time']=11;rover['freshness']={'position':{'observed_at':9}}
        old=policy.decide(state)
        self.assertFalse(any(c['agent_id']==aid for c in old['commands']))
        self.assertEqual(job.pending,'return')
        rover['freshness']['position']['observed_at']=11
        fresh=policy.decide(state)
        self.assertEqual(next(c for c in fresh['commands'] if c['agent_id']==aid)['action'],'handover')
        self.assertEqual(fresh['metaevolution']['execution_reconciliation'][0]['outcome'],'observed_complete')
        self.assertEqual(job.target,'t/first')
        policy.observe_response({'status':'running','command_results':[{'decision_id':job.pending,'agent_id':aid,
            'command_index':job.pending_index,'execution_status':'completed'}]})
        self.assertIsNone(job.target);self.assertEqual(job.phase,'park')


if __name__=='__main__':unittest.main()
