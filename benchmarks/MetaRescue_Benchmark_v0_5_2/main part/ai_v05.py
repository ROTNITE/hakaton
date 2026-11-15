"""Two DeepSeek roles over the same validated simulator; no access to hidden truth."""
from __future__ import annotations
from collections import defaultdict
from ai_control import AIClient,LOCAL_ALLOWED,GLOBAL_ALLOWED
SCENARIOS={'coverage_search','hazard_verification','priority_response','route_recovery','rescue_support'}

class AIOrchestrator:
    def __init__(self,variant,mode='live',max_calls=240,local_timeout=3,global_timeout=6):
        self.variant=variant;self.has_global=variant in ('global_ai','global_local_ai');self.has_local=variant=='global_local_ai'
        self.client=AIClient(mode,local_timeout=local_timeout,global_timeout=global_timeout,max_calls=max_calls)
        # Keep global capacity while preserving local opportunities; total remains max_calls.
        if self.has_local:self.client.local_reserved=max(1,max_calls//3)
        self.audit=[];self.local_mem=defaultdict(list);self.global_mem=[]
        self.last_global=-1e9;self.global_actions=0;self.local_actions=0;self.fallbacks=0
        self.plan_version=1
    def record(self,t,source,kind,**kw):
        self.audit.append({'t':round(t,4),'source':source,'type':kind,**kw})
    def local_decide(self,t,agent,event,candidates,context):
        if not self.has_local:return None,0.
        observation={**context,'agent_id':agent,'plan_version':self.plan_version,
                     'event':event,'candidate_actions':[
                        {k:c.get(k) for k in ('id','type','duration','energy','risk','destination')} for c in candidates],
                     'memory':self.local_mem[agent][-6:]}
        response,delay=self.client.decide('local',observation,self.audit,t,agent)
        if not isinstance(response,dict):self.fallbacks+=1;return None,delay
        choice=response.get('decision','').upper()
        candidate=next((c for c in candidates if c['id']==response.get('candidate_id')),None)
        if choice not in LOCAL_ALLOWED or (choice=='DETOUR' and not candidate):
            self.record(t,'validator','LOCAL_REJECTED',agent=agent,reason='invalid_candidate',response=response)
            self.fallbacks+=1;return None,delay
        if choice in ('KEEP','DETOUR') and candidate is None:
            self.record(t,'validator','LOCAL_REJECTED',agent=agent,reason='missing_candidate')
            self.fallbacks+=1;return None,delay
        self.local_actions+=1
        info={'time':t,'event':event.get('type'),'decision':choice,
              'candidate_id':response.get('candidate_id'),'reason_codes':response.get('reason_codes',[])}
        self.local_mem[agent].append(info)
        self.record(t,'local_ai','LOCAL_ACCEPTED',agent=agent,decision=choice,
                    candidate_id=response.get('candidate_id'),reason_codes=response.get('reason_codes',[]),
                    explanation=str(response.get('explanation',''))[:400])
        return {'decision':choice,'candidate':candidate,
                'messages':response.get('messages',[]) if isinstance(response.get('messages'),list) else [],
                'request_global_replan':bool(response.get('request_global_replan'))},delay
    def global_decide(self,t,event,context,known_ids,known_sectors,force=False):
        if not self.has_global:return None,0.
        if not force and t-self.last_global<30:return None,0.
        self.last_global=t
        observation={**context,'time':round(t,4),'event':event,
                     'plan_version':self.plan_version,'memory':self.global_mem[-5:]}
        response,delay=self.client.decide('global',observation,self.audit,t)
        if not isinstance(response,dict):self.fallbacks+=1;return None,delay
        op=response.get('operation')
        rep=response.get('replan')
        if op not in GLOBAL_ALLOWED or not isinstance(rep,dict):
            self.record(t,'validator','GLOBAL_REJECTED',reason='invalid_operation_or_replan',response=response)
            self.fallbacks+=1;return None,delay
        offered={c['id']:c for c in observation.get('strategy_candidates',[]) if isinstance(c,dict) and isinstance(c.get('id'),str)}
        strategy_id=response.get('strategy_id','balanced')
        if strategy_id not in offered and offered:
            self.record(t,'validator','GLOBAL_STRATEGY_REJECTED',reason='unknown_strategy_id',offered=list(offered),selected=strategy_id)
            strategy_id='balanced'
        if strategy_id not in offered:strategy_id='balanced'
        raw=response.get('priority_ids') or []
        ids=[x for x in raw if type(x) is int and x in known_ids][:15] if isinstance(raw,list) else []
        rawsecs=response.get('scout_priority_sectors')
        if not isinstance(rawsecs,list):rawsecs=[response.get('scout_priority_sector')]
        secs=[s for s in rawsecs if type(s) is int and s in known_sectors][:12]
        raw_scenarios=response.get('selected_scenarios') or []
        scenarios=[x for x in raw_scenarios if isinstance(x,str) and x in SCENARIOS][:5] if isinstance(raw_scenarios,list) else []
        if not scenarios:
            event_type=event.get('type','')
            scenarios=['hazard_verification','route_recovery'] if 'hazard' in event_type or 'route' in event_type else ['priority_response','rescue_support'] if event_type=='target_detected' else ['coverage_search']
        raw_tasks=response.get('task_proposals') or []
        tasks=[]
        if isinstance(raw_tasks,list):
            for task in raw_tasks[:12]:
                if not isinstance(task,dict):continue
                aid=task.get('agent_id');sec=task.get('sector_id')
                if isinstance(aid,str) and aid.startswith('drone_') and aid[6:].isdigit() and type(sec) is int and sec in known_sectors:
                    tasks.append({'agent_id':aid,'sector_id':sec})
        change={'operation':op,'strategy_id':strategy_id,'priority_ids':ids,'scout_priority_sectors':secs,
                'selected_scenarios':scenarios,'task_proposals':tasks,
                'scout_replan':bool(rep.get('scout')),'rescue_replan':bool(rep.get('rescue')),
                'reason_codes':response.get('reason_codes',[]) if isinstance(response.get('reason_codes'),list) else [],
                'explanation':str(response.get('explanation',''))[:450]}
        if op=='keep':change['scout_replan']=False;change['rescue_replan']=False
        self.global_actions+=1;self.global_mem.append({'t':t,'event':event.get('type'),'decision':change})
        self.record(t,'global_ai','GLOBAL_PROPOSED',decision=change)
        return change,delay
    def summary(self):
        return {**self.client.statistics(),'local_actions':self.local_actions,
                'global_actions':self.global_actions,'fallbacks':self.fallbacks,
                'plan_version':self.plan_version}
