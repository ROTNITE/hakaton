from pathlib import Path
import json
import tempfile
import unittest

from controller.decisions import decision
from controller.operator_directives import FORMAT
from controller.operator_input import INPUT_FORMAT, OperatorInput
from tools.issue_operator import enqueue
from test_problem_builder import public_state


CAPS={'extensions':[FORMAT],'supported_actions':{'issue_directive':{'parameters_schema':{
    'type':'object','properties':{'action':{'enum':['hold']},'target_id':{'type':'string'},
        'reason':{'type':'string'},'duration_s':{'type':'number','minimum':1,'maximum':60}},
    'required':['action','target_id','reason','duration_s']}}}}


class OperatorInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path=Path(self.temporary.name)/'оператор.json'
        self.state=public_state()
        self.state['agents'].append({'id':'human','kind':'operator','status':'active',
            'communication':{'reachable':True},'available_actions':[{'action':'issue_directive'}]})
        self.input=OperatorInput(self.path,CAPS)
        self.parameters={'action':'hold','target_id':self.state['agents'][0]['id'],'reason':'hold test','duration_s':10}

    def enqueue(self,**overrides):
        return enqueue(self.path,**{'episode_id':'e','expires_at':20,'parameters':self.parameters,
                                     'request_id':'human-request',**overrides})

    def step(self):
        request=decision(self.state)
        self.input.append(self.state,request)
        return request

    def test_atomic_unicode_queue_is_submitted_once_and_keeps_original_command_ack(self):
        ident=self.enqueue()
        self.assertEqual(self.enqueue(),ident)
        request=self.step()
        self.assertEqual(len(request['commands']),1)
        self.assertEqual(request['commands'][0]['parameters'],self.parameters)
        self.assertEqual(self.step()['commands'],[])
        self.input.observe({'time':1,'command_results':[{'decision_id':request['decision_id'],'command_index':0,
            'agent_id':'human','delivery_status':'delivered','execution_status':'completed','service_result':{'revision':1}}]})
        rows=self.input.drain()
        self.assertEqual([r['state'] for r in rows],['submitted','finished'])
        self.assertEqual(rows[1]['result']['service_result']['revision'],1)

    def test_stale_episode_expired_request_and_missing_extension_cannot_issue(self):
        self.enqueue(episode_id='old-e')
        self.assertEqual(self.step()['commands'],[])
        self.assertIn('current episode',self.input.drain()[0]['reason'])
        self.path.write_text(json.dumps({'format':INPUT_FORMAT,'episode_id':'e','requests':[
            {'id':'expired','expires_at':0,'parameters':self.parameters}]}),encoding='utf-8')
        self.assertEqual(self.step()['commands'],[])
        self.assertEqual(self.input.drain()[0]['state'],'expired')
        empty=OperatorInput(self.path,{})
        request=decision(self.state)
        empty.append(self.state,request)
        self.assertEqual(request['commands'],[])
        self.assertIn('does not advertise',empty.drain()[0]['reason'])

    def test_changed_request_id_is_rejected_and_never_reexecuted(self):
        self.enqueue()
        self.step()
        with self.assertRaisesRegex(ValueError,'different input'):
            self.enqueue(parameters={**self.parameters,'duration_s':20})
        data=json.loads(self.path.read_bytes())
        data['requests'][0]['parameters']['duration_s']=20
        self.path.write_text(json.dumps(data),encoding='utf-8')
        self.assertEqual(self.step()['commands'],[])
        self.assertEqual(self.input.drain()[-1]['reason'],'request_id_reused_with_different_input')
        self.step()
        self.assertEqual(self.input.drain(),[])

    def test_schema_or_json_failure_is_logged_without_stopping_the_rescue_loop(self):
        self.enqueue(parameters={**self.parameters,'duration_s':100})
        self.assertEqual(self.step()['commands'],[])
        self.assertEqual(self.input.drain()[0]['state'],'rejected')
        self.path.write_text('{"broken":',encoding='utf-8')
        self.assertEqual(self.step()['commands'],[])
        self.assertEqual(self.input.drain()[0]['state'],'rejected')
        self.step()
        self.assertEqual(self.input.drain(),[])

    def test_offline_operator_waits_then_submits_and_episode_reset_forgets_old_ids(self):
        self.enqueue()
        operator=self.state['agents'][-1]
        operator['communication']['reachable']=False
        self.assertEqual(self.step()['commands'],[])
        operator['communication']['reachable']=True
        self.assertEqual(len(self.step()['commands']),1)
        self.state['episode_id']='another'
        self.assertEqual(self.step()['commands'],[])
        self.assertEqual(self.input.requests,{})

    def test_writer_never_replaces_another_episode_queue(self):
        self.enqueue()
        before=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'another episode'):
            self.enqueue(episode_id='other')
        self.assertEqual(self.path.read_bytes(),before)

    def test_unknown_target_and_control_characters_do_not_reach_core(self):
        self.enqueue(parameters={**self.parameters,'target_id':'not-public'})
        self.assertEqual(self.step()['commands'],[])
        self.assertIn('Unknown',self.input.drain()[0]['reason'])
        self.path.write_text(json.dumps({'format':INPUT_FORMAT,'episode_id':'e','requests':[
            {'id':'control-character','expires_at':20,'parameters':{**self.parameters,'reason':'bad\nreason'}}]}),encoding='utf-8')
        self.assertEqual(self.step()['commands'],[])
        self.assertIn('control characters',self.input.drain()[0]['reason'])

    def test_safe_stop_does_not_append_new_operator_actions(self):
        self.enqueue()
        request=decision(self.state,operation='safe_stop')
        self.input.append(self.state,request)
        self.assertEqual(request['commands'],[])
        self.assertEqual(self.input.requests,{})

    def test_bad_old_request_does_not_block_a_later_valid_instruction(self):
        self.enqueue(parameters={**self.parameters,'duration_s':100},request_id='bad')
        self.enqueue(request_id='good')
        request=self.step()
        self.assertEqual(len(request['commands']),1)
        self.assertEqual(request['commands'][0]['parameters'],self.parameters)
        rows=self.input.drain()
        self.assertEqual([(row['request_id'],row['state']) for row in rows],[('bad','rejected'),('good','submitted')])


if __name__=='__main__':unittest.main()
