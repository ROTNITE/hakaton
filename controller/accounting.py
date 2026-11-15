"""Pure usage/cost accounting. The LIVE ledger is the only request counter.

Money is an estimate from measured usage, never a claim of a provider debit.
Unknown categories remain null; nested token details are not added to totals.
"""
from __future__ import annotations

from collections import Counter,defaultdict
from copy import deepcopy
import csv
from datetime import datetime,timezone
from decimal import Decimal
import hashlib
import io
import json
import math


TARIFF={
    'id':'deepseek-flash-usd-20261111','provider':'deepseek','currency':'USD','unit_tokens':1000000,
    'models':['deepseek-flash','DeepSeek-V4.1-Flash-1017'],
    'source':'https://api-docs.deepseek.com/quick_start/pricing/',
    'checked_utc':'2026-11-11T13:55:25+00:00','effective_from':None,
    'effective_from_reason':'The official table does not state an effective date.',
    'peak_utc_weekday_intervals':[[1,4],[6,10]],
    'holiday_exception':'Chinese public holidays use off-peak rates; no holiday calendar is assumed.',
    'rates_per_million':{'off_peak':{'input_hit':'0.003','input_miss':'0.15','output':'0.6'},
                         'peak':{'input_hit':'0.006','input_miss':'0.3','output':'1.2'}},
}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def validate_tariff(value):
    if not isinstance(value,dict):raise ValueError('Tariff must be an object')
    for key in ('id','provider','currency','source','checked_utc'):
        if not isinstance(value.get(key),str) or not value[key]:raise ValueError('Missing tariff '+key)
    if len(value['currency'])!=3 or not value['currency'].isupper():raise ValueError('Invalid tariff currency')
    if type(value.get('unit_tokens')) is not int or value['unit_tokens']<=0:raise ValueError('Invalid tariff unit')
    if not isinstance(value.get('models'),list) or not value['models'] or any(not isinstance(m,str) for m in value['models']):
        raise ValueError('Invalid tariff models')
    checked=datetime.fromisoformat(value['checked_utc'].replace('Z','+00:00'))
    if checked.tzinfo is None:raise ValueError('Tariff check requires a timezone')
    for period in ('peak','off_peak'):
        for key in ('input_hit','input_miss','output'):
            rate=Decimal(value['rates_per_million'][period][key])
            if not rate.is_finite() or rate<0:raise ValueError('Invalid tariff rate')
    return deepcopy(value)


def numeric_usage(value,depth=0):
    if not isinstance(value,dict) or depth>64:return None
    output={}
    for key,child in value.items():
        if isinstance(child,dict):
            nested=numeric_usage(child,depth+1)
            if nested:output[key]=nested
        elif type(child) in (int,float):
            try:finite=math.isfinite(child)
            except OverflowError:finite=False
            if finite:output[key]=child
    return output


def normalize_usage(raw):
    raw=numeric_usage(raw) or {};missing={};inconsistencies=[]
    def count(*paths):
        found=[]
        for path in paths:
            value=raw
            for key in path.split('.'):
                value=value.get(key) if isinstance(value,dict) else None
            if type(value) is int and 0<=value<=10**12:found.append(value)
            elif value is not None:inconsistencies.append('invalid_token_count:'+path)
        if len(set(found))>1:inconsistencies.append('alias_mismatch:'+paths[0])
        return found[0] if found else None
    result={'input_tokens':count('prompt_tokens','input_tokens'),
            'output_tokens':count('completion_tokens','output_tokens'),
            'total_tokens':count('total_tokens'),
            'input_cache_hit_tokens':count('prompt_cache_hit_tokens','prompt_tokens_details.cached_tokens','input_tokens_details.cached_tokens'),
            'input_cache_miss_tokens':count('prompt_cache_miss_tokens'),
            'reasoning_tokens':count('completion_tokens_details.reasoning_tokens','output_tokens_details.reasoning_tokens')}
    methods={key:'reported' for key,value in result.items() if value is not None}
    total=result['input_tokens'];hit=result['input_cache_hit_tokens'];miss=result['input_cache_miss_tokens']
    if total is not None:
        if hit is not None and hit>total or miss is not None and miss>total:
            inconsistencies.append('cache_exceeds_input')
        elif hit is not None and miss is not None and hit+miss!=total:
            inconsistencies.append('cache_partition_does_not_equal_input')
        elif hit is not None and miss is None:
            result['input_cache_miss_tokens']=total-hit;methods['input_cache_miss_tokens']='input_minus_reported_hit'
        elif miss is not None and hit is None:
            result['input_cache_hit_tokens']=total-miss;methods['input_cache_hit_tokens']='input_minus_reported_miss'
    if result['total_tokens'] is not None and total is not None and result['output_tokens'] is not None:
        if result['total_tokens']!=total+result['output_tokens']:inconsistencies.append('reported_total_mismatch')
    for key,value in result.items():
        if value is None:missing[key]='not_reported'
    return {**result,'methods':methods,'unknown_reasons':missing,'inconsistencies':inconsistencies}


