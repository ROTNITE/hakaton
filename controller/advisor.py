"""Nonblocking AI mailbox with separate bounded memories and recorded delay replay."""
from __future__ import annotations

from collections import defaultdict,deque
from concurrent.futures import ThreadPoolExecutor
import time

from controller.ai import replay_key,utc
from controller.ai_contracts import AIError,validate_proposal


class Advisors:
    def __init__(self,provider,*,executor=None,max_local=4,local_timeout_s=3,global_timeout_s=6):
        if type(max_local) is not int or not 1<=max_local<=16:raise ValueError('Invalid local AI concurrency')
        self.provider=provider;self.max_local=max_local
        self.executor=executor or ThreadPoolExecutor(max_workers=max_local+1,thread_name_prefix='rescue-advisor')
        self.owns_executor=executor is None;self.pending={};self.traces=[]
        self.timeouts={'global':global_timeout_s,'local':local_timeout_s}
        self.global_memory=deque(maxlen=8);self.local_memory=defaultdict(lambda:deque(maxlen=8))
        self.episode=None;self.counters={'submitted':0,'validated':0,'rejected':0,'timeouts':0,'fallbacks':0}
        self.cached_status=None;self.status_at=-100
        self.historical_tickets=set()

    def reset(self,episode_id):
        # Running requests remain in the bounded mailbox until their actual return,
        # so a reset cannot start an unbounded number of orphan HTTP workers.
        self.episode=episode_id;self.global_memory.clear();self.local_memory.clear()
        for entry in self.pending.values():
            if entry['future'].cancel():entry['cancelled']=True

    def memory(self,role,agent_id=None):
        return list(self.global_memory if role=='global' else self.local_memory[agent_id])

    def _trace(self,kind,request,**payload):
        data=request.data
        self.traces.append({'type':kind,'request_id':data['request_id'],'episode_id':data['episode_id'],
                            'role':request.role,'agent_id':data.get('agent_id'),**payload})

    def submit(self,request):
        data=request.data
        if self.episode!=data['episode_id']:self.reset(data['episode_id'])
        same=[e for e in self.pending.values() if e['request'].role==request.role]
        if (request.role=='global' and same or request.role=='local' and
            (len(same)>=self.max_local or any(e['request'].data['agent_id']==data['agent_id'] for e in same))):
            self._trace('ai_fallback',request,reason='AI_MAILBOX_BUSY');self.counters['fallbacks']+=1
            return False
        if self.provider.mode=='OFF':
            self._trace('ai_fallback',request,reason='AI_OFF');self.counters['fallbacks']+=1
            return False
        self._trace('ai_request',request,input=data,input_sha256=request.fingerprint,replay_key=replay_key(request),
                    mode=self.provider.mode)
        future=self.executor.submit(self.provider.complete,request)
        self.pending[data['request_id']]={'request':request,'future':future,'wall_started':time.perf_counter(),
                                         'timed_out':False,'cancelled':False,'result':None}
        self.counters['submitted']+=1
        return True

    def available(self,role,agent_id=None):
        entries=[e for e in self.pending.values() if e['request'].role==role]
        return not entries if role=='global' else len(entries)<self.max_local and not any(
            e['request'].data['agent_id']==agent_id for e in entries)

    def poll(self,observation,plan_version):
        now=observation['time'];outcomes=[]
        for identifier,entry in list(self.pending.items()):
            request=entry['request'];future=entry['future'];data=request.data
            elapsed=time.perf_counter()-entry['wall_started']
            if not future.done():
                if elapsed>self.timeouts[request.role] and not entry['timed_out']:
                    entry['timed_out']=True;self.counters['timeouts']+=1;self.counters['fallbacks']+=1
                    self._trace('ai_timeout_fallback',request,wall_elapsed_s=elapsed)
                    outcomes.append({'request':request,'accepted':False,'reason':'AI_TIMEOUT'})
                continue
            if entry['cancelled'] or future.cancelled():
                self._trace('ai_cancelled',request,reason='episode_reset');del self.pending[identifier];continue
            result=entry['result']
            if result is None:
                try:result=future.result()
                except Exception as error:
                    reason=str(error) if isinstance(error,AIError) else 'AI_WORKER_ERROR: '+type(error).__name__
                    ticket=error.details.get('budget_ticket') if isinstance(error,AIError) else None
                    if ticket and hasattr(self.provider,'record_outcome'):
                        self.provider.record_outcome(ticket,envelope_valid=False,controller_validated=False,
                                                     rejection_reason=reason,validation_utc=utc())
                    self._trace('ai_error',request,reason=reason,wall_elapsed_s=elapsed,
                                delay_model_s=now-data['based_on_time'],replay_key=replay_key(request),
                                details=error.details if isinstance(error,AIError) else {})
                    self.counters['rejected']+=1;self.counters['fallbacks']+=1
                    outcomes.append({'request':request,'accepted':False,'reason':reason})
                    del self.pending[identifier];continue
                entry['result']=result
            available=data['based_on_time']+result.get('recorded_delay_model_s',0)
            if now<available:continue
            reason=None;candidate=None
            try:
                if entry['timed_out']:raise AIError('AI_RETURNED_AFTER_TIMEOUT')
                if result.get('replay_error'):raise AIError(result['replay_error'])
                current_version=plan_version(request) if callable(plan_version) else plan_version
                candidate=validate_proposal(request,result['proposal'],episode_id=observation['episode_id'],
                                            plan_version=current_version,now=now)
            except AIError as error:reason=str(error)
            except (KeyError,TypeError):reason='AI_RESULT_INVALID'
            accepted=reason is None
            ticket=result.get('budget_ticket')
            if ticket and self.provider.mode=='REPLAY':self.historical_tickets.add(ticket)
            if ticket and self.provider.mode=='LIVE' and hasattr(self.provider,'record_outcome'):
                self.provider.record_outcome(ticket,schema_valid=not bool(reason and reason.startswith('AI_SCHEMA_INVALID')),
                    envelope_valid=accepted,rejection_reason=reason,validation_utc=utc(),
                    **({'controller_validated':False} if not accepted else {}))
            self._trace('ai_response',request,result=result,validated=accepted,rejection_reason=reason,
                        delay_model_s=now-data['based_on_time'],wall_elapsed_s=elapsed,replay_key=replay_key(request))
            self.counters['validated' if accepted else 'rejected']+=1
            proposal=result.get('proposal') or {}
            memory={'time':now,'trigger':data['trigger'],'action':proposal.get('action'),
                    'candidate_id':proposal.get('candidate_id'),'validated':accepted,'reason':reason}
            (self.global_memory if request.role=='global' else self.local_memory[data['agent_id']]).append(memory)
            outcomes.append({'request':request,'accepted':accepted,'reason':reason,'result':result,'candidate':candidate})
            del self.pending[identifier]
        return outcomes

    def status(self):
        now=time.perf_counter()
        if self.cached_status is None or now-self.status_at>2:
            try:self.cached_status=self.provider.status()
            except AIError:self.cached_status={'mode':self.provider.mode,'api_confirmed':False,'budget_error':True}
            self.status_at=now
        return {**self.cached_status,'pending':len(self.pending),'counters':dict(self.counters)}

    def drain_traces(self):
        result,self.traces=self.traces,[]
        return result

    def close(self,observation=None,plan_version=0):
        if self.owns_executor:self.executor.shutdown(wait=True,cancel_futures=True)
        if observation is not None:self.poll(observation,plan_version)
        for entry in self.pending.values():
            self._trace('ai_unapplied_at_close',entry['request'],reason='episode_ended',result=entry.get('result'))
        self.pending.clear()
