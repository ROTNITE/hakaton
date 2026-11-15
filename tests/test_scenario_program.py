from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from controller.scenario_program import ProgramError, ScenarioProgram, coalition_rules, semantic_program
from controller.scenarios import COALITION, COVERAGE, PRIORITY, ScenarioGames, ScenarioCoordinator
from controller.decisions import decision
from test_problem_builder import public_state


ROOT=Path(__file__).resolve().parents[1]
CATALOG={row['id']:row for row in json.loads((ROOT/'unreal/MetaRescue/Content/Scenario/core-scenarios-v1.json').read_text(encoding='utf-8'))['scenarios']}
NAMES={'relay':'opaque:r','executor':'§helper'}
ASSIGNMENTS={agent:role for role,agent in NAMES.items()}
PARAMETERS={'relay_position':[35,22,12],'target_position':[72,10,.47],
            'target_id':'target','resource_id':'medical_kits','amount':2}
CAPABILITIES={'supported_scenarios':CATALOG,'radio_model':{'range_m':72},'supported_actions':
    {name:{'parameters_schema':{'type':'object','required':fields}}
     for name,fields in (('move',['target']),('relay',['enabled']),('send_message',['recipient_id','payload']),
                          ('deliver',['target_id','resource_id','amount']))}}


def declaration(*,synthesize=False):
    value=deepcopy(CATALOG[COALITION]);value['execution_rules']=coalition_rules(synthesized=synthesize)
    if synthesize:
        value['parameter_schema']['properties']['executor_id']={'type':'string'}
        value['parameter_schema']['required'].append('executor_id')
    return value


def agent(role,*,revision=4,connected=True):
    return {'id':NAMES[role],'configuration_revision':revision,'role':role,
            'status':'active' if connected else 'offline','communication':{'reachable':connected},
            'available_actions':[{'action':name} for name in CAPABILITIES['supported_actions']]}


def state(time,*,revision=4,connected=True):
    return {'time':time,'agents':[agent('relay',revision=revision),agent('executor',connected=connected)]}


def dispatch(program,time,action,*,connected=True):
    commands=program.propose(state(time,connected=connected),4)
    assert [c['action'] for c in commands]==[action],commands
    request={'decision_id':f'decision-{time}','time':time}
    program.bind(request,[0])
    return request


def ack(program,request,*,status='completed',delivery='delivered'):
    program.observe({'command_results':[{'decision_id':request['decision_id'],'command_index':0,
                      'execution_status':status,'delivery_status':delivery,'validation_status':'accepted'}]})


