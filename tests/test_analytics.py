from copy import deepcopy
import gzip
import json
import math
import tempfile
from pathlib import Path
import unittest
import zlib

from analytics.metrics import hypervolume,igd_plus,nondominated,outcome_metrics,paired_interval
from analytics.store import RunStore,safe_path,signature
from tools.native_archive import ENTRY,file_sha256


class AnalyticsTests(unittest.TestCase):
    def test_pareto_box_union_and_minimization_igd_plus(self):
        points=[(1,3),(2,2),(3,1),(3,3),(1,3)]
        self.assertEqual(nondominated(points),[(1.,3.),(2.,2.),(3.,1.)])
        self.assertEqual(hypervolume(points,(4,4)),6)
        self.assertEqual(hypervolume([(1,2,1),(2,1,1)],(3,3,3)),6)
        self.assertEqual(igd_plus([(0,0)],[(1,1)]),0)
        self.assertAlmostEqual(igd_plus([(2,2)],[(1,1)]),math.sqrt(2))
        self.assertIsNone(igd_plus([],[(1,1)]))

    def test_bootstrap_uses_maps_as_independent_units(self):
        result=paired_interval([('one',3,1)]*9+[('two',0,4)],samples=500)
        self.assertEqual(result['maps'],2)
        self.assertEqual(result['pairs'],10)
        self.assertEqual(result['mean_difference'],-1)
        self.assertEqual(result,paired_interval([('one',3,1)]*9+[('two',0,4)],samples=500))

    def test_hidden_undiscovered_target_stays_in_the_denominator_after_the_run(self):
        def row(kind,payload,time=10):
            return {'record_type':kind,'time':time,'payload':payload}
        targets=[{'id':'known','priority':1,'rescued':True},{'id':'hidden','priority':3,'rescued':False}]
        truth=[row('truth_snapshot',{'targets':targets,'agents':[{'physical':{'consumed_wh':2,'distance_m':4}}]})]
        public=[row('target_detected',{'id':'known','observed_at':1}),
                row('target_state_changed',{'id':'known','observed_at':9,'evacuation_state':'evacuated'})]
        expected=deepcopy(targets)
        result=outcome_metrics(iter(truth),iter(public),iter(()))
        self.assertEqual(result['M1']['value'],.25)
        self.assertEqual(result['registered_targets'],2)
        self.assertEqual(result['found'],1)
        self.assertIsNone(result['found_90_s'])
        self.assertIsNone(result['official_total'])
        self.assertEqual(result['first_handover_s'],9)
        self.assertEqual(targets,expected)
        targets[0].pop('priority')
        self.assertIsNone(outcome_metrics(truth,public,[])['M1']['value'])

    def test_future_appearance_is_not_a_registered_goal_at_an_early_cutoff(self):
        targets=[{'id':'initial','priority':1,'rescued':True,'available_at':0},
                 {'id':'unborn','priority':3,'rescued':False,'available_at':20}]
        snapshot={'record_type':'truth_snapshot','time':10,'payload':{'targets':targets,'agents':[]}}
        result=outcome_metrics([snapshot],[],[])
        self.assertEqual(result['registered_targets'],1)
        self.assertEqual(result['not_yet_available_targets'],1)
        self.assertEqual(result['M1']['value'],1)
        snapshot['time']=20
        result=outcome_metrics([snapshot],[],[])
        self.assertEqual(result['registered_targets'],2)
        self.assertEqual(result['not_yet_available_targets'],0)
        self.assertEqual(result['M1']['value'],.25)

    def test_audit_joins_accepted_revision_observation_roles_and_execution(self):
        def row(kind, payload, time=2, trace_id=None):
            return {'record_type': kind, 'time': time, 'payload': payload, 'trace_id': trace_id}

        initial, chosen = {'scenario_ids': ['coverage_search']}, {'scenario_ids': ['safe_degradation']}
        truth = [row('contest_event_started', {'id': 'fault', 'type': 'agent_failure'}, 2, 'fault-trace'),
                 row('truth_snapshot', {'targets': [{'id': 'target', 'priority': 1, 'rescued': True}], 'agents': []}, 8)]
        public = [row('observation', {'request_id': 'observed', 'metaevolution': {'plan': {
                      'plan_revision': 1, 'accepted_configuration': initial}}}, 2),
                  row('decision', {'decision_id': 'accepted', 'request_id': 'step', 'operation': 'switch',
                      'selected_configuration': chosen, 'role_assignments': {'agent': 'safe_holder'},
                      'commands': [{'agent_id': 'agent'}], 'candidate_evaluations': [{'applicable': True}],
                      'constraint_checks': [{'status': 'passed'}],
                      'explanation': {'observation_refs': ['observed'], 'reason_codes': ['failover']}}),
                  row('observation', {'request_id': 'step', 'metaevolution': {'plan': {
                      'plan_revision': 2, 'accepted_configuration': chosen, 'agent_acknowledgements': {
                          'agent': {'plan_revision': 2, 'role': 'safe_holder', 'freshness': {'state': 'current'}}}}}}, 3),
                  row('command_result', {'decision_id': 'accepted', 'command_index': 0, 'command_id': 'accepted:0',
                      'validation_status': 'accepted', 'delivery_status': 'delivered', 'execution_status': 'completed'}, 3, 'command-trace'),
                  row('target_state_changed', {'id': 'target', 'observed_at': 7, 'evacuation_state': 'evacuated'}, 7)]
        rejected = deepcopy(public[1]); rejected['payload'].update(decision_id='rejected', request_id='error')
        public.append(rejected)
        result = outcome_metrics(truth, public, [])
        self.assertEqual(result['M2']['physical_disturbances'][0]['next_handover_delay_s'], 5)
        self.assertEqual(result['M4']['submitted_transitions'], {'switch': 2})
        self.assertEqual(result['M4']['accepted_transitions'], {'switch': 1})
        self.assertEqual(result['M6']['strictly_joined_transitions'], 1)
        self.assertEqual(result['M6']['transitions'][0]['command_outcomes'][0]['trace_id'], 'command-trace')
        self.assertIsNone(result['M6']['transitions'][1]['accepted_revision'])
        public[1]['payload']['explanation']['observation_refs'].append('unrecorded')
        self.assertEqual(outcome_metrics(truth, public, [])['M6']['strictly_joined_transitions'], 0)

    def test_evidence_paths_cannot_escape_the_configured_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'data';root.mkdir()
            allowed=root/'run.json';allowed.write_text('{}')
            outside=Path(directory)/'other.json';outside.write_text('{}')
            self.assertEqual(safe_path(root,allowed),allowed.resolve())
            with self.assertRaises(ValueError):safe_path(root,outside)

    def test_native_index_commits_closes_and_invalidates_after_source_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);native=root/'core-runs/episode';native.mkdir(parents=True)
            run_path=root/'missions/example';(run_path/'controller').mkdir(parents=True)
            record={'episode_id':'episode','record_type':'truth_snapshot','time':3,
                    'payload':{'targets':[],'agents':[]}}
            agent={'id':'test-agent','kind':'ground','position':[11,22,0],
                   'communication':{'quality':.2,'reachable':True},'freshness':{'position':{'observed_at':1}}}
            delivered={'episode_id':'episode','record_type':'observation','time':1,'payload':{'agents':[agent]}}
            truth_agent={**agent,'position':[51,22,0],'communication':{'quality':.9,'reachable':True}}
            telemetry={'episode_id':'episode','record_type':'agent_telemetry','time':3,'payload':{'agents':[truth_agent]}}
            manifest={'format':'metarescue.indexed-json.v1','episode_id':'episode',
                      'state':'complete','status':'success','time':3,'files':{}}
            for name,rows in (('truth',[record,telemetry]),('public',[delivered,{**delivered,'time':2}]),('replay',[])):
                encoded=[json.dumps(row).encode() for row in rows];data=b''.join(encoded);offset=0;entries=[]
                for row in encoded:
                    entries.append(ENTRY.pack(offset,len(row),len(row),zlib.crc32(row),0));offset+=len(row)
                (native/(name+'.records')).write_bytes(data);(native/(name+'.index')).write_bytes(b''.join(entries))
                manifest['files'][name]={'records':len(rows),'stored_bytes':len(data),
                    'uncompressed_bytes':len(data),'index_bytes':len(entries)*ENTRY.size}
            (native/'manifest.json').write_text(json.dumps(manifest))
            moved_native=root.parent/'old-location/core-runs/episode'
            (run_path/'manifest.json').write_text(json.dumps({'native_archive':str(moved_native),'state':'complete','episode_status':'success'}))
            journal=run_path/'controller/controller.jsonl.gz'
            with gzip.open(journal,'wt') as stream:
                stream.write(json.dumps({'record_type':'planning_trace','payload':{'type':'planning_result_committed',
                    'result':{'plan':{'stats':{'wall_ms':250}}}}})+'\n')
            (run_path/'controller/manifest.json').write_text(json.dumps({'journal_sha256':file_sha256(journal)}))
            store=RunStore(root)
            try:
                run=store.locate('mission-example');stamp=signature(run)
                cache=store.cache/run['id'];cache.mkdir()
                store._build(run,stamp,cache)
                report=store.ensure(run['id'])
                self.assertEqual(report['state'],'ready')
                self.assertEqual(report['summary']['metrics']['optimizer_wall_s']['p95'],.25)
                records=store.records(run['id'],stream='truth')
                self.assertEqual(records['records'][0]['record'],record)
                self.assertEqual(store.timeline(run['id'])['frames'][0]['agents'][0]['position'],[11,22,0])
                self.assertEqual(store.heatmap(run['id'])['cells'],[[1,2,1,1,1]])
                self.assertEqual(store.heatmap(run['id'],truth=True)['cells'],[[5,2,1,1,0]])
                self.assertFalse((cache/'records.sqlite.part').exists())
                # Windows cannot rename/delete the database while a handle remains open.
                renamed=cache/'checked.sqlite';(cache/'records.sqlite').replace(renamed);renamed.replace(cache/'records.sqlite')
                with self.assertRaises(ValueError):store.records(run['id'],after=float('nan'))
                with self.assertRaises(ValueError):store.records(run['id'],after=-1)
                replay=native/'replay.records'
                replay.write_bytes(b'corrupt')
                self.assertNotEqual(signature(run),stamp)
                with self.assertRaisesRegex(ValueError,'Manifest mismatch'):store._build(run,signature(run),cache)
                replay.write_bytes(b'')
                with (native/'truth.records').open('ab') as stream:stream.write(b'corrupt')
                self.assertNotEqual(signature(run),stamp)
                with self.assertRaisesRegex(ValueError,'Manifest mismatch'):store._build(run,signature(run),cache)
            finally:store.close()
