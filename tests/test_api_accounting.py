from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from contracts.protocol import encode
from controller.accounting import TARIFF,estimate_cost,normalize_usage,numeric_usage,summarize,validate_tariff
from controller.advisor import Advisors
from controller.ai import DeepSeek,LiveBudget,Replay,replay_key
from controller.ai_contracts import AIError,example_response
from test_advisor import Deferred
from test_ai import request,state


USAGE={'prompt_tokens':1000,'completion_tokens':100,'total_tokens':1100,
       'prompt_cache_hit_tokens':800,'prompt_cache_miss_tokens':200,
       'prompt_tokens_details':{'cached_tokens':800},'completion_tokens_details':{'reasoning_tokens':20}}


class UsageTests(unittest.TestCase):
    def test_raw_numeric_details_are_preserved_without_double_counting(self):
        raw=numeric_usage({**USAGE,'extra_numeric':3,'unsafe_text':'not retained','bool':True})
        self.assertEqual(raw['prompt_tokens_details'],{'cached_tokens':800})
        self.assertEqual(raw['extra_numeric'],3);self.assertNotIn('unsafe_text',raw);self.assertNotIn('bool',raw)
        normalized=normalize_usage(raw)
        self.assertEqual(normalized['total_tokens'],1100);self.assertEqual(normalized['reasoning_tokens'],20)
        self.assertFalse(normalized['inconsistencies'])
        cost=estimate_cost(normalized,timestamp='2026-11-11T13:00:00Z')
        self.assertEqual(Decimal(cost['amount']),Decimal('0.0000924'))
        self.assertTrue(cost['complete']);self.assertIsNone(cost['actual_debit'])

    def test_missing_usage_and_missing_cache_remain_unknown(self):
        normalized=normalize_usage(None);self.assertIsNone(normalized['total_tokens'])
        cost=estimate_cost(normalized,timestamp='2026-11-11T13:00:00Z')
        self.assertIsNone(cost['amount']);self.assertIsNone(cost['known_minimum']);self.assertIsNone(cost['known_maximum'])
        partial=normalize_usage({'prompt_tokens':1000,'completion_tokens':100,'total_tokens':1100})
        self.assertIsNone(partial['input_cache_hit_tokens'])
        cost=estimate_cost(partial,timestamp='2026-11-11T13:00:00Z')
        self.assertEqual(Decimal(cost['known_minimum']),Decimal('.000063'))
        self.assertEqual(Decimal(cost['known_maximum']),Decimal('.00021'));self.assertIsNone(cost['amount'])

    def test_reported_zero_and_derived_partition_are_distinct_from_missing(self):
        raw={k:v for k,v in USAGE.items() if k not in ('prompt_cache_miss_tokens','prompt_tokens_details')}
        raw['prompt_cache_hit_tokens']=0
        n=normalize_usage(raw);self.assertEqual(n['input_cache_miss_tokens'],1000)
        self.assertEqual(n['methods']['input_cache_miss_tokens'],'input_minus_reported_hit')
        bad=normalize_usage({**USAGE,'prompt_cache_hit_tokens':1001})
        self.assertIn('cache_exceeds_input',bad['inconsistencies'])
        self.assertFalse(estimate_cost(bad,timestamp='2026-11-11T13:00:00Z')['complete'])
        self.assertIn('invalid_token_count:prompt_tokens',normalize_usage({'prompt_tokens':-1})['inconsistencies'])
        duplicate=normalize_usage({**USAGE,'prompt_tokens_details':{'cached_tokens':799}})
        self.assertIn('alias_mismatch:prompt_cache_hit_tokens',duplicate['inconsistencies'])

    def test_peak_holiday_uncertainty_and_currency_are_explicit(self):
        cost=estimate_cost(normalize_usage(USAGE),timestamp='2026-11-11T02:00:00Z')
        self.assertFalse(cost['complete']);self.assertEqual(cost['pricing_periods'],['off_peak','peak'])
        self.assertEqual(Decimal(cost['known_maximum']),2*Decimal(cost['known_minimum']))
        other=deepcopy(TARIFF);other.update(id='verified-eur-example',currency='EUR')
        self.assertEqual(estimate_cost(normalize_usage(USAGE),timestamp='2026-11-11T13:00:00Z',tariff=other)['currency'],'EUR')
        bad=deepcopy(TARIFF);bad['rates_per_million']['peak']['output']='NaN'
        with self.assertRaises(ValueError):validate_tariff(bad)
        old=estimate_cost(normalize_usage(USAGE),timestamp='2026-12-11T13:00:00Z')
        self.assertIsNone(old['amount']);self.assertIn('pricing_snapshot_not_verified_on_request_date',old['unknown_reasons'])