class ScenarioProgramTests(unittest.TestCase):
    def test_synthesis_adds_acknowledged_peer_dependency_and_waits_for_public_roles(self):
        program=ScenarioProgram(declaration(synthesize=True),{**PARAMETERS,'executor_id':NAMES['executor']},
                                ASSIGNMENTS,CAPABILITIES,known_rules=[coalition_rules()])
        self.assertEqual(program.propose(state(1,revision=3),4),[])
        route=dispatch(program,2,'move',connected=False)
        self.assertEqual(program.propose(state(3,connected=False),4),[])
        ack(program,route)
        relay=dispatch(program,4,'relay',connected=False);ack(program,relay)
        self.assertEqual(program.propose(state(5,connected=False),4),[])
        message=dispatch(program,6,'send_message')
        ack(program,message,status='unknown',delivery='unknown')
        self.assertEqual(program.propose(state(7),4),[])
        ack(program,message)
        approach=dispatch(program,8,'move');ack(program,approach)
        aid=dispatch(program,9,'deliver')
        self.assertEqual(program.propose(state(10),4),[])
        ack(program,aid)
        self.assertEqual(program.propose(state(11),4),[])
        self.assertEqual(program.outcome,'success')
        self.assertEqual(sum(t['type']=='scenario_phase_dispatch' for t in program.drain()),5)

    def test_unknown_ack_expires_to_safe_degradation_without_new_delivery(self):
        program=ScenarioProgram(declaration(),PARAMETERS,ASSIGNMENTS,CAPABILITIES)
        route=dispatch(program,0,'move');ack(program,route,status='unknown',delivery='unknown')
        self.assertEqual(program.propose(state(12),4),[])
        self.assertEqual(program.propose(state(50),4),[])
        self.assertEqual(program.outcome,'safe_degradation')
        self.assertEqual(sum(t['type']=='scenario_phase_dispatch' for t in program.drain()),1)

    def test_renamed_reordered_and_retimed_library_graph_is_not_novel(self):
        old=coalition_rules();renamed=deepcopy(old)
        renamed['initial_state']='new_'+renamed['initial_state']
        renamed['deadline_seconds']+=10
        for entry in renamed['states']:
            entry['id']='new_'+entry['id']
            if 'transition' in entry:
                for key in ('on_success','on_failure'):entry['transition'][key]='new_'+entry['transition'][key]
                entry['timeout']['on_timeout']='new_'+entry['timeout']['on_timeout']
        renamed['states'].reverse()
        self.assertEqual(semantic_program(old),semantic_program(renamed))
        with self.assertRaisesRegex(ProgramError,'existing program'):
            ScenarioProgram({**declaration(),'execution_rules':renamed},PARAMETERS,ASSIGNMENTS,
                            CAPABILITIES,known_rules=[old])
        renamed['states'][-1]['transition']['on_success']='missing'
        with self.assertRaisesRegex(ProgramError,'missing state'):
            ScenarioProgram({**declaration(),'execution_rules':renamed},PARAMETERS,ASSIGNMENTS,CAPABILITIES)

    def test_games_use_delivered_roles_and_predicates_and_compose_priority(self):
        observation=public_state();observation['mission']['status']='active'
        for row in observation['agents']:row['communication']={'reachable':True}
        plan=observation['metaevolution']['plan']
        plan['accepted_configuration']['scenario_ids']=[COVERAGE]
        plan['desired_role_assignments']={observation['agents'][0]['id']:'rescuer',observation['agents'][1]['id']:'scout'}
        seen=[]
        policy=SimpleNamespace(completed_sectors=set(),builder=None,jobs={},request_replan=lambda **row:seen.append(row))
        evaluated=ScenarioGames(CAPABILITIES).evaluate(observation,policy)
        self.assertTrue(evaluated[PRIORITY].applicable)
        self.assertFalse(evaluated[COALITION].applicable)
        self.assertEqual(set(evaluated[PRIORITY].evidence),{'N','A','I','U','K','Theta','E'})
        chosen=ScenarioCoordinator(CAPABILITIES).apply(observation,decision(observation),policy)
        self.assertEqual(chosen['operation'],'compose')
        self.assertEqual(chosen['selected_configuration']['parameters']['by_scenario'][PRIORITY]['target_id'],'t/first')
        self.assertEqual(seen[0]['planners'],('rescue',))

    def test_coverage_modification_follows_delivered_observation_delay(self):
        observation=public_state()
        observation['mission']['status']='active'
        observation['targets']=[]
        observation['observation_quality']={'maximum_delay':6.4}
        plan=observation['metaevolution']['plan']
        plan['accepted_configuration']['scenario_ids']=[COVERAGE]
        plan['desired_role_assignments']={observation['agents'][1]['id']:'scout'}
        policy=SimpleNamespace(completed_sectors=set(),builder=None,jobs={})
        result=ScenarioCoordinator(CAPABILITIES).apply(observation,decision(observation),policy)
        self.assertEqual(result['operation'],'modify')
        self.assertEqual(result['selected_configuration']['scenario_ids'],[COVERAGE])
        self.assertEqual(result['selected_configuration']['parameters'],{'observation_interval':7.2})
        self.assertIn('scenario_modify',result['explanation']['reason_codes'])
        self.assertEqual(result['explanation']['observation_refs'],[observation['request_id']])
