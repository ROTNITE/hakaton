from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from contracts.protocol import encode
from controller.ai import DeepSeek,LiveBudget,Mock,Off,Replay,replay_key,load_key
from controller.ai_contracts import AIError,example_response,make_request,validate_proposal


def state():
    return {'episode_id':'episode-a','time':10.,'agents':[
        {'id':'opaque:17','kind':'ground','status':'active','position':[1,2,3],
         'physical':{'remaining_wh':20,'carrying':True,'cargo_target_id':'person-z'},
         'private_sensor_future':{'secret':True}},
        {'id':'second','kind':'aerial','status':'active','position':[10,20,30]}],
        'targets':[{'id':'person-z','priority':3,'status':'confirmed','evacuation_state':'waiting',
                    'position':[20,2,0],'future_health':'must-not-appear'}],
        'events':[],'zones':[],'private_people':[{'id':'hidden'}],'future_events':[1]}


def request(role='global'):
    candidates=([{'id':'balanced','eligible':False,'routes':{},'forecast':{},'utility':0},
                 {'id':'urgent','eligible':True,'routes':{'opaque:17':['person-z']},'utility':2}]
                if role=='global' else [{'id':'detour-1','action':'DETOUR','route':[[2,3,4]]},
                                        {'id':'raise','action':'ESCALATE'}])
    return make_request(role,state(),4,candidates,agent_id='opaque:17' if role=='local' else None)


class AIContractTests(unittest.TestCase):
    def test_inputs_are_immutable_whitelisted_and_local_is_per_agent(self):
        observation=state();candidates=[{'id':'x','action':'HOLD','seconds':3}]
        req=make_request('local',observation,0,candidates,agent_id='opaque:17')
        candidates[0]['seconds']=99;observation['agents'][0]['position'][0]=999
        self.assertEqual(req.data['agent']['position'],[1,2,3]);self.assertEqual(req.data['candidates'][0]['seconds'],3)
        text=req.wire.decode();self.assertNotIn('"id":"second"',text);self.assertNotIn('must-not-appear',text)
        self.assertNotIn('private_sensor_future',text)
        text=request().wire.decode();self.assertNotIn('private_people',text);self.assertNotIn('future_health',text)

    def test_schema_identity_version_and_expiry_gates(self):
        req=request();proposal=example_response(req,'SELECT','urgent')
        def check(value,**kw):
            return validate_proposal(req,value,episode_id='episode-a',plan_version=4,now=12,**kw)
        self.assertEqual(check(proposal)['id'],'urgent')
        for key,value in [('request_id','other'),('episode_id','other'),('plan_version',3),
                          ('plan_version',True),('valid_until',999),('candidate_id','invented'),
                          ('candidate_id','balanced'),('action','synthesize'),('route',[[999,1,2]])]:
            bad={**proposal,key:value}
            with self.subTest(key=key,value=value),self.assertRaises(AIError):check(bad)
        with self.assertRaisesRegex(AIError,'EXPIRED'):
            validate_proposal(req,proposal,episode_id='episode-a',plan_version=4,now=36)
        with self.assertRaisesRegex(AIError,'STALE_PLAN'):
            validate_proposal(req,proposal,episode_id='episode-a',plan_version=5,now=12)

    def test_local_cannot_change_another_agent_or_action(self):
        req=request('local');proposal=example_response(req,'DETOUR','detour-1')
        validate_proposal(req,proposal,episode_id='episode-a',plan_version=4,now=11)
        for change in ({'agent_id':'second'},{'action':'HOLD'},{'action':'KEEP'}):
            with self.assertRaises(AIError):
                validate_proposal(req,{**proposal,**change},episode_id='episode-a',plan_version=4,now=11)


class AIBudgetTests(unittest.TestCase):
    def test_concurrent_reservations_never_exceed_durable_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'budget.json'
            def reserve(_):
                try:return LiveBudget(path,limit=4).reserve(request())
                except AIError as error:return str(error)
            with ThreadPoolExecutor(max_workers=9) as executor:results=list(executor.map(reserve,range(9)))
            self.assertEqual(results.count('AI_BUDGET_EXHAUSTED'),5)
            data=json.loads(path.read_text());self.assertEqual(data['used'],4)
            self.assertEqual(len({r['id'] for r in data['requests']}),4)
            # A restart and an unfinished reservation cannot replenish the limit.
            with self.assertRaisesRegex(AIError,'EXHAUSTED'):LiveBudget(path,limit=240).reserve(request())
            self.assertEqual(LiveBudget(path).snapshot(),{'used':4,'limit':4})

    def test_corrupt_ledger_is_fail_closed_and_failed_call_is_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'budget.json';budget=LiveBudget(path,limit=2)
            ticket=budget.reserve(request());budget.finish(ticket,status='error',latency_s=.1)
            self.assertEqual(budget.snapshot()['used'],1)
            with self.assertRaisesRegex(AIError,'ALREADY_FINISHED'):budget.finish(ticket,status='x',latency_s=0)
            data=json.loads(path.read_text());data['used']=0;path.write_text(json.dumps(data))
            with self.assertRaisesRegex(AIError,'CORRUPT'):budget.reserve(request())


