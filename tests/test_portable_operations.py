"""Meaningful seven-operation behavior with mandatory public observations only."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from contracts.protocol import validate_decision
from controller.portable import PortablePolicy

ROOT=Path(__file__).resolve().parents[1]


class PortableOperationsTests(unittest.TestCase):
    def setUp(self):
        contract=json.loads((ROOT/'contracts/examples/interaction-v1.json').read_bytes())
        self.cap=deepcopy(contract['capabilities']);self.cap['extensions']=[]
        self.cap['supported_operations']=['keep','select','switch','modify','compose','synthesize','safe_stop']
        cat=self.cap['supported_scenarios']
        cat['coverage_search']['compatible_with']=['priority_response']
        cat['priority_response']['compatible_with']=['coverage_search']
        keep=('protocol_version','episode_id','request_id','time','mission','agents','infrastructure',
              'targets','zones','network','events','constraints','metrics','observation_quality')
        original=contract['reset_response']['observation']
        self.o={k:deepcopy(original[k]) for k in keep}
        self.o.update(episode_id='episode/λ',request_id='o/0',time=0,targets=[],events=[],metrics={},constraints=[])
        self.o['mission'].update(objectives=[],directives=[],constraints=[],status='active',termination={'horizon':120})
        self.o['network']['partition_count']=0
        self.o['observation_quality'].update(stale_data_ratio=0,unknown_state_ratio=0,maximum_delay=0,contradiction_count=0)
        def agent(aid,kind,pos,actions,caps):
            return {'id':aid,'kind':kind,'position':pos,'status':'active','role':None,'scenario_ids':[],
                    'capabilities':caps,'available_actions':[{'action':x} for x in actions],
                    'resources':{'energy':{'id':'energy','minimum':.1,'maximum':1.,'value':.9,'unit':'normalized'}},
                    'communication':{'reachable':True},'constraints':[]}
        self.scout=agent('θ/7','aerial',[2.,2.,8.],['move','observe','inspect','hold'],['move','sense','inspect'])
        self.carrier=agent('p#49','ground',[1.,1.,0.],['move','deliver','hold'],['move','deliver'])
        self.carrier['resources']['kit/47']={'id':'kit/47','minimum':0,'maximum':1,'value':1,'unit':'normalized'}
        self.relay=agent('r:β','infrastructure',[0.,0.,0.],[],['relay'])
        self.o['agents']=[self.scout,self.carrier,self.relay]
        self.o['zones']=[{'id':kind+'/z','type':kind,'geometry':{'type':'box','min':lo,'max':hi},
                         'risk':0,'access':{},'cost':{},'communication':{},'constraints':[]}
                        for kind,lo,hi in [('air',[0,0,1],[50,50,15]),('land',[0,0,0],[50,50,0])]]
        self.policy=PortablePolicy(self.cap,'nsga2_nsga2')

    def target(self,identifier='t/仮',priority=.5):
        position=[*self.scout['position'][:2],0.]
        self.o['targets']=[{'id':identifier,'status':'confirmed','kind':'person','position':position,'confidence':.8}]
        self.o['mission']['objectives']=[{'id':'goal/δ','type':'deliver','status':'active','priority':priority,
            'target_id':identifier,'required_capabilities':['deliver'],
            'success_conditions':{'resource_id':'kit/47','amount_at_least':1}}]

    def decide(self):
        before=deepcopy(self.o);result=self.policy.decide(self.o)
        self.assertEqual(before,self.o,'Controller mutated the delivered observation')
        self.assertNotIn('metaevolution',result)
        validate_decision(result,self.o,self.cap)
        self.assertTrue(result['explanation']['observation_refs'])
        return result

    def accept(self,d,*,completed=True,extra_results=()):
        byid={a['id']:a for a in self.o['agents']}
        for aid,role in d['role_assignments'].items():byid[aid]['role']=role
        results=[]
        for i,c in enumerate(d['commands']):
            if completed and c['action']=='move':byid[c['agent_id']]['position']=list(c['parameters']['target'])
            results.append({'decision_id':d['decision_id'],'command_index':i,'agent_id':c['agent_id'],
                'action':c['action'],'validation_status':'accepted','delivery_status':'delivered',
                'execution_status':'completed' if completed else 'in_progress','reason_code':None,'updated_at':self.o['time']+1})
        self.o['time']+=1;self.o['request_id']='o/'+str(self.o['time'])
        self.policy.observe_response({'observation':self.o,'time':self.o['time'],'command_results':results+list(extra_results)})
        return results

    def test_compose_modify_switch_preserve_independent_work(self):
        first=self.decide();self.assertEqual(first['operation'],'select');self.accept(first)
        self.target();composed=self.decide()
        self.assertEqual(composed['operation'],'compose')
        self.assertEqual(composed['selected_configuration']['scenario_ids'],['coverage_search','priority_response'])
        self.assertEqual(set(c['agent_id'] for c in composed['commands']),{self.scout['id'],self.carrier['id']})
        self.accept(composed)
        self.target('t/new')
        modified=self.decide();self.assertEqual(modified['operation'],'modify')
        self.assertEqual(modified['selected_configuration']['parameters']['by_scenario']['priority_response']['target_id'],'t/new')
        self.accept(modified)
        self.o['targets']=[];self.o['mission']['objectives']=[]
        switched=self.decide();self.assertEqual(switched['operation'],'switch')
        self.assertEqual(switched['selected_configuration']['scenario_ids'],['coverage_search'])

    def test_uncertain_priority_synthesis_executes_correlated_phases(self):
        initial=self.decide();self.accept(initial)
        self.target(priority=1.)
        self.o['observation_quality']['stale_data_ratio']=.8
        created=self.decide();self.assertEqual(created['operation'],'synthesize')
        declaration=created['selected_configuration']['synthesized_scenario']
        self.assertIsInstance(declaration,dict)
        self.assertNotIn(declaration['id'],self.cap['supported_scenarios'])
        self.assertTrue(declaration['execution_rules']['states'])
        self.accept(created)
        inspection=self.decide();self.assertEqual(inspection['operation'],'keep')
        self.assertEqual([c['action'] for c in inspection['commands']],['inspect'])
        pending=self.accept(inspection,completed=False)
        waiting=self.decide();self.assertEqual(waiting['commands'],[])
        wrong={**pending[0],'decision_id':'unrelated','execution_status':'completed'}
        self.accept(waiting,extra_results=[wrong])
        still_waiting=self.decide();self.assertEqual(still_waiting['commands'],[])
        self.accept(still_waiting,extra_results=[{**pending[0],'execution_status':'completed'}])
        approach=self.decide();self.assertEqual([c['action'] for c in approach['commands']],['move'])
        self.accept(approach)
        delivery=self.decide();self.assertEqual([c['action'] for c in delivery['commands']],['deliver'])
        self.assertEqual(delivery['commands'][0]['parameters'],{'target_id':'t/仮','resource_id':'kit/47','amount':1})
        self.accept(delivery)
        self.o['mission']['objectives'][0]['status']='completed'
        finished=self.decide();self.assertEqual(finished['operation'],'switch')
        self.assertEqual(finished['selected_configuration']['scenario_ids'],['coverage_search'])

    def test_exhausted_available_actors_request_command_free_safe_stop(self):
        for a in self.o['agents']:a['resources']['energy']['value']=a['resources']['energy']['minimum']
        d=self.decide();self.assertEqual(d['operation'],'safe_stop');self.assertEqual(d['commands'],[])

    def test_accepted_safe_stop_keeps_waiting_even_if_resources_recover(self):
        for a in self.o['agents']:a['resources']['energy']['value']=a['resources']['energy']['minimum']
        stopped=self.decide();self.accept(stopped)
        for a in self.o['agents']:a['resources']['energy']['value']=.9
        waiting=self.decide()
        self.assertEqual((waiting['operation'],waiting['commands']),('keep',[]))
        self.assertEqual(waiting['selected_configuration'],stopped['selected_configuration'])

    def test_busy_or_charging_actors_keep_accepted_plan_while_ack_is_pending(self):
        initial=self.decide();self.accept(initial,completed=False);self.target()
        for status in ('busy','charging'):
            with self.subTest(status=status):
                self.scout['status']=self.carrier['status']=status
                waiting=self.decide()
                self.assertEqual((waiting['operation'],waiting['commands']),('keep',[]))
                self.assertEqual(waiting['selected_configuration'],initial['selected_configuration'])
                self.assertEqual(waiting['role_assignments'],initial['role_assignments'])

    def test_unknown_compatibility_does_not_authorize_composition(self):
        for declaration in self.cap['supported_scenarios'].values():declaration.pop('compatible_with',None)
        initial=self.decide();self.accept(initial);self.target()
        self.assertEqual(self.decide()['operation'],'switch')

    def test_public_termination_does_not_require_author_horizon(self):
        self.target(priority=1.);self.o['observation_quality']['stale_data_ratio']=.8
        for termination in ({'time_limit':120},{}):
            with self.subTest(termination=termination):
                self.policy=PortablePolicy(self.cap,'nsga2_nsga2')
                self.o['mission']['termination']=termination
                created=self.decide();self.assertEqual(created['operation'],'synthesize')
                self.assertEqual(created['selected_configuration']['synthesized_scenario']['execution_rules']['deadline_seconds'],60)

    def test_multicapability_scout_keeps_scout_role_during_composition(self):
        self.scout['capabilities'].append('relay')
        self.target()
        composed=self.decide();self.assertEqual(composed['operation'],'compose')
        self.assertEqual(composed['role_assignments'],{
            self.scout['id']:'scout',self.carrier['id']:'executor',self.relay['id']:'relay'})

    def start_program(self):
        self.target(priority=1.)
        self.o['observation_quality']['stale_data_ratio']=.8
        created=self.decide();self.assertEqual(created['operation'],'synthesize');self.accept(created)

    def test_roles_must_be_delivered_without_optional_configuration_revision(self):
        self.start_program()
        self.scout['role']=None
        waiting=self.decide();self.assertEqual(waiting['commands'],[]);self.accept(waiting)
        self.scout['role']='verifier'
        self.assertEqual([c['action'] for c in self.decide()['commands']],['inspect'])

    def test_active_program_uses_declared_actions_of_busy_role_owners(self):
        self.start_program()
        self.scout['status']=self.carrier['status']='busy'
        inspection=self.decide()
        self.assertEqual([c['action'] for c in inspection['commands']],['inspect'])
        self.assertEqual(inspection['operation'],'keep')

    def test_missing_ack_expires_to_safe_stop_without_delivery(self):
        self.start_program()
        inspection=self.decide();self.accept(inspection,completed=False)
        self.o['time']=17
        stopped=self.decide()
        self.assertEqual((stopped['operation'],stopped['commands']),('safe_stop',[]))
        self.assertNotIn(('deliver','goal/δ'),self.policy.completed)

    def test_new_obstacle_aborts_program_before_approach(self):
        self.start_program()
        self.accept(self.decide())
        self.o['zones'].append({'id':'closed/corridor','type':'restricted',
            'geometry':{'type':'box','min':[1.4,1.4,-1],'max':[1.6,1.6,1]},
            'risk':1,'access':{},'constraints':[]})
        stopped=self.decide()
        self.assertEqual((stopped['operation'],stopped['commands']),('safe_stop',[]))

    def test_resource_loss_before_delivery_does_not_issue_delivery(self):
        self.start_program();self.accept(self.decide());self.accept(self.decide())
        self.carrier['resources']['kit/47']['value']=0
        stopped=self.decide()
        self.assertEqual((stopped['operation'],stopped['commands']),('safe_stop',[]))

    def test_rejected_synthesis_does_not_retry_or_wait_for_unaccepted_roles(self):
        self.target(priority=1.);self.o['observation_quality']['stale_data_ratio']=.8
        rejected=self.decide();self.assertEqual(rejected['operation'],'synthesize')
        self.policy.reject(self.o['time'],'INVALID_SCENARIO')
        fallback=self.decide()
        self.assertNotEqual(fallback['operation'],'synthesize')
        self.assertTrue(fallback['commands'])
        self.assertIsNone(self.policy.program)


if __name__=='__main__':unittest.main()