def pricing_periods(timestamp,tariff=None):
    try:
        value=datetime.fromisoformat(timestamp.replace('Z','+00:00'))
        if value.tzinfo is None:raise ValueError('missing UTC offset')
        value=value.astimezone(timezone.utc)
    except (AttributeError,TypeError,ValueError):return ['off_peak','peak'],'unknown_request_time'
    hour=value.hour+value.minute/60+value.second/3600
    if value.weekday()>=5 or not any(a<=hour<b for a,b in (tariff or TARIFF)['peak_utc_weekday_intervals']):return ['off_peak'],None
    return ['off_peak','peak'],'weekday_peak_or_chinese_public_holiday'


def estimate_cost(usage,*,timestamp,tariff=None,model='deepseek-flash'):
    tariff=deepcopy(tariff or TARIFF);currency=tariff['currency'];reasons=[]
    empty={'kind':'token_estimate','currency':currency,'tariff_id':tariff['id'],'tariff_sha256':digest(tariff),
           'amount':None,'known_minimum':None,'known_maximum':None,'complete':False,
           'actual_debit':None,'billing_reason':'No attributable provider billing statement is available.',
           'formula':'(input_hit*hit_rate + input_miss*miss_rate + output*output_rate) / unit_tokens'}
    if model not in tariff['models']:return {**empty,'unknown_reasons':['unpriced_actual_model']}
    if usage['inconsistencies']:return {**empty,'unknown_reasons':usage['inconsistencies']}
    try:
        requested_at=datetime.fromisoformat(timestamp.replace('Z','+00:00'))
        checked_at=datetime.fromisoformat(tariff['checked_utc'].replace('Z','+00:00'))
        if requested_at.tzinfo is None or checked_at.tzinfo is None:raise ValueError('missing timezone')
        if requested_at.astimezone(timezone.utc).date()!=checked_at.astimezone(timezone.utc).date():
            return {**empty,'unknown_reasons':['pricing_snapshot_not_verified_on_request_date']}
    except (AttributeError,TypeError,ValueError):return {**empty,'unknown_reasons':['unknown_request_or_pricing_time']}
    periods,period_reason=pricing_periods(timestamp,tariff)
    if period_reason:reasons.append(period_reason)
    inp,out=usage['input_tokens'],usage['output_tokens']
    hit,miss=usage['input_cache_hit_tokens'],usage['input_cache_miss_tokens']
    bounds=[];known=inp is not None or out is not None
    for period in periods:
        rates={k:Decimal(v) for k,v in tariff['rates_per_million'][period].items()};lower=upper=Decimal(0)
        if hit is not None and miss is not None:
            lower=upper=Decimal(hit)*rates['input_hit']+Decimal(miss)*rates['input_miss']
        elif inp is not None:
            lower=Decimal(inp)*min(rates['input_hit'],rates['input_miss'])
            upper=Decimal(inp)*max(rates['input_hit'],rates['input_miss'])
        if out is not None:lower+=Decimal(out)*rates['output'];upper+=Decimal(out)*rates['output']
        bounds.append((lower/Decimal(tariff['unit_tokens']),upper/Decimal(tariff['unit_tokens'])))
    if inp is None:reasons.append('input_usage_unknown')
    if out is None:reasons.append('output_usage_unknown')
    if hit is None or miss is None:reasons.append('cache_partition_unknown')
    complete=inp is not None and out is not None and hit is not None and miss is not None and len(periods)==1
    lower=min(b[0] for b in bounds) if known else None
    upper=max(b[1] for b in bounds) if inp is not None and out is not None else None
    return {**empty,'amount':str(lower) if complete else None,'known_minimum':str(lower) if lower is not None else None,
            'known_maximum':str(upper) if upper is not None else None,'complete':complete,
            'pricing_periods':periods,'unknown_reasons':reasons}


def percentile(values,fraction):
    return sorted(values)[max(0,math.ceil(len(values)*fraction)-1)] if values else None


