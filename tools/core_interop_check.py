"""Independent standard-library HTTP client for the mandatory Core wire profile."""
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import json
import math
from pathlib import Path
import time
from urllib.parse import urlencode
import uuid


FIELDS = ('protocol_version', 'episode_id', 'request_id', 'time', 'mission', 'agents',
          'infrastructure', 'targets', 'zones', 'network', 'events', 'constraints', 'metrics',
          'observation_quality')


def drive(port, seed):
    transcript = []

    def call(endpoint, body=None, query=None, expected=200):
        path = '/v1/environment/' + endpoint + ('?' + urlencode(query) if query else '')
        connection = HTTPConnection('127.0.0.1', port, timeout=90)
        try:
            connection.request('POST' if body is not None else 'GET', path,
                               body=json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode() if body is not None else None,
                               headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            data = json.loads(response.read())
            transcript.append({'path': path, 'status': response.status, 'request_id': data.get('request_id'),
                               'episode_id': data.get('episode_id'), 'time': data.get('time'),
                               'error': data.get('error')})
            assert response.status == expected, (path, response.status, data.get('error'))
            return data
        finally:
            connection.close()

    def public_observation(response):
        return {key: response[key] for key in FIELDS}

    def state_from(response):
        return public_observation(response['observation'])

    def new_reset(value, parameters=None):
        return {'protocol_version': '1.0', 'request_id': uuid.uuid4().hex, 'seed': value,
                'mission': {'id': 'search_and_rescue', 'parameters': parameters or {}}}

    def geometry_signature(observation):
        return {'agents': sorted((a['id'], a['kind'], a['position']) for a in observation['agents']),
                'zones': sorted((z['id'], z['type'], z['geometry']) for z in observation['zones']),
                'infrastructure': sorted((x['id'], x['kind'], x['position']) for x in observation['infrastructure'])}

    def compare_geometry(left, right):
        assert left['zones'] == right['zones'] and left['infrastructure'] == right['infrastructure']
        assert [a[:2] for a in left['agents']] == [a[:2] for a in right['agents']]
        max_drift = max((math.dist(a[2], b[2]) for a, b in zip(left['agents'], right['agents'])
                         if a[2] is not None and b[2] is not None), default=0.)
        assert max_drift <= .001, max_drift
        return max_drift

    assert call('health')['status'] == 'ready'
    caps = call('capabilities')
    assert caps['protocol_version'] == '1.0' and not caps['reset_parameters']['startup_configuration_only']
    assert {'keep', 'select', 'switch'} <= set(caps['supported_operations'])
    first_reset = new_reset(seed)
    first = call('reset', first_reset)
    observation = state_from(first)
    original = geometry_signature(observation)
    assert {'air', 'land', 'obstacle'} <= {zone['type'] for zone in observation['zones']}
    assert observation['time'] == first['time'] == 0 and observation['episode_id'] == first['episode_id']
    by_kind = {a['kind']: a for a in reversed(observation['agents'])}
    scout, carrier = by_kind['aerial'], by_kind['ground']
    assert {scout['id'], carrier['id']} == {'θ/7', 'p#49'}
    old_roles = {}
    current = {'scenario_ids': [], 'parameters': {}, 'synthesized_scenario': None}

    def decision(operation='keep', scenario=None, roles=None, commands=()):
        configuration = current if scenario is None else {'scenario_ids': [scenario], 'parameters': {},
                                                            'synthesized_scenario': None}
        return {'protocol_version': '1.0', 'episode_id': observation['episode_id'],
                'request_id': uuid.uuid4().hex, 'decision_id': uuid.uuid4().hex, 'time': observation['time'],
                'operation': operation,
                'previous_configuration': {'scenario_ids': current['scenario_ids'], 'role_assignments': old_roles},
                'selected_configuration': configuration, 'role_assignments': old_roles if roles is None else roles,
                'commands': list(commands), 'constraint_checks': [], 'candidate_evaluations': [],
                'explanation': {'observation_refs': [observation['request_id']], 'reason_codes': ['core_1_0_reference_client'],
                                'expected_effects': [], 'confidence': 1.}}

    def accept(request, response):
        nonlocal observation, current, old_roles
        observation = state_from(response)
        current = request['selected_configuration']
        old_roles = request['role_assignments']

    goal = [*scout['position'][:2], scout['position'][2]+8]
    move = {'agent_id': scout['id'], 'action': 'move', 'parameters': {'target': goal}}
    select = decision('select', 'coverage_search', {scout['id']: 'scout', carrier['id']: 'rescuer'}, [move])
    accept(select, call('step', select))
    keep = decision()
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(call, 'step', keep)
        b = pool.submit(call, 'step', keep)
        accepted = a.result()
        assert accepted == b.result() and accepted['time'] == 2
    accept(keep, accepted)
    for _ in range(5):
        keep = decision()
        accept(keep, call('step', keep))
    height = next(a['position'][2] for a in observation['agents'] if a['id'] == scout['id'])
    assert height > scout['position'][2]+4
    switch = decision('switch', 'coordination_reconfiguration', {carrier['id']: 'rescuer'})
    accept(switch, call('step', switch))
    stale = decision()
    stale['time'] -= 1
    assert call('step', stale, expected=400)['error']['code'] == 'INVALID_REQUEST'
    invalid = decision(commands=[move, move])
    assert call('step', invalid, expected=422)['error']['code'] == 'INVALID_COMMAND'
    conflict = {**keep, 'request_id': uuid.uuid4().hex}
    assert call('step', conflict, expected=400)['error']['code'] == 'INVALID_REQUEST'
    public = public_observation(call('observation', query={'episode_id': first['episode_id']}))
    assert public['time'] == observation['time']
    assert call('logs', query={'episode_id': first['episode_id'], 'cursor': 0})['records']
    assert call('reset', first_reset) == first
    invalid_reset = new_reset(seed+1, {'arbitrary_file': 'invalid'})
    assert call('reset', invalid_reset, expected=400)['error']['code'] == 'INVALID_REQUEST'
    assert call('observation')['time'] == observation['time']

    parameters = {'preset': 'open', 'people': 3, 'scouts': 2, 'rescuers': 1, 'horizon': 120}
    next_reset = new_reset(seed+1, parameters)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(call, 'reset', next_reset) for _ in range(2)]
        changed = tasks[0].result()
        assert changed == tasks[1].result()
    changed_s = time.monotonic()-started
    changed_state = state_from(changed)
    assert changed['episode_id'] != first['episode_id'] and changed_state['time'] == 0
    assert sum(a['kind'] == 'aerial' for a in changed_state['agents']) == 2
    assert changed_state['mission']['termination']['horizon'] == 120
    assert geometry_signature(changed_state) != original
    assert call('capabilities')['reset_parameters']['seed'] == seed+1
    assert call('observation', query={'episode_id': first['episode_id']}, expected=404)['error']['code'] == 'UNKNOWN_EPISODE'
    assert call('reset', first_reset, expected=400)['error']['code'] == 'INVALID_REQUEST'

    regenerated = call('reset', new_reset(seed+1, parameters))
    assert regenerated['episode_id'] != changed['episode_id']
    regenerated_drift = compare_geometry(geometry_signature(state_from(regenerated)), geometry_signature(changed_state))
    restored = call('reset', new_reset(seed))
    startup_drift = compare_geometry(geometry_signature(state_from(restored)), original)
    close = {'protocol_version': '1.0', 'request_id': uuid.uuid4().hex, 'episode_id': restored['episode_id']}
    closed = call('close', close)
    assert closed['closed'] and closed['time'] == 0
    assert call('close', close) == closed
    assert call('observation')['time'] == 0
    return {'passed': True, 'episode_ids': [r['episode_id'] for r in (first, changed, regenerated, restored)],
            'start_seed': seed, 'changed_seed': seed+1, 'changes': parameters, 'changed_reset_wall_s': changed_s,
            'same_seed_pose_tolerance_m': .001, 'regenerated_max_pose_drift_m': regenerated_drift,
            'restored_max_pose_drift_m': startup_drift,
            'opaque_agents': [scout['id'], carrier['id']], 'physical_climb_m': height-scout['position'][2],
            'checks': ['public_only_select_keep_switch', 'exact_concurrent_step', 'invalid_stale_and_conflicting_step',
                       'readonly_observation_and_logs', 'invalid_reset_leaves_world_intact', 'exact_concurrent_dynamic_reset',
                       'seed_and_parameter_change', 'same_seed_and_parameters_reproduce_geometry',
                       'return_to_authored_startup_layout', 'idempotent_close'],
            'public_http': transcript}


def verify(result, root):
    manifests = [json.loads((Path(root)/'core-runs'/eid/'manifest.json').read_bytes()) for eid in result['episode_ids']]
    assert [m['world_seed'] for m in manifests] == [result['start_seed'], result['changed_seed'],
                                                  result['changed_seed'], result['start_seed']]
    assert all(m['state'] == 'complete' for m in manifests)
    left, right = (Path(manifests[i]['generated_layout']) for i in (1, 2))
    assert left != right
    generated = [json.loads(p.with_name('result.json').read_bytes()) for p in (left, right)]
    assert generated[0]['sha256'] == generated[1]['sha256'] and left.read_bytes() == right.read_bytes()
    assert manifests[0]['generated_layout'] is None and manifests[-1]['generated_layout'] is None
    result['regenerated_private_layout_sha256'] = generated[0]['sha256']
    result['regenerated_private_layouts'] = [str(left), str(right)]
