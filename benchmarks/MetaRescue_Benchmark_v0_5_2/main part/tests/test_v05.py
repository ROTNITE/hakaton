"""v0.5 behavioral regression tests for causal knowledge, perpetual patrol and explicit start."""
import unittest,sys,os,json,urllib.request,urllib.error,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from world import World,DEFAULT_PROBABILITIES
from observation_engine import Knowledge
from patrol_scheduler import PatrolScheduler
from message_bus import MessageBus
from ai_v05 import AIOrchestrator
from mission_v05 import run_mission_v05
from server import params,ThreadingHTTPServer,Handler
from run_manager import RUN_MANAGER
from log_export import log_chunks

class V05Tests(unittest.TestCase):
    def setUp(self):
        self.w=World(2026,8,'urban',25,3,4,{k:70 for k in DEFAULT_PROBABILITIES})
    def test_hidden_hazard_not_available_before_sensor(self):
        knowledge=Knowledge(self.w)
        self.assertFalse(knowledge.hazard_summary())
        if self.w.landscape_events:
            e=next(e for e in self.w.landscape_events if e['type'] not in ('smoke','smoke_clear'))
            sec=(e['cells'][0][1]//5)*self.w.sector_count+e['cells'][0][0]//5
            self.assertTrue(any(any(kind for x,y,kind,smoke in knowledge.sense_sector(sec,e['t']+.01,'drone_01')['cells'])
                                for _ in [0]))
            self.assertFalse(knowledge.hazard_summary())
    def test_delivered_update_not_instant(self):
        k=Knowledge(self.w)
        obs=k.sense_sector(0,1,'drone_01')
        self.assertEqual(k.last_seen,{})
        k.merge_delivered(obs,1.35)
        self.assertEqual(k.last_seen[0],1.)
        self.assertEqual(k.changes[0]['t'],1.35)
    def test_message_delay_and_loss(self):
        schedule=[];bus=MessageBus(123,loss_rate=0,latency=.35)
        bus.send(10,'drone_01','global','TARGET_DETECTED',{'sector':4},lambda *x:schedule.append(x))
        self.assertEqual(schedule[0][0],10.35)
        self.assertEqual(bus.messages[0]['delivery_status'],'queued')
        bus.delivered(bus.messages[0],10.35)
        self.assertEqual(bus.messages[0]['delivery_status'],'delivered')
    def test_unlimited_energy_and_patrol_continues(self):
        result=run_mission_v05(self.w,'base')
        self.assertGreater(result['final']['scans'],self.w.sector_count**2)
        self.assertGreater(result['final']['energy'],0)
        self.assertTrue(result['opt']['scout_replans']>=1)
        self.assertTrue(all(e['t']<=self.w.horizon for e in result['rescues']))
    def test_nsga2_rescue_does_not_restrict_battery(self):
        from rescue import eval_plan
        from world import Person
        p=Person(1,7,8,2,0)
        tr={'energy':1e6,'duration':20}
        obj,tasks=eval_plan(([0],[0]),[p],[[tr]],now=0,available=[0],energy=[0],
                            battery_cap=1,horizon=400)
        self.assertEqual(obj[0],0.)
        self.assertEqual(len(tasks[0]),1)
    def test_run_is_deterministic_without_llm(self):
        a=run_mission_v05(self.w,'base')
        b=run_mission_v05(World(2026,8,'urban',25,3,4,{k:70 for k in DEFAULT_PROBABILITIES}),'base')
        self.assertEqual(a['final'],b['final'])
        self.assertEqual(a['discoveries'],b['discoveries'])
    def test_local_and_global_act_on_observed_events(self):
        w=World(2026,12,'urban',25,3,4,{k:100 for k in DEFAULT_PROBABILITIES})
        ai=AIOrchestrator('global_local_ai','mock',max_calls=100)
        result=run_mission_v05(w,'global_local_ai',ai)
        self.assertGreater(result['ai_stats']['global_actions'],0)
        self.assertGreater(result['ai_stats']['local_actions'],0)
        self.assertGreater(result['opt']['scout_replans'],3)
        self.assertGreater(sum(e['type']=='GLOBAL_SCOUT_REPLAN' for e in result['audit']),0)
    def test_no_known_hazard_before_truth_event(self):
        w=World(2026,8,'urban',25,3,4,{k:100 for k in DEFAULT_PROBABILITIES})
        out=run_mission_v05(w,'base')
        for item in out['knowledge_events']:
            for x,y,kind,smoke in item['cells']:
                if kind:
                    self.assertTrue(any(e['t']<=item['observed_at']+1e-7 and
                                        [x,y] in e.get('cells',[]) and e['type']==kind
                                        for e in w.landscape_events))
    def test_api_budget_fourfold(self):
        self.assertEqual(params({})[9],240)
        self.assertEqual(params({'ai_calls':['1600']})[9],1600)
        with self.assertRaises(ValueError):params({'ai_calls':['1601']})
    def test_no_background_simulation_before_post(self):
        before=len(RUN_MANAGER.jobs)
        srv=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
        url=f'http://127.0.0.1:{srv.server_port}'
        try:
            urllib.request.urlopen(url+'/').read()
            urllib.request.urlopen(url+'/api/health').read()
            self.assertEqual(len(RUN_MANAGER.jobs),before)
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(url+'/api/simulation').read()
            self.assertEqual(ctx.exception.code,405)
            self.assertEqual(len(RUN_MANAGER.jobs),before)
        finally:srv.shutdown();srv.server_close()
    def test_audit_contains_team_map_per_second(self):
        out=run_mission_v05(self.w,'base')
        from server import run_collection
        # Stream a single run to validate structure without duplicating expensive optimizations.
        sc=self.w.public_map()
        data={'scenario':sc,'runs':[out], 'ai_mode':'off',
              '_truth_people':[{'id':p.id,'x':p.x,'y':p.y,'priority':p.priority,
                   'appearance_t':self.w._appear_time.get(p.id,0)} for p in self.w.people]}
        count_team=count_truth=0
        for chunk in log_chunks(data):
            count_team+=chunk.count(b'TEAM_KNOWN_MAP_BEGIN')
            count_truth+=chunk.count(b'TRUTH_MAP_BEGIN')
        self.assertEqual(count_truth,self.w.horizon+1)
        self.assertEqual(count_team,self.w.horizon+1)

if __name__=='__main__':unittest.main()
