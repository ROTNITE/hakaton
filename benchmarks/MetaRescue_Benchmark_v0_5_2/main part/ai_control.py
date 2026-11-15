"""Event-triggered global and per-agent DeepSeek proposals, audit, safety boundaries.

Neither LLM receives world.people or the future event tape. Physical execution is
performed by mission.py / scout.py only after deterministic validation.
"""
from __future__ import annotations
import json, os, time, urllib.request, urllib.error, hashlib, random
from collections import defaultdict

LOCAL_ALLOWED={'KEEP','DETOUR','HOLD','ESCALATE'}
GLOBAL_ALLOWED={'keep','select','switch','modify','compose','synthesize','safe_stop'}

class AIClient:
    def __init__(self, mode='live', model=None, key=None, local_timeout=3.0, global_timeout=6.0, max_calls=240):
        self.mode=mode if mode in ('live','mock','off') else 'off'
        self.model=model or os.environ.get('DEEPSEEK_MODEL','deepseek-flash')
        self.key=key or os.environ.get('DEEPSEEK_API_KEY','')
        self.local_timeout=max(.5,min(30,float(local_timeout)))
        self.global_timeout=max(.5,min(60,float(global_timeout)))
        self.max_calls=max(0,min(1600,int(max_calls)))
        self.calls=0;self.role_calls={'global':0,'local':0};self.local_reserved=0;self.tokens_in=0;self.tokens_out=0;self.latency=0.0;self.errors=0
        self.prompts=[]
    @property
    def active(self):return self.mode=='mock' or self.mode=='live' and bool(self.key)
    def decide(self,role,observation,audit,t,agent=None):
        if not self.active:
            audit.append({'t':round(t,3),'source':'ai_client','type':'AI_UNAVAILABLE',
                          'role':role,'agent':agent,'reason':'no_key_or_off','mode':self.mode})
            return None,0.0
        global_quota=self.max_calls-self.local_reserved
        if self.calls>=self.max_calls or (role=='global' and self.role_calls['global']>=global_quota):
            audit.append({'t':round(t,3),'source':'ai_client','type':'AI_BUDGET_EXHAUSTED','role':role,'agent':agent})
            return None,0.0
        self.calls+=1;self.role_calls[role]+=1
        sys_prompt= (
            'You are a LOCAL rescue robot agent (ground or scout). You only know delivered or personally sensed observations. Output JSON only with fields: '
            'decision (KEEP|DETOUR|HOLD|ESCALATE), candidate_id (string or null), '
            'messages (array of {recipient,type,event_ref}), request_global_replan (bool), '
            'reason_codes (array of strings), explanation (one brief observable justification sentence). Choose only supplied safe candidates. '
            'Do not fabricate facts or change another agent task.'
            if role=='local' else
            'You are the GLOBAL strategic coordinator of a rescue swarm. Your job is to make meaningful, verifiable choices among genuine NSGA-II strategy candidates, not to rubber-stamp route recomputations. '
            'You see ONLY delivered observations and candidate forecasts, never hidden victims or future events. '
            'Use fields: operation (keep|select|switch|modify|compose|synthesize|safe_stop), strategy_id (one EXACT id from strategy_candidates or balanced), '
            'replan ({scout:boolean,rescue:boolean}), priority_ids (known integers), scout_priority_sectors (confirmed sectors), '
            'task_proposals (array of {agent_id,sector_id} for confirmed scouts), selected_scenarios (array of coverage_search|hazard_verification|priority_response|route_recovery|rescue_support), '
            'reason_codes (string array), explanation (one brief grounded reason). '
            'Compare baseline to ALL candidate plans using forecast.saved, forecast.priority_saved, forecast.weighted_completion and forecast.energy_Wh across three uncertainty scenarios. '
            'Prefer a candidate marked eligible with a measurable, safety-validated benefit; otherwise return keep and strategy_id=balanced. '
            'You may form a scout-and-rescuer cooperation group by selecting cooperative and a confirmed scout_task. '
            'Changing strategy_id changes the objective weights of the Rescue NSGA-II, and supported scout mode changes adaptive patrol AFTER first coverage. '
            'Never require rechecking confirmed victim sectors just because they contain a victim; do not interrupt an ongoing evacuation. '
            'Every assignment and route is checked by the runtime; your explanation cannot override the validator.'
        )
        body={'model':self.model,'thinking':{'type':'disabled'},'response_format':{'type':'json_object'},
              'temperature':0.1,'max_tokens':450 if role=='local' else 720,
              'messages':[{'role':'system','content':sys_prompt},
                          {'role':'user','content':'Use only this observed JSON state: '+json.dumps(observation,ensure_ascii=False,separators=(',',':'))}]}
        request={'role':role,'agent':agent,'request':body,'model':self.model,'mode':self.mode}
        audit.append({'t':round(t,3),'source':'ai_client','type':'AI_API_REQUEST','data':request})
        st=time.perf_counter();response=None;error=None
        if self.mode=='mock':
            if role=='local':
                options=observation.get('candidate_actions',[])
                choice=next((o for o in options if o.get('type')=='DETOUR'),None)
                response={'decision':'DETOUR' if choice else 'ESCALATE',
                          'candidate_id':choice.get('id') if choice else None,
                          'messages':[{'recipient':'global','type':'ROUTE_BLOCKED',
                                       'event_ref':observation.get('event',{}).get('id','unknown')}],
                          'request_global_replan':not bool(choice),'reason_codes':['observed_route_change'],
                          'explanation':'Detected route change; prefer feasible local A* detour.'}
            else:
                known=observation.get('known_targets',[])
                candidates=observation.get('strategy_candidates') or []
                eligible=[p for p in candidates if p.get('eligible')]
                choice=max(eligible,key=lambda p:p.get('utility',-1e20),default=None)
                event=(observation.get('event') or {})
                needs_scout=event.get('type') in ('hazard_confirmed','audible_signal','route_blocked','hazard_warning')
                response={'operation':'select' if choice else ('modify' if needs_scout else 'keep'),
                          'strategy_id':choice['id'] if choice else 'balanced',
                          'replan':{'scout':needs_scout,'rescue':bool(choice)},
                          'priority_ids':[p['id'] for p in sorted(known,key=lambda x:(-x['priority'],x['id']))[:3]] if choice else [],
                          'scout_priority_sector':event.get('sector') if needs_scout else None,
                          'scout_priority_sectors':[event['sector']] if needs_scout and type(event.get('sector')) is int else [],
                          'selected_scenarios':['hazard_verification','route_recovery'] if needs_scout else ['priority_response'],
                          'task_proposals':choice.get('scout_tasks',[]) if choice else [],
                          'reason_codes':['forecasted_cooperation_gain'] if choice else ['no_forecast_improvement'],
                          'explanation':'Choose forecast-safe NSGA-II objective profile.' if choice else 'Only change patrol for confirmed hazard; rescue plan is unchanged.'}
        else:
            try:
                request_data=json.dumps(body,ensure_ascii=False).encode('utf-8')
                req=urllib.request.Request('https://api.deepseek.com/chat/completions',request_data,
                    headers={'Content-Type':'application/json','Authorization':'Bearer '+self.key},method='POST')
                timeout=self.local_timeout if role=='local' else self.global_timeout
                with urllib.request.urlopen(req,timeout=timeout) as resp:
                    raw=resp.read(250_000).decode('utf-8','replace')
                obj=json.loads(raw)
                choice=obj['choices'][0]
                if choice.get('finish_reason')!='stop':raise ValueError('finish_reason='+str(choice.get('finish_reason')))
                content=choice['message'].get('content','')
                if not content.strip():raise ValueError('Empty JSON response')
                response=json.loads(content)
                usage=obj.get('usage') or {}
                self.tokens_in+=int(usage.get('prompt_tokens') or 0)
                self.tokens_out+=int(usage.get('completion_tokens') or 0)
            except Exception as exc:
                error=f'{type(exc).__name__}: {str(exc)[:240]}'
                self.errors+=1
        elapsed=time.perf_counter()-st
        self.latency+=elapsed
        # Store final visible response only, never unexposed internal reasoning or credentials.
        audit.append({'t':round(t,3),'source':'ai_client',
                      'type':'AI_API_RESPONSE' if response is not None else 'AI_API_ERROR',
                      'role':role,'agent':agent,'latency_s':round(elapsed,4),
                      'response':response,'error':error,
                      'usage_total':{'input_tokens':self.tokens_in,'output_tokens':self.tokens_out}})
        return response,elapsed
    def statistics(self):
        return {'mode':self.mode,'connected':self.active,'model':self.model,'calls':self.calls,'role_calls':dict(self.role_calls),
                'input_tokens':self.tokens_in,'output_tokens':self.tokens_out,
                'api_wall_s':round(self.latency,3),'api_errors':self.errors}