class AIProviderTests(unittest.TestCase):
    def client(self,directory):
        with patch.dict('os.environ',{'METARESCUE_TEST_KEY':'test-credential-placeholder'}):
            return DeepSeek(LiveBudget(Path(directory)/'budget.json',limit=2),key_environment='METARESCUE_TEST_KEY')

    def test_off_and_mock_never_access_api_or_confirm_live(self):
        self.assertFalse(Off().status()['api_confirmed'])
        with self.assertRaisesRegex(AIError,'AI_OFF'):Off().complete(request())
        for role in ('global','local'):
            req=request(role);provider=Mock();result=provider.complete(req)
            validate_proposal(req,result['proposal'],episode_id='episode-a',plan_version=4,now=10)
            self.assertFalse(provider.status()['api_confirmed'])
            self.assertEqual(result['mode'],'MOCK')

    def test_transport_body_json_disabled_thinking_and_no_secret_in_results(self):
        with tempfile.TemporaryDirectory() as directory:
            provider=self.client(directory);req=request();proposal=example_response(req)
            self.assertTrue(provider.status()['key_configured']);self.assertFalse(provider.status()['api_confirmed'])
            def post(body,timeout):
                ledger=json.loads((Path(directory)/'budget.json').read_text())
                self.assertEqual(ledger['used'],1);self.assertEqual(ledger['requests'][0]['status'],'reserved')
                payload=json.loads(body);self.assertEqual(payload['model'],'deepseek-flash')
                self.assertEqual(payload['thinking'],{'type':'disabled'})
                self.assertEqual(payload['response_format'],{'type':'json_object'})
                self.assertNotIn('test-credential-placeholder',body.decode())
                return encode({'id':'api-example','model':'deepseek-flash','choices':[
                    {'finish_reason':'stop','message':{'content':json.dumps(proposal)}}],
                    'usage':{'prompt_tokens':120,'completion_tokens':40,'total_tokens':160}})
            with patch.object(provider,'_post',side_effect=post):result=provider.complete(req)
            self.assertTrue(provider.status()['api_confirmed']);self.assertEqual(result['usage']['total_tokens'],160)
            self.assertNotIn('test-credential-placeholder',json.dumps(result))
            self.assertNotIn('test-credential-placeholder',(Path(directory)/'budget.json').read_text())

    def test_timeout_and_invalid_output_are_counted_without_automatic_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            provider=self.client(directory)
            with patch.object(provider,'_post',side_effect=TimeoutError) as post:
                with self.assertRaisesRegex(AIError,'TIMEOUT'):provider.complete(request())
                self.assertEqual(post.call_count,1)
            bad=encode({'choices':[{'finish_reason':'stop','message':{'content':'{"x":1,"x":2}'}}]})
            with patch.object(provider,'_post',return_value=bad):
                with self.assertRaisesRegex(AIError,'RESPONSE_INVALID'):provider.complete(request())
            self.assertEqual(provider.budget.snapshot()['used'],2);self.assertFalse(provider.status()['api_confirmed'])
            with patch.object(provider,'_post') as post:
                with self.assertRaisesRegex(AIError,'EXHAUSTED'):provider.complete(request())
                post.assert_not_called()

    def test_secret_file_is_not_copied_into_prompts_or_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'secret.env';path.write_text('# local only\nAPI="file-test-placeholder"\n')
            with patch.dict('os.environ',{},clear=True):
                self.assertEqual(load_key(file_path=path),'file-test-placeholder')
                provider=DeepSeek(LiveBudget(Path(directory)/'budget.json'),key_file=path)
            self.assertNotIn('file-test-placeholder',json.dumps(provider.status()))
            self.assertNotIn('file-test-placeholder',json.dumps(provider.body(request())))

    def test_replay_preserves_recorded_model_delay_and_requires_exact_semantics(self):
        original=request();result=Mock().complete(original)
        replay=Replay([{'replay_key':replay_key(original),'result':result,'delay_model_s':2.5}])
        new_state=state();new_state['episode_id']='replayed-episode'
        new=make_request('global',new_state,4,original.data['candidates'])
        restored=replay.complete(new)
        self.assertEqual(restored['proposal']['episode_id'],'replayed-episode')
        self.assertEqual(restored['recorded_delay_model_s'],2.5);self.assertEqual(restored['mode'],'REPLAY')
        changed=make_request('global',new_state,5,original.data['candidates'])
        with self.assertRaisesRegex(AIError,'REPLAY_MISS'):replay.complete(changed)


if __name__=='__main__':unittest.main()
