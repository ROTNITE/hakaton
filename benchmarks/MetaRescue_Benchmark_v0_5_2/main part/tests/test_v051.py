"""v0.5.1 regressions: coverage invariants, non-canceling HOLD, global gating."""
from __future__ import annotations
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from patrol_scheduler import PatrolScheduler
from world import World,DEFAULT_PROBABILITIES
from ai_v05 import AIOrchestrator
from mission_v05 import Mission

class V051Tests(unittest.TestCase):
    def setUp(self):
        self.w=World(2026,8,'urban',25,3,4,{k:0 for k in DEFAULT_PROBABILITIES})
    def test_highlight_does_not_remove_unvisited_sectors(self):
        s=PatrolScheduler(self.w,[list(range(0,8)),list(range(8,16)),list(range(16,25))])
        before={sec for q in s.queues for sec in q}
        self.assertEqual(before,set(range(25)))
        s.highlight([1,3,5],10,importance=4)
        self.assertEqual({sec for q in s.queues for sec in q},before)
        self.assertFalse(s.online_nsga2(10))
        self.assertEqual({sec for q in s.queues for sec in q},before)
    def test_all_primary_sectors_reached_and_no_repeat_until_full(self):
        s=PatrolScheduler(self.w,[list(range(25)),[],[]])
        ordered=[]
        for i in range(25):
            r=i%3
            sec=s.select(r,i)
            self.assertIsNotNone(sec)
            self.assertNotIn(sec,ordered)
            ordered.append(sec)
            s.scanned(r,sec,i)
        self.assertEqual(set(ordered),set(range(25)))
        self.assertTrue(s.primary_complete)
        self.assertIsNotNone(s.select(0,26))
    def test_global_routine_target_does_not_call_api(self):
        ai=AIOrchestrator('global_ai','mock')
        m=Mission(self.w,'global_ai',ai)
        m.patrol=PatrolScheduler(self.w,[list(range(25)),[],[]])
        m.confirmed={self.w.people[0].id};m.pending=set(m.confirmed)
        m.trigger_global(50,'target_detected',self.w.people[0].sector)
        self.assertEqual(ai.client.calls,0)
        self.assertTrue(any(x['type']=='GLOBAL_SKIPPED' for x in m.audit))
    def test_hold_preserves_uncollected_and_carried_targets(self):
        class HoldAI:
            has_local=True
            has_global=False
            def local_decide(self,*args):
                return {'decision':'HOLD','candidate':None,'messages':[]},0.
        for carrying in (False,True):
            m=Mission(self.w,'global_local_ai',HoldAI())
            p=self.w.people[0]
            segment={'r':0,'t0':10.,'t1':12.,'a':[1,1],'b':[2,1],
                     'e':1.,'action':'to_base' if carrying else 'to_person'}
            m.ground_jobs[0]={'person':p.id,'segments':[segment],'index':0,
                'token':0,'carrying':carrying,'position':[1,1],
                'start':5.,'finish':50.,'local':False}
            m.rescue_segments=[segment]
            old_walkable=self.w.walkable
            try:
                self.w.walkable=lambda x,y,terrain=None:False if (x,y)==(2,1) else old_walkable(x,y,terrain)
                m.ground_advance(10,0,0)
            finally:
                self.w.walkable=old_walkable
            self.assertEqual(m.ground_jobs[0]['person'],p.id)
            self.assertTrue(m.ground_jobs[0]['stuck'])
            self.assertEqual(m.ground_jobs[0]['carrying'],carrying)
            self.assertNotIn(p.id,m.pending)
            self.assertEqual(m.audit[-1]['type'],'TASK_HELD')
    def test_reroute_never_drops_passenger(self):
        m=Mission(self.w,'base')
        p=self.w.people[0]
        seg={'r':0,'t0':30.,'t1':35.,'a':[1,1],'b':[2,1],
             'e':1.2,'action':'to_base'}
        self.assertTrue(m.dispatch_job(0,p,[seg],5,local=True,carrying=True))
        self.assertTrue(m.ground_jobs[0]['carrying'])
        self.assertEqual(m.ground_jobs[0]['person'],p.id)

if __name__=='__main__':unittest.main()