class AIController:
    def __init__(self,world,variant,mode='live',max_calls=240,local_timeout=3,global_timeout=6):
        self.world=world;self.variant=variant
        self.has_global=variant in ('global_ai','global_local_ai')
        self.has_local=variant=='global_local_ai'
        self.client=AIClient(mode,local_timeout=local_timeout,global_timeout=global_timeout,max_calls=max_calls)
        if self.has_local:self.client.local_reserved=max(1,max_calls//2)
        self.audit=[];self.messages=[];self.local_mem=defaultdict(list);self.global_mem=[]
        self.priority_ids=[];self.global_last={};self.plan_version=1
        self.detections={};self.local_actions=0;self.global_actions=0;self.fallbacks=0
        self.public_terrain_changes=[]
    def record(self,t,source,type_,**fields):
        self.audit.append({'t':round(t,4),'source':source,'type':type_,**fields})
    def send(self,t,sender,recipient,type_,payload):
        msg={'message_id':f'msg_{len(self.messages)+1:05d}','t':round(t,4),
             'sender':sender,'recipient':recipient,'type':type_,'payload':payload,
             'delivery_status':'delivered','delivery_t':round(t+0.15,4)}
        self.messages.append(msg);self.record(t,'message_bus','MESSAGE_SENT',message=msg)
        self.record(t+.15,'message_bus','MESSAGE_DELIVERED',message_id=msg['message_id'],recipient=recipient)
        return msg
    def local_event(self,t,r,person_id,kind,pos,carrying,options,energy):
        if not self.has_local:return None,0.0
        aid=f'ground_{r+1:02d}'
        safe_options=[{'id':c['id'],'type':c['type'],'destination':c['destination'],
                       'eta_s':round(c['duration'],2),'energy_Wh':round(c['energy'],2)} for c in options]
        obs={'agent':{'id':aid,'type':'evacuator','position':list(pos),'energy_Wh':round(energy,2)},
             'plan_version':self.plan_version,'event':{'id':f'{kind}_{int(t*100)}','kind':kind,'time':t},
             'task':{'target_id':person_id,'carrying':carrying},
             'candidate_actions':safe_options,
             'memory':self.local_mem[aid][-5:], 'known_nearby_terrain_events':self.public_terrain_changes[-3:]}
        response,latency=self.client.decide('local',obs,self.audit,t,aid)
        if response is None:
            self.fallbacks+=1;return None,latency
        choice=str(response.get('decision','')).upper()
        picked=response.get('candidate_id')
        candidate=next((o for o in options if o['id']==picked),None)
        if choice not in LOCAL_ALLOWED or (choice=='DETOUR' and (candidate is None or candidate['type']!='DETOUR')):
            self.record(t,'validator','LOCAL_REJECTED',agent=aid,reason='invalid_or_unavailable_candidate',response=response)
            self.fallbacks+=1;return None,latency
        self.local_actions+=1
        rationale=list(response.get('reason_codes',[]))[:8] if isinstance(response.get('reason_codes'),list) else []
        self.local_mem[aid].append({'t':t,'kind':kind,'decision':choice,'reasons':rationale})
        self.record(t,'local_ai','LOCAL_ACCEPTED',agent=aid,decision=choice,candidate_id=picked,reasons=rationale,
                    explanation=str(response.get('explanation',''))[:350])
        allowed_types={'ROUTE_BLOCKED','HELP_REQUEST','HAZARD_WARNING','LOW_VISIBILITY','TASK_STATUS'}
        sent=False
        for m in response.get('messages',[])[:5] if isinstance(response.get('messages'),list) else []:
            if not isinstance(m,dict):continue
            dst=m.get('recipient');typ=m.get('type')
            is_robot=isinstance(dst,str) and ((dst.startswith('ground_') and dst[7:].isdigit() and 1<=int(dst[7:])<=self.world.n_rescuers)
                            or (dst.startswith('drone_') and dst[6:].isdigit() and 1<=int(dst[6:])<=self.world.n_scouts))
            if (dst in ('global','broadcast') or is_robot) and typ in allowed_types:
                self.send(t,aid,dst,typ,{'kind':kind,'target_id':person_id,'position':list(pos),
                                       'event_ref':str(m.get('event_ref',''))[:80]});sent=True
        if not sent:self.send(t,aid,'global','ROUTE_BLOCKED',{'kind':kind,'target_id':person_id,'at':list(pos)})
        return candidate if choice=='DETOUR' else {'type':choice,'id':choice},latency
    def global_event(self,t,reason,known,active,terrain=None,signal_sector=None,force=False,phase="mission"):
        if not self.has_global:return None,0.0
        if not force and t-self.global_last.get(phase,-9999)<35:return None,0.0
        self.global_last[phase]=t
        summary=[{'id':p.id,'priority':p.priority,'sector':p.sector} for p in known[:85]]
        obs={'time':round(t,3),'reason':reason,'plan_version':self.plan_version,
             'known_targets':summary,'fleet':{'scouts':self.world.n_scouts,'rescuers':self.world.n_rescuers},
             'active_rescuers':active,'signal_sector':signal_sector,
             'known_terrain_changes':[e for e in self.public_terrain_changes if e['t']<=t][-8:],
             'recent_messages':[m for m in self.messages if m['delivery_t']<=t][-6:],
             'global_memory':[m for m in self.global_mem if m['t']<=t][-5:],
             'constraints':{'priorities':'must be based on confirmed targets',
                            'routes':'only NSGA-II/A* can generate paths'}}
        response,latency=self.client.decide('global',obs,self.audit,t)
        if response is None:
            self.fallbacks+=1;return None,latency
        operation=response.get('operation')
        if operation not in GLOBAL_ALLOWED or not isinstance(response.get('replan'),dict):
            self.record(t,'validator','GLOBAL_REJECTED',reason='invalid_schema',response=response)
            self.fallbacks+=1;return None,latency
        ids={p.id for p in known}
        raw=response.get('priority_ids',[])
        if not isinstance(raw,list):raw=[]
        selected=[i for i in raw if type(i)==int and i in ids][:12]
        sector=response.get('scout_priority_sector')
        if type(sector)!=int or not 0<=sector<self.world.sector_count**2:sector=None
        if sector!=signal_sector:sector=None  # never invent sectors in absence of public signal
        self.priority_ids=selected
        decision={'operation':operation,'priority_ids':selected,'scout_priority_sector':sector,
                  'scout_replan':bool(response['replan'].get('scout')),
                  'rescue_replan':bool(response['replan'].get('rescue')),
                  'reason_codes':response.get('reason_codes',[])[:10] if isinstance(response.get('reason_codes'),list) else [],
                  'explanation':str(response.get('explanation',''))[:350]}
        self.global_actions+=1;self.global_mem.append({'t':t,'reason':reason,'decision':decision})
        self.record(t,'global_ai','GLOBAL_ACCEPTED',decision=decision)
        return decision,latency
    def summary(self):
        return {**self.client.statistics(),'local_actions':self.local_actions,
                'global_actions':self.global_actions,'fallbacks':self.fallbacks,
                'messages':len(self.messages),'plan_version':self.plan_version}
    def local_scout_event(self,t,r,sector,quality):
        if not self.has_local:return None
        aid=f'drone_{r+1:02d}'
        obs={'agent':{'id':aid,'type':'scout','sector':sector},'plan_version':self.plan_version,
             'event':{'id':f'visibility_{sector}_{int(t)}','kind':'unexpected_low_visibility','time':t},
             'candidate_actions':[{'id':'verify_sector','type':'DETOUR','destination':sector,
                                    'eta_s':6,'energy_Wh':1.1}],
             'observation':{'visibility':quality},'memory':self.local_mem[aid][-4:]}
        result,latency=self.client.decide('local',obs,self.audit,t,aid)
        if not isinstance(result,dict):self.fallbacks+=1;return None
        if result.get('decision')=='DETOUR' and result.get('candidate_id')=='verify_sector':
            self.local_actions+=1
            self.local_mem[aid].append({'t':t,'sector':sector,'visibility':quality})
            self.send(t,aid,'global','LOW_VISIBILITY',{'sector':sector,'quality':quality})
            self.record(t,'local_ai','SCOUT_VERIFY_REQUEST',agent=aid,sector=sector)
            return {'sector':sector,'not_before':t+latency+15}
        self.record(t,'local_ai','SCOUT_KEEP',agent=aid,sector=sector)
        return None
