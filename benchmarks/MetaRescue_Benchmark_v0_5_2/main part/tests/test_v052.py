"""v0.5.2: strategy choice, coalition assignment and safety invariants."""
from __future__ import annotations
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from strategy_engine import StrategyEngine, PROFILES, worthwhile
from patrol_scheduler import PatrolScheduler
from world import World,DEFAULT_PROBABILITIES
from mission_v05 import Mission
from rescue import prepare,mission_segments
from ai_v05 import AIOrchestrator

class StrategyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w=World(2026,18,'urban',35,4,6,{k:0 for k in DEFAULT_PROBABILITIES})

    def test_five_real_nsga2_candidates_and_three_forecasts(self):
        choices=StrategyEngine(self.w).propose(60,self.w.people[:8],list(range(6)),None)
        self.assertEqual({c['id'] for c in choices},set(PROFILES))
        for c in choices:
            self.assertEqual(len(c['continuations']),3)
            self.assertTrue(c['assignments'])
            self.assertIn('nominal_objectives',c)
            self.assertEqual(c['estimated_from'],'observed_targets_and_known_terrain_only')

    def test_forecast_will_not_admit_rescue_loss(self):
        base={'id':'balanced','forecast':{'saved':5.,'priority_saved':8.,'weighted_completion':100.,'energy_Wh':200.},
              'continuations':[{'saved':5,'priority_saved':8}]*3}
        reckless={'id':'energy_saver','forecast':{'saved':4.,'priority_saved':7.,'weighted_completion':80.,'energy_Wh':100.},
                  'continuations':[{'saved':4,'priority_saved':7}]*3}
        allowed,why=worthwhile(reckless,base)
        self.assertFalse(allowed);self.assertEqual(why,'EXPECTED_RESCUE_LOSS')
        efficient={'id':'energy_saver','forecast':{'saved':5.,'priority_saved':8.,'weighted_completion':102.,'energy_Wh':170.},
                   'continuations':[{'saved':5,'priority_saved':8}]*3}
        self.assertTrue(worthwhile(efficient,base)[0])

    def test_strategy_commits_real_policy_and_robot_assignments(self):
        m=Mission(self.w,'global_ai')
        m.patrol=PatrolScheduler(self.w,[list(range(49)),[],[],[]])
        m.patrol.unvisited.clear()
        pid=self.w.people[0].id
        m.pending={pid}
        candidate={'id':'energy_saver','scout_mode':'efficient',
                   'policy_weights':PROFILES['energy_saver'],
                   'assignments':[{'robot_id':'ground_01','target_id':pid}]}
        m.install_strategy(75,candidate)
        self.assertEqual(m.strategy_policy,'energy_saver')
        self.assertEqual(m.patrol.strategy,'efficient')
        self.assertEqual(m.strategic_assignments,{0:pid})
        self.assertEqual(m.strategy_commit_count,1)

    def test_busy_robot_may_be_reserved_for_next_job_without_interruption(self):
        m=Mission(self.w,'global_ai')
        m.patrol=PatrolScheduler(self.w,[list(range(49)),[],[],[]]);m.patrol.unvisited.clear()
        pid=self.w.people[0].id;m.pending={pid}
        m.ground_jobs[0]={'person':self.w.people[1].id,'carrying':True}
        candidate={'id':'urgent','scout_mode':'risk','policy_weights':{},
                   'assignments':[{'robot_id':'ground_01','target_id':pid}]}
        m.install_strategy(75,candidate)
        self.assertEqual(m.strategic_assignments.get(0),pid)
        self.assertTrue(m.ground_jobs[0]['carrying'])

    def test_motor_efficiency_is_in_route_and_actual_segments(self):
        victim=self.w.people[0]
        _,trips=prepare(self.w,[victim])
        for r in range(self.w.n_rescuers):
            tr=trips[r][0]
            if tr is None:continue
            segments,end=mission_segments(victim,r,tr,0)
            self.assertAlmostEqual(sum(seg['e'] for seg in segments),tr['energy'],places=2)
            self.assertAlmostEqual(tr['energy_factor'],self.w.ground_energy_factor(r),places=6)

    def test_invalid_llm_strategy_id_is_discarded(self):
        ai=AIOrchestrator('global_ai','mock',max_calls=5)
        ai.client.decide=lambda role,obs,audit,t,agent=None:({'operation':'modify','strategy_id':'fake_strategy',
                         'replan':{'scout':False,'rescue':True},'priority_ids':[]},0.)
        context={'strategy_candidates':[{'id':'balanced'}], 'known_targets':[]}
        decision,_=ai.global_decide(60,{'type':'strategic_review'},context,set(),set(),force=True)
        self.assertEqual(decision['strategy_id'],'balanced')
        self.assertTrue(any(e['type']=='GLOBAL_STRATEGY_REJECTED' for e in ai.audit))

    def test_packaged_empty_lowercase_secret_env(self):
        file=Path(__file__).resolve().parents[2]/'secret.env'
        self.assertEqual(file.read_text(encoding='utf-8').strip(),'API=')

if __name__=='__main__':unittest.main()
