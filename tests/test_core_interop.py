"""Run the actual controller CLI against a base Core HTTP reference peer."""
from copy import deepcopy
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from contracts.protocol import ProtocolError, validate, validate_decision


ROOT = Path(__file__).resolve().parents[1]


def agent(identifier, kind, position, actions, capabilities):
    return {'id': identifier, 'kind': kind, 'position': position, 'status': 'active',
            'capabilities': capabilities, 'available_actions': [{'action': a} for a in actions],
            'resources': {'energy': {'id': 'energy', 'minimum': 0, 'maximum': 1, 'value': .9,
                                     'unit': 'normalized'}}, 'communication': {'reachable': True},
            'role': None, 'scenario_ids': [], 'constraints': []}


def zone(identifier, kind, low, high):
    return {'id': identifier, 'type': kind, 'geometry': {'type': 'box', 'min': low, 'max': high},
            'risk': 0, 'access': {}, 'cost': {}, 'communication': {}, 'constraints': []}


class ReferenceEpisode:
    def __init__(self, contract, altered, optional):
        cap = contract['capabilities']
        self.seed = 48319 if altered else 701
        self.scout, self.carrier, self.relay, self.target = (
            ('no/role:λ', 'unit/%§', 'a:β/unused', 'target?#仮') if altered else
            ('θ/7', 'p#49', 'r:xyz', '5/?'))
        self.issued_observations = set()
        x, y, width = (-16, 27, 54) if altered else (0, 0, 50)
        self.target_position = [x+10, y+10, 0]
        zone_ids = ('new|δ', 'ζ/2', 'unrelated:γ') if altered else ('space|a', 'space|g', 'wall#1')
        infrastructure_ids = ('ref:relay', 'ref:charge', 'ref:sensor', 'ref:base')
        if altered:
            infrastructure_ids = ('α/19', 'b#37', 'δ/12', 'k:67')
        self.capabilities = {'protocol_version': '1.0', 'environment_id': 'reference_peer',
                             'agent_kinds': ['aerial', 'ground', 'infrastructure'],
                             'supported_actions': {a: cap['supported_actions'][a] for a in
                                                   ('move', 'observe', 'inspect', 'deliver', 'hold')},
                             'supported_scenarios': {s: cap['supported_scenarios'][s] for s in
                                                     ('coverage_search', 'priority_response')}}
        self.capabilities['extensions'] = ['metarescue.radio_transport.v1']
        base = contract['reset_response']['observation']
        self.state = {key: deepcopy(base[key]) for key in (
            'protocol_version', 'episode_id', 'request_id', 'time', 'mission', 'agents',
            'infrastructure', 'targets', 'zones', 'network', 'events', 'constraints', 'metrics',
            'observation_quality')}
        self.state.update(episode_id='foreign:β/37' if altered else 'opaque:019/β',
                          time=0, targets=[], events=[], metrics={},
                          infrastructure=[{'id':identifier,'kind':kind,'position':[x+i,y,0],'status':'active',
                                           'capabilities':[],'resources':{},'communication':{},'constraints':[]}
                                          for i,(identifier,kind) in enumerate(zip(infrastructure_ids,
                                              ('relay','charging_station','sensor_node','base_station')))],
                          agents=[agent(self.scout,'aerial',[x+3,y+3,7 if altered else 8],
                                        ['move','observe','hold'],['move','sense']),
                                  agent(self.carrier,'ground',[x+4,y+2,0],['move','deliver','hold'],['move','deliver']),
                                  agent(self.relay,'infrastructure',[x,y,0],[],['relay'])],
                          zones=[zone(zone_ids[0],'air',[x,y,1],[x+width,y+width,17 if altered else 15]),
                                 zone(zone_ids[1],'land',[x,y,0],[x+width,y+width,0]),
                                 zone(zone_ids[2],'obstacle',[x+1,y+20,0],[x+3,y+30,16])])
        if altered:
            self.state['agents'].append(agent('extra/opaque','digital',None,[],[]))
            for key in ('agents','zones','infrastructure'):
                self.state[key].reverse()
        if optional=='unadvertised_map':
            self.state['metaevolution']={'announced_map':{'unknown_geometry':'must not affect decisions'}}
        elif optional=='scalar':
            self.state['metaevolution']=True
        self.state['mission'].update(objectives=[], termination={'horizon': 60})
        self.plan = {'scenario_ids': [], 'role_assignments': {}}
        self.cache = {}
        self.operations = []
        self.actions = []
        self.attempted = []
        self.simulate_faults = altered
        self.dropped = False
        self.rejected = False
        self.closed = False

    def observation(self, request_id):
        self.issued_observations.add(request_id)
        return {**deepcopy(self.state), 'request_id': request_id}

    def response(self, request_id):
        observation = self.observation(request_id)
        return {'protocol_version': '1.0', 'request_id': request_id, 'episode_id': observation['episode_id'],
                'time': observation['time'], 'observation': observation,
                'status': 'success' if self.state['mission']['status'] == 'completed' else 'running'}

    def step(self, raw, request):
        identifier = request['decision_id']
        self.attempted.append((identifier, raw))
        if identifier in self.cache:
            original, response = self.cache[identifier]
            assert original == raw
            return response
        validate_decision(request, self.state, self.capabilities)
        assert 'metaevolution' not in request and request['previous_configuration'] == self.plan
        explanation=request['explanation']
        assert explanation['observation_refs'] and set(explanation['observation_refs'])<=self.issued_observations
        assert explanation['reason_codes']
        selected = request['selected_configuration']
        ids = selected['scenario_ids']
        for scenario in ids:
            descriptor = self.capabilities['supported_scenarios'][scenario]
            validate(selected['parameters'], descriptor['parameters_schema'], 'INVALID_SCENARIO')
        if self.simulate_faults and not self.rejected and request['commands']:
            self.rejected = True
            raise ProtocolError('INVALID_COMMAND', 'Reference peer rejected the first proposed move')
        self.plan = {'scenario_ids': ids, 'role_assignments': request['role_assignments']}
        self.operations.append((request['operation'], list(ids), dict(request['role_assignments'])))
        self.state['time'] += 1
        agents = {a['id']: a for a in self.state['agents']}
        results = []
        for index, cmd in enumerate(request['commands']):
            who, action, params = cmd['agent_id'], cmd['action'], cmd['parameters']
            self.actions.append((who, action, params))
            a = agents[who]
            if action == 'move':
                a['position'] = params['target']
            if (action == 'observe' and not self.state['targets'] and
                    math.dist(a['position'],self.target_position)<=params['radius']):
                self.state['targets']=[{'id':self.target,'status':'confirmed','kind':'person',
                                        'confidence':1.,'position':self.target_position}]
                self.state['mission']['objectives']=[
                    {'id':'goal/foreign' if self.simulate_faults else 'obj/λ','type':'deliver','status':'active',
                     'priority':1.,'target_id':self.target,'required_capabilities':['deliver'],
                     'success_conditions':{'resource_id':'kit#1','amount_at_least':1}}]
                self.state['events']=[{'id':'detected/φ','type':'target_detected','time':self.state['time'],
                                      'source':who,'targets':[self.target],'parameters':{'message_id':'report/φ'},
                                      'received_at':self.state['time'],
                                      'confidence':1.,'status':'new'}]
                if self.simulate_faults:
                    self.state['events'].insert(0,{'id':'world/changed','type':'environment_change',
                        'time':self.state['time'],'source':self.state['infrastructure'][0]['id'],
                        'targets':[self.state['zones'][0]['id']],'parameters':{},'confidence':1.,'status':'active'})
            if action == 'deliver':
                assert a['position']==self.target_position and who==self.carrier
                assert params=={'target_id':self.target,'resource_id':'kit#1','amount':1}
                self.state['mission']['objectives'][0]['status'] = 'completed'
                self.state['mission']['status'] = 'completed'
                self.state['metrics']['actual_delivery_count'] = 1
            results.append({'decision_id': identifier, 'command_index': index, 'agent_id': who,
                            'action': action, 'validation_status': 'accepted', 'delivery_status': 'delivered',
                            'execution_status': 'completed', 'reason_code': None, 'updated_at': self.state['time']})
        assert self.state['time'] <= self.state['mission']['termination']['horizon']
        response = {**self.response(request['request_id']), 'command_results': results, 'events': [],
                    'metrics': self.state['metrics'].copy()}
        self.cache[identifier] = (raw, response)
        if self.simulate_faults and not self.dropped:
            self.dropped = True
            return None
        return response