def summarize(rows,*,blocked=(),budget=None):
    """Rows are attempts. Replay is never inserted as a new LIVE purchase."""
    normalized=[]
    for source in rows:
        row=deepcopy(source)
        if 'normalized_usage' not in row:row['normalized_usage']=normalize_usage(row.get('usage'))
        if 'cost' not in row:row['cost']={**estimate_cost(row['normalized_usage'],timestamp=row.get('reserved_utc')),
                                         'reconstructed':True,'usage_completeness':'legacy_numeric_subset'}
        normalized.append(row)
    token_totals={}
    for key in ('input_tokens','output_tokens','total_tokens','input_cache_hit_tokens','input_cache_miss_tokens','reasoning_tokens'):
        values=[r['normalized_usage'][key] for r in normalized if r['normalized_usage'][key] is not None]
        token_totals[key]={'known_sum':sum(values) if values else None,'known_records':len(values),
                           'unknown_records':len(rows)-len(values),'complete_total':sum(values) if len(values)==len(rows) else None}
    money={}
    for currency in {r['cost']['currency'] for r in normalized}:
        costs=[r['cost'] for r in normalized if r['cost']['currency']==currency]
        amounts=[Decimal(c['amount']) for c in costs if c['amount'] is not None]
        minima=[Decimal(c['known_minimum']) for c in costs if c['known_minimum'] is not None]
        maxima=[Decimal(c['known_maximum']) for c in costs if c['known_maximum'] is not None]
        money[currency]={'estimated_complete_total':str(sum(amounts)) if len(amounts)==len(costs) else None,
            'known_subtotal_minimum':str(sum(minima)) if minima else None,
            'known_subtotal_maximum':str(sum(maxima)) if maxima else None,
            'exact_estimate_records':len(amounts),'bounded_records':len(maxima),
            'incomplete_records':len(costs)-len(amounts),'unbounded_records':len(costs)-len(maxima),
            'actual_debit':None,'actual_debit_reason':'No attributable billing data.',
            'mean_known_exact_estimate':str(sum(amounts)/Decimal(len(amounts))) if amounts else None,
            'mean_bounded_estimate':{'minimum':str(sum(minima)/Decimal(len(maxima))) if maxima else None,
                'maximum':str(sum(maxima)/Decimal(len(maxima))) if maxima else None,'sample_size':len(maxima)}}
    latencies=[r['latency_s'] for r in rows if type(r.get('latency_s')) in (int,float)]
    totals=[r['normalized_usage']['total_tokens'] for r in normalized if r['normalized_usage']['total_tokens'] is not None]
    return {'format':'metarescue.api-summary.v1','network_attempts':len(rows),
        'logical_requests':len({r.get('logical_request_id',r['request_id']) for r in rows}),
        'retries':sum(max(0,r.get('attempt',1)-1)>0 for r in rows),'statuses':dict(Counter(r['status'] for r in rows)),
        'schema_rejections':sum(r.get('outcome',{}).get('schema_valid') is False for r in rows),
        'semantic_rejections':sum(r.get('outcome',{}).get('controller_validated') is False for r in rows),
        'controller_applied':sum(r.get('outcome',{}).get('controller_applied') is True for r in rows),
        'physical_applications_confirmed':sum(r.get('outcome',{}).get('physical_application')=='confirmed' for r in rows),
        'budget_blocked':len(blocked),'budget':budget,'tokens':token_totals,'money':money,
        'latency_s':{'sample_size':len(latencies),'p50':percentile(latencies,.5),'p95':percentile(latencies,.95),
                     'mean':sum(latencies)/len(latencies) if latencies else None,'method':'nearest_rank'},
        'mean_total_tokens':{'value':sum(totals)/len(totals) if totals else None,'sample_size':len(totals)},
        'zero_new_api_cost':not rows,'billing_verified':False}


def report_text(summary):
    lines=['MetaRescue API: token estimates, not confirmed provider debits.',
           'Network attempts: '+str(summary['network_attempts'])+'; logical requests: '+str(summary['logical_requests']),
           'Statuses: '+json.dumps(summary['statuses'])+'; blocked: '+str(summary['budget_blocked']),
           'Budget: '+json.dumps(summary['budget']),
           'Latency seconds: '+json.dumps(summary['latency_s']),
           'Usage: '+json.dumps(summary['tokens']),
           'Estimated cost by currency (incomplete records remain unknown): '+json.dumps(summary['money'])]
    return '\n'.join(lines)+'\n'


def report_csv(rows):
    stream=io.StringIO(newline='');fields=['attempt_id','logical_request_id','attempt','retry_of','backoff_s',
        'run_id','episode_id','purpose','role','agent_id','requested_model','returned_model',
        'status','reserved_utc','finished_utc','latency_s','http_status','input_tokens','output_tokens','total_tokens',
        'input_cache_hit_tokens','input_cache_miss_tokens','reasoning_tokens','usage_unknown_reasons',
        'currency','estimated_cost','cost_minimum','cost_maximum','cost_complete','cost_unknown_reasons','tariff_id',
        'error_code','schema_valid','envelope_valid','controller_validated','controller_applied','physical_application',
        'config_sha256','map_sha256','usage_raw_path']
    writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
    for row in rows:
        usage=row.get('normalized_usage') or normalize_usage(row.get('usage'))
        cost=row.get('cost') or estimate_cost(usage,timestamp=row.get('reserved_utc'))
        writer.writerow({**{key:row.get(key) for key in fields if key in row},'attempt_id':row['id'],
            'logical_request_id':row.get('logical_request_id',row['request_id']),
            **{key:row.get('context',{}).get(key) for key in ('run_id','purpose','config_sha256','map_sha256')},
            **{key:row.get('outcome',{}).get(key) for key in ('schema_valid','envelope_valid','controller_validated','controller_applied','physical_application')},
            **{k:usage[k] for k in fields if k in usage},'usage_unknown_reasons':json.dumps(usage['unknown_reasons']),
            'currency':cost['currency'],'estimated_cost':cost['amount'],'cost_complete':cost['complete'],'tariff_id':cost['tariff_id'],
            'cost_minimum':cost['known_minimum'],'cost_maximum':cost['known_maximum'],'cost_unknown_reasons':json.dumps(cost['unknown_reasons']),
            'usage_raw_path':(row.get('usage_raw') or {}).get('path')})
    return stream.getvalue()
