from copy import deepcopy
import unittest

from contracts.protocol import ProtocolError
from controller.baselines import FixedWorkflow,Job
from controller.navigation import NavigationMap,observed_surfaces
from environment.config import Settings
from environment.disturbances import FORMAT,validate_tape
from environment.layout import generate,public_map
from test_problem_builder import public_state


class DisturbanceTests(unittest.TestCase):
    def test_private_restriction_and_effect_timing(self):
        world=generate(Settings.parse({'scouts':1,'rescuers':1,'people':3}))
        tape={'format':FORMAT,'events':[{'id':'road','type':'restricted_zone_appeared','time':2.125,'until':5.5,
            'source':'operator','targets':[],'parameters':{'bounds':{'min':[90,5,0],'max':[95,15,2]},'allowed_kinds':['aerial']}}]}
        self.assertEqual(validate_tape(tape,world),tape)
        world['disturbances']=tape
        self.assertNotIn('disturbances',public_map(world))
        for key,value in (('until',2.),('time',False),('source','')):
            bad=deepcopy(tape);bad['events'][0][key]=value
            with self.assertRaises(ProtocolError):validate_tape(bad,world)
        duplicate=deepcopy(tape);duplicate['events'].extend(tape['events'])
        with self.assertRaises(ProtocolError):validate_tape(duplicate,world)

    def test_delivered_restriction_is_specific_to_agent_kind(self):
        state=public_state()
        state['zones']=[{'type':'restricted','geometry':{'type':'box','min':[90,5,0],'max':[95,15,30]},
                         'access':{'allowed_kinds':['ground']}}]
        nav=NavigationMap(state['metaevolution']['announced_map'],surfaces=observed_surfaces(state))
        self.assertTrue(nav.clear((80,10,.47),(100,10,.47),1.45,1.1))
        self.assertFalse(nav.clear((80,10,20),(100,10,20),1.65,.4,aerial=True))
        self.assertTrue(nav.clear((92,10,20),(100,10,20),1.65,.4,aerial=True))

    def test_directive_waits_for_pickup_and_retains_assignment(self):
        state=public_state();policy=FixedWorkflow();policy.decide(state)
        aid=state['agents'][0]['id'];job=policy.jobs[aid]=Job('pickup','t/first','loading','return',0,'pickup')
        state['mission']['directives']=[{'id':'hold-1','agent_id':aid,'action':'hold','issued_at':0,'expires_at':10}]
        directive=policy.decide(state)
        self.assertFalse(any(c['agent_id']==aid for c in directive['commands']))
        self.assertEqual(directive['metaevolution']['directive_checks'][0]['outcome'],'waiting_for_safe_service_boundary')
        policy.observe_response({'status':'running','command_results':[{'decision_id':'loading','agent_id':aid,
            'command_index':0,'execution_status':'completed'}]})
        hold=policy.decide(state)
        self.assertEqual(next(c for c in hold['commands'] if c['agent_id']==aid)['action'],'hold')
        self.assertEqual((job.phase,job.target),('return','t/first'))


if __name__=='__main__':unittest.main()