class AccountingLifecycleTests(unittest.TestCase):
    def setUp(self):
        # Lifecycle fixtures use the tariff verified on this UTC date.
        clock=patch('controller.ai.utc',return_value='2026-11-11T13:00:00+00:00')
        clock.start();self.addCleanup(clock.stop)

    def client(self,directory,**kwargs):
        with patch.dict('os.environ',{'METARESCUE_TEST_KEY':'placeholder-test-key'}):
            return DeepSeek(LiveBudget(Path(directory)/'budget.json',limit=8),key_environment='METARESCUE_TEST_KEY',
                            context={'run_id':'trial-1','purpose':'unit_transport','policy':'nsga2_nsga2'},**kwargs)

    @staticmethod
    def api_response(req,**change):
        data={'id':'response-1','model':'deepseek-flash','usage':USAGE,'choices':[
            {'finish_reason':'stop','message':{'content':json.dumps(example_response(req))}}]}
        data.update(change);return encode(data)

    def test_rejected_proposal_keeps_usage_cost_and_schema_outcome_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            provider=self.client(directory);req=request();bad=example_response(req);bad['arbitrary_route']=[[1,2,3]]
            api=self.api_response(req,choices=[{'finish_reason':'stop','message':{'content':json.dumps(bad)}}])
            executor=Deferred();box=Advisors(provider,executor=executor)
            with patch.object(provider,'_post',return_value=api):box.submit(req);executor.complete()
            outcome=box.poll(state(),4)[0];self.assertFalse(outcome['accepted'])
            data=json.loads(provider.budget.path.read_text());row=data['requests'][0]
            self.assertEqual(row['normalized_usage']['total_tokens'],1100);self.assertFalse(row['outcome']['schema_valid'])
            self.assertTrue(row['cost']['complete']);self.assertEqual(row['http_status'],200)
            raw=json.loads(Path(row['usage_raw']['path']).read_text());self.assertEqual(raw,USAGE)
            restored=LiveBudget(provider.budget.path);self.assertEqual(restored.snapshot()['used'],1)
            revision=data['revision'];box.poll(state(),4)
            self.assertEqual(json.loads(provider.budget.path.read_text())['revision'],revision)
            report=restored.report(Path(directory)/'report',run_id='trial-1')
            self.assertEqual(report['summary']['schema_rejections'],1)
            self.assertEqual(json.loads((Path(directory)/'report/run.json').read_text())['network_attempts'],1)
            self.assertIn('0.0000924',(Path(directory)/'report/attempts.csv').read_text(encoding='utf-8-sig'))

    def test_incomplete_output_is_paid_usage_and_timeout_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            provider=self.client(directory);req=request()
            api=self.api_response(req,choices=[{'finish_reason':'length','message':{'content':'{'}}])
            with patch.object(provider,'_post',return_value=api):
                with self.assertRaisesRegex(AIError,'INCOMPLETE_OUTPUT'):provider.complete(req)
            with patch.object(provider,'_post',side_effect=TimeoutError):
                with self.assertRaisesRegex(AIError,'TIMEOUT'):provider.complete(request())
            data=json.loads(provider.budget.path.read_text());first,second=data['requests']
            self.assertEqual(first['normalized_usage']['total_tokens'],1100);self.assertIsNotNone(first['cost']['amount'])
            self.assertIsNone(second['normalized_usage']['total_tokens']);self.assertIsNone(second['cost']['amount'])
            result=summarize(data['requests']);self.assertEqual(result['money']['USD']['unbounded_records'],1)
            self.assertIsNone(result['money']['USD']['estimated_complete_total'])
            self.assertEqual(result['money']['USD']['mean_bounded_estimate']['sample_size'],1)
            self.assertEqual(Decimal(result['money']['USD']['mean_bounded_estimate']['minimum']),Decimal('.0000924'))

    def test_later_request_keeps_tokens_but_does_not_assume_old_tariff_is_current(self):
        with tempfile.TemporaryDirectory() as directory:
            provider=self.client(directory);req=request()
            with patch('controller.ai.utc',return_value='2026-11-12T13:00:00+00:00'),\
                 patch.object(provider,'_post',return_value=self.api_response(req)):
                provider.complete(req)
            row=json.loads(provider.budget.path.read_text())['requests'][0]
            self.assertEqual(row['normalized_usage']['total_tokens'],1100)
            self.assertIsNone(row['cost']['amount'])
            self.assertIn('pricing_snapshot_not_verified_on_request_date',row['cost']['unknown_reasons'])

    def test_explicit_retry_has_new_ticket_same_logical_id_and_is_charged_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            provider=self.client(directory);req=request()
            with patch.object(provider,'_post',return_value=self.api_response(req)):
                one=provider.complete(req);two=provider.complete(req)
            self.assertNotEqual(one['budget_ticket'],two['budget_ticket'])
            rows=json.loads(provider.budget.path.read_text())['requests'];self.assertEqual(rows[1]['retry_of'],rows[0]['id'])
            result=summarize(rows);self.assertEqual(result['network_attempts'],2);self.assertEqual(result['logical_requests'],1)
            self.assertEqual(result['retries'],1);self.assertEqual(result['tokens']['total_tokens']['known_sum'],2200)

    def test_price_change_does_not_reprice_earlier_records_and_currencies_stay_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            provider=self.client(directory);req=request()
            with patch.object(provider,'_post',return_value=self.api_response(req)):provider.complete(req)
            first=json.loads(provider.budget.path.read_text())['requests'][0]['cost']
            provider.tariff=deepcopy(TARIFF);provider.tariff.update(id='price-revision-2',currency='EUR')
            provider.tariff['rates_per_million']['off_peak']['output']='1.2'
            with patch.object(provider,'_post',return_value=self.api_response(req)):provider.complete(req)
            rows=json.loads(provider.budget.path.read_text())['requests']
            self.assertEqual(rows[0]['cost'],first);self.assertEqual(rows[1]['cost']['tariff_id'],'price-revision-2')
            self.assertEqual(set(summarize(rows)['money']),{'USD','EUR'})

    def test_replay_never_reserves_again_or_mutates_original_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            provider=self.client(directory);req=request()
            with patch.object(provider,'_post',return_value=self.api_response(req)):result=provider.complete(req)
            before=provider.budget.path.read_bytes();executor=Deferred()
            replay=Replay([{'replay_key':replay_key(req),'result':result,'delay_model_s':1}]);box=Advisors(replay,executor=executor)
            box.submit(req);executor.complete();current=state();current['time']=11;box.poll(current,4)
            self.assertEqual(provider.budget.path.read_bytes(),before);self.assertIn(result['budget_ticket'],box.historical_tickets)
            report=provider.budget.report(Path(directory)/'replay-report',run_id='new-replay',historical_tickets=box.historical_tickets)
            run=json.loads((Path(directory)/'replay-report/run.json').read_text());self.assertTrue(run['zero_new_api_cost'])
            self.assertEqual(run['network_attempts'],0)
            historical=json.loads((Path(directory)/'replay-report/historical-replay.json').read_text())
            self.assertEqual(historical['new_api_attempts'],0);self.assertEqual(historical['network_attempts'],1)
            self.assertTrue(historical['zero_new_api_cost'])

    def test_denied_calls_and_idempotent_annotations_do_not_change_used_count(self):
        with tempfile.TemporaryDirectory() as directory:
            budget=LiveBudget(Path(directory)/'budget.json',limit=1);req=request();ticket=budget.reserve(req)
            budget.finish(ticket,status='error',latency_s=.1)
            budget.annotate(ticket,controller_validated=False,rejection_reason='schema_error')
            before=budget.path.read_bytes();budget.annotate(ticket,controller_validated=False,rejection_reason='schema_error')
            self.assertEqual(before,budget.path.read_bytes())
            with self.assertRaisesRegex(AIError,'EXHAUSTED'):budget.reserve(request())
            report=budget.report(Path(directory)/'report')
            self.assertEqual(report['summary']['budget_blocked'],1);self.assertEqual(report['summary']['budget']['used'],1)


if __name__=='__main__':unittest.main()
