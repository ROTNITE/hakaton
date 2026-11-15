from concurrent.futures import Future
from copy import deepcopy
import time
import unittest

from controller.advisor import Advisors
from controller.ai import Mock,Replay,replay_key
from controller.ai_contracts import make_request
from test_ai import request,state


class Deferred:
    def __init__(self):self.tasks=[]
    def submit(self,function,*args):
        future=Future();self.tasks.append((future,function,args));return future
    def complete(self):
        for future,function,args in self.tasks:
            if not future.done():
                try:future.set_result(function(*args))
                except BaseException as error:future.set_exception(error)


class AdvisorTests(unittest.TestCase):
    def test_delayed_local_reply_does_not_block_other_agents_or_global(self):
        executor=Deferred();box=Advisors(Mock(),executor=executor,max_local=1)
        local=request('local');began=time.perf_counter();self.assertTrue(box.submit(local))
        self.assertTrue(box.submit(request('global')))
        self.assertEqual(box.poll(state(),4),[]);self.assertLess(time.perf_counter()-began,.3)
        self.assertFalse(box.submit(request('local')))
        executor.complete();results=box.poll(state(),4)
        self.assertEqual(len(results),2);self.assertTrue(all(r['accepted'] for r in results))
        self.assertEqual(len(box.memory('local','opaque:17')),1);self.assertEqual(box.memory('local','second'),[])

    def test_late_result_version_and_episode_are_rejected_with_full_trace(self):
        for field,value,version,reason in [('time',40,4,'EXPIRED'),('episode_id','other',4,'EPISODE'),
                                           ('time',11,5,'STALE_PLAN')]:
            with self.subTest(reason=reason):
                executor=Deferred();box=Advisors(Mock(),executor=executor);box.submit(request())
                executor.complete();current=state();current[field]=value;outcome=box.poll(current,version)[0]
                self.assertFalse(outcome['accepted']);self.assertIn(reason,outcome['reason'])
                trace=next(t for t in box.drain_traces() if t['type']=='ai_response')
                self.assertIn('response_content',trace['result'])

    def test_timeout_fallback_once_but_running_worker_retains_its_slot(self):
        executor=Deferred();box=Advisors(Mock(),executor=executor,global_timeout_s=.01)
        req=request();box.submit(req)
        box.pending[req.data['request_id']]['wall_started']-=1
        self.assertEqual(box.poll(state(),4)[0]['reason'],'AI_TIMEOUT')
        self.assertEqual(box.poll(state(),4),[]);self.assertFalse(box.submit(request()))
        executor.complete();outcome=box.poll(state(),4)[0]
        self.assertFalse(outcome['accepted']);self.assertIn('AFTER_TIMEOUT',outcome['reason'])
        self.assertEqual(box.counters['timeouts'],1)

    def test_replay_is_available_at_recorded_model_time_without_sleep(self):
        req=request();result=Mock().complete(req);executor=Deferred()
        box=Advisors(Replay([{'replay_key':replay_key(req),'result':result,'delay_model_s':2.5}]),executor=executor)
        box.submit(req);executor.complete();self.assertEqual(box.poll(state(),4),[])
        current=state();current['time']=12.49;self.assertEqual(box.poll(current,4),[])
        current['time']=12.5;self.assertTrue(box.poll(current,4)[0]['accepted'])

    def test_reset_keeps_running_workers_bounded_and_clears_private_memory(self):
        executor=Deferred();box=Advisors(Mock(),executor=executor,max_local=1);req=request('local')
        box.submit(req);executor.tasks[0][0].set_running_or_notify_cancel()
        box.local_memory['opaque:17'].append({'time':10,'action':'HOLD'})
        box.reset('new');self.assertEqual(box.memory('local','opaque:17'),[])
        new=state();new['episode_id']='new'
        other=make_request('local',new,4,req.data['candidates'],agent_id='opaque:17')
        self.assertFalse(box.submit(other))
        executor.complete();self.assertFalse(box.poll(new,4)[0]['accepted'])
        self.assertTrue(box.submit(other))

    def test_unrelated_global_revision_does_not_invalidate_a_local_task(self):
        executor=Deferred();box=Advisors(Mock(),executor=executor)
        box.submit(request('global'));box.submit(request('local'));executor.complete()
        results=box.poll(state(),lambda req:5 if req.role=='global' else 4)
        self.assertFalse(next(r for r in results if r['request'].role=='global')['accepted'])
        self.assertTrue(next(r for r in results if r['request'].role=='local')['accepted'])


if __name__=='__main__':unittest.main()