class CoreInteroperability(unittest.TestCase):
    def test_controller_completes_a_foreign_public_episode(self):
        contract = json.loads((ROOT/'contracts/examples/interaction-v1.json').read_text(encoding='utf-8'))
        variants=((False,None,True),(True,'unadvertised_map',False),(True,'scalar',True))
        for altered,optional,contest in variants:
            with self.subTest(altered=altered,optional=optional,contest=contest), tempfile.TemporaryDirectory() as temp:
                episode = ReferenceEpisode(contract, altered, optional)
                handler_errors = []

                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, *args):
                        pass

                    def send_json(self, value, status=200):
                        wire = json.dumps(value, ensure_ascii=False).encode()
                        self.send_response(status)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Content-Length', str(len(wire)))
                        self.end_headers()
                        self.wfile.write(wire)

                    def do_GET(self):
                        url = urlsplit(self.path)
                        if url.path == '/v1/environment/capabilities':
                            self.send_json(episode.capabilities)
                        elif url.path == '/v1/environment/observation':
                            self.send_json(episode.observation(parse_qs(url.query)['request_id'][0]))
                        else:
                            self.send_error(404)

                    def do_POST(self):
                        raw = self.rfile.read(int(self.headers['Content-Length']))
                        request = json.loads(raw)
                        try:
                            if self.path == '/v1/environment/reset':
                                assert request['seed'] == episode.seed and request['mission']['id'] == 'search_and_rescue'
                                self.send_json(episode.response(request['request_id']))
                            elif self.path == '/v1/environment/step':
                                response = episode.step(raw, request)
                                if response is None:
                                    self.connection.shutdown(socket.SHUT_RDWR)
                                    self.close_connection = True
                                    return
                                self.send_json(response)
                            elif self.path == '/v1/environment/close':
                                assert request['episode_id'] == episode.state['episode_id']
                                episode.closed = True
                                self.send_json({'protocol_version': '1.0', 'request_id': request['request_id'],
                                                'episode_id': request['episode_id'], 'status': 'success',
                                                'time': episode.state['time'], 'closed': True})
                            else:
                                self.send_error(404)
                        except ProtocolError as error:
                            self.send_json({'protocol_version': '1.0', 'request_id': request['request_id'],
                                            'error': {'code': error.code, 'message': error.message}}, status=422)
                        except Exception as error:
                            handler_errors.append(error)
                            self.send_error(500)

                with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    path = Path(temp)
                    try:
                        result = subprocess.run(
                            [sys.executable, '-B', '-X', 'utf8', '-m', 'controller.main', '--environment',
                             f'http://127.0.0.1:{server.server_port}','--health-port','0','--seed',str(episode.seed),
                             *(['--contest-coordination'] if contest else []),
                             '--output',str(path/'run'),'--ai-budget',str(path/'budget.json')],
                            cwd=ROOT, capture_output=True, encoding='utf-8', timeout=40)
                    finally:
                        server.shutdown()
                        thread.join(timeout=5)
                self.assertFalse(handler_errors, handler_errors)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(episode.closed)
                self.assertEqual(sum(a[1] == 'deliver' for a in episode.actions), 1)
                self.assertIn(('select',['coverage_search'],{episode.scout:'scout',episode.relay:'relay'}),episode.operations)
                self.assertIn(('switch',['priority_response'],{episode.carrier:'executor',episode.relay:'relay'}),episode.operations)
                manifest = json.loads((path/'run/manifest.json').read_bytes())
                self.assertEqual((manifest['policy_profile'], manifest['episode_status']), ('core_1_0', 'success'))
                self.assertEqual(manifest['metrics'], {'actual_delivery_count': 1})
                with gzip.open(path/'run/controller.jsonl.gz','rt',encoding='utf-8') as journal:
                    records=[json.loads(line) for line in journal]
                self.assertEqual(len(records),manifest['records'])
                decisions=[row['payload']['decision'] for row in records if row['record_type']=='decision']
                self.assertEqual([d['decision_id'] for d in decisions],list(dict.fromkeys(i for i,_ in episode.attempted)))
                self.assertTrue(all(d['explanation']['observation_refs'] for d in decisions))
                event_types={event['type'] for row in records if row['record_type']=='step_response'
                             for event in row['payload']['observation']['events']}
                self.assertIn('target_detected',event_types)
                communication=[row['payload'] for row in records if row['record_type']=='agent_communication']
                self.assertEqual(len(communication),1)
                self.assertEqual((communication[0]['sender'],communication[0]['signal'],communication[0]['message_id']),
                                 (episode.scout,'TARGET_DETECTED','report/φ'))
                if altered:
                    self.assertIn('environment_change',event_types)
                    self.assertTrue(episode.dropped and episode.rejected)
                    self.assertEqual(episode.attempted[1],episode.attempted[2])
                    self.assertEqual(sum(row['record_type']=='environment_rejection' for row in records),1)


if __name__ == '__main__':
    unittest.main()
