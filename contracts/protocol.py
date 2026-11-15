"""Public Core 1.0 values and validation; no environment state is imported here."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any

from jsonschema import Draft202012Validator

VERSION = '1.0'
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
TIME_EPSILON = 1e-9
OPERATIONS = ('keep', 'select', 'switch', 'modify', 'compose', 'synthesize', 'safe_stop')
AGENT_KINDS = ('aerial', 'ground', 'underground', 'surface_water', 'underwater',
               'infrastructure', 'digital', 'operator')
ZONE_KINDS = ('land', 'water', 'air', 'underground', 'obstacle', 'hazard',
              'restricted', 'low_connectivity', 'infrastructure')
EVENT_KINDS = ('agent_failure', 'agent_degradation', 'infrastructure_failure',
               'connectivity_loss', 'mission_priority_change', 'operator_directive',
               'hazard_appeared', 'restricted_zone_appeared', 'resource_shortage',
               'target_detected', 'target_state_changed', 'contradictory_information',
               'stale_information', 'environment_change')
ERROR_CODES = ('INVALID_REQUEST', 'UNSUPPORTED_PROTOCOL_VERSION', 'UNKNOWN_EPISODE',
               'INVALID_COMMAND', 'CONSTRAINT_VIOLATION', 'INVALID_SCENARIO',
               'RESOURCE_EXHAUSTED', 'TIMEOUT', 'INTERNAL_ERROR')


@dataclass
class ProtocolError(ValueError):
    code: str
    message: str
    details: dict | None = None

    def __str__(self):
        return f'{self.code}: {self.message}'

    def response(self, request_id=None, episode_id=None):
        return {'protocol_version': VERSION, 'request_id': request_id,
                'episode_id': episode_id,
                'error': {'code': self.code, 'message': self.message,
                          'details': self.details or {}}}


def _check_values(value, depth=0):
    if depth > 64:
        raise ProtocolError('INVALID_REQUEST', 'JSON nesting exceeds 64 levels')
    if type(value) in (int, float):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ProtocolError('INVALID_REQUEST', 'Non-finite or unrepresentable number')
    if isinstance(value, str):
        try:
            value.encode('utf-8')
        except UnicodeError as error:
            raise ProtocolError('INVALID_REQUEST', 'Invalid Unicode string') from error
    elif isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ProtocolError('INVALID_REQUEST', 'JSON object keys must be strings')
            _check_values(key, depth + 1)
            _check_values(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _check_values(child, depth + 1)


def strict_json(raw: str | bytes, *, maximum_bytes=MAX_BODY_BYTES) -> Any:
    """Reject duplicates/nonfinite values before interpreting a request."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ProtocolError('INVALID_REQUEST', 'Duplicate JSON key', {'key': key})
            result[key] = value
        return result

    def invalid_constant(_):
        raise ProtocolError('INVALID_REQUEST', 'Non-finite JSON number')

    try:
        data = raw.encode('utf-8') if isinstance(raw, str) else raw
        if len(data) > maximum_bytes:
            raise ProtocolError('INVALID_REQUEST', 'JSON exceeds the declared size limit', {'maximum_bytes': maximum_bytes})
        value = json.loads(data.decode('utf-8'), object_pairs_hook=pairs,
                           parse_constant=invalid_constant)
        _check_values(value)
        return value
    except ProtocolError:
        raise
    except (UnicodeError, ValueError, RecursionError, OverflowError) as error:
        raise ProtocolError('INVALID_REQUEST', 'Invalid UTF-8 JSON') from error


def encode(value) -> bytes:
    _check_values(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def object_schema(properties, required=None):
    return {'type': 'object', 'properties': properties,
            'required': list(properties) if required is None else required}


ID = {'type': 'string', 'minLength': 1}
NUMBER = {'type': 'number'}
NONNEGATIVE = {'type': 'number', 'minimum': 0}
UNIT = {'type': 'number', 'minimum': 0, 'maximum': 1}
STRINGS = {'type': 'array', 'items': ID}
OBJECTS = {'type': 'array', 'items': {'type': 'object'}}
POINT = {'type': 'array', 'items': NUMBER, 'minItems': 3, 'maxItems': 3}
RESOURCE = object_schema({'id': ID, 'value': UNIT, 'minimum': UNIT, 'maximum': UNIT,
                          'unit': {'const': 'normalized'}})
AGENT = object_schema({
    'id': ID, 'kind': {'enum': AGENT_KINDS},
    'position': {'anyOf': [POINT, {'type': 'null'}]},
    'status': {'enum': ['active', 'degraded', 'failed', 'offline', 'charging',
                        'busy', 'safe_mode', 'unknown']},
    'capabilities': STRINGS, 'resources': {'type': 'object', 'additionalProperties': RESOURCE},
    'communication': {'type': 'object'}, 'role': {'anyOf': [ID, {'type': 'null'}]},
    'scenario_ids': STRINGS, 'available_actions': {'type': 'array',
        'items': object_schema({'action': ID})}, 'constraints': OBJECTS})
MISSION = object_schema({'id': ID, 'objectives': OBJECTS, 'priorities': {'type': 'array'},
    'directives': OBJECTS, 'constraints': OBJECTS,
    'status': {'enum': ['active', 'completed', 'failed', 'suspended', 'safe_stopped']},
    'termination': {'type': 'object'}})
NETWORK = object_schema({'connectivity_score': UNIT,
    'partition_count': {'type': 'integer', 'minimum': 0}, 'reachable_agent_ratio': UNIT,
    'average_link_quality': UNIT, 'mesh_available': {'type': 'boolean'}, 'known_links': OBJECTS})
QUALITY = object_schema({'global_completeness': UNIT, 'maximum_delay': NONNEGATIVE,
    'stale_data_ratio': UNIT, 'contradiction_count': {'type': 'integer', 'minimum': 0},
    'unknown_state_ratio': UNIT})
INFRASTRUCTURE = object_schema({'id': ID,
    'kind': {'enum': ['relay', 'charging_station', 'sensor_node', 'base_station', 'compute_node']},
    'position': POINT, 'status': ID, 'capabilities': STRINGS,
    'resources': {'type': 'object', 'additionalProperties': RESOURCE},
    'communication': {'type': 'object'}, 'constraints': OBJECTS})
ZONE = object_schema({'id': ID, 'geometry': {'type': 'object'},
    'type': {'enum': ZONE_KINDS}, 'access': {'type': 'object'}, 'risk': UNIT,
    'cost': {'type': 'object'}, 'communication': {'type': 'object'}, 'constraints': OBJECTS})
EVENT = object_schema({'id': ID, 'type': ID, 'time': NONNEGATIVE, 'source': ID,
    'targets': STRINGS, 'parameters': {'type': 'object'}, 'confidence': UNIT,
    'status': {'enum': ['new', 'active', 'resolved', 'expired']}})
OBSERVATION = object_schema({'protocol_version': {'const': VERSION}, 'episode_id': ID,
    'request_id': ID, 'time': NONNEGATIVE, 'mission': MISSION,
    'agents': {'type': 'array', 'items': AGENT},
    'infrastructure': {'type': 'array', 'items': INFRASTRUCTURE},
    'targets': OBJECTS, 'zones': {'type': 'array', 'items': ZONE}, 'network': NETWORK,
    'events': {'type': 'array', 'items': EVENT},
    'constraints': OBJECTS, 'metrics': {'type': 'object'}, 'observation_quality': QUALITY})
CONFIGURATION = object_schema({'scenario_ids': STRINGS, 'parameters': {'type': 'object'},
    'synthesized_scenario': {'type': ['object', 'null']}})
DECISION = object_schema({'protocol_version': {'const': VERSION}, 'episode_id': ID,
    'decision_id': ID, 'request_id': ID, 'time': NONNEGATIVE,
    'operation': {'enum': OPERATIONS}, 'previous_configuration': object_schema({
        'scenario_ids': STRINGS, 'role_assignments': {'type': 'object'}}),
    'selected_configuration': CONFIGURATION, 'candidate_evaluations': OBJECTS,
    'role_assignments': {'type': 'object', 'additionalProperties': ID},
    'commands': {'type': 'array', 'maxItems': 256, 'items': object_schema({
        'agent_id': ID, 'action': ID, 'parameters': {'type': 'object'}})},
    'constraint_checks': OBJECTS, 'explanation': object_schema({
        'observation_refs': STRINGS, 'reason_codes': STRINGS,
        'expected_effects': {'type': 'array'}, 'confidence': UNIT})})
EPISODE_STATUS = {'enum': ['running', 'success', 'failed', 'safe_stopped', 'time_limit']}
RESET_RESPONSE = object_schema({'protocol_version': {'const': VERSION}, 'request_id': ID,
    'episode_id': ID, 'time': NONNEGATIVE, 'status': EPISODE_STATUS, 'observation': OBSERVATION})
STEP_RESPONSE = object_schema({**RESET_RESPONSE['properties'], 'command_results': OBJECTS,
    'events': {'type': 'array', 'items': EVENT}, 'metrics': {'type': 'object'}})


def validate(value, schema, code='INVALID_REQUEST'):
    _check_values(value)
    # Public schemas may contain local references, never trigger network reads.
    def check_refs(node):
        if isinstance(node, dict):
            if '$ref' in node and not node['$ref'].startswith('#'):
                raise ProtocolError(code, 'External JSON Schema references are not supported')
            for child in node.values():
                check_refs(child)
        elif isinstance(node, list):
            for child in node:
                check_refs(child)
    check_refs(schema)
    validator = Draft202012Validator(schema)
    error = next(validator.iter_errors(value), None)
    if error:
        raise ProtocolError(code, 'Schema validation failed',
                            {'path': list(error.absolute_path), 'rule': error.validator})
    return value


def validate_observation(observation):
    if isinstance(observation, dict) and observation.get('protocol_version', VERSION) != VERSION:
        raise ProtocolError('UNSUPPORTED_PROTOCOL_VERSION', 'Unsupported protocol version')
    validate(observation, OBSERVATION)
    for field in ('agents', 'targets', 'zones', 'infrastructure', 'events'):
        ids = [item.get('id') for item in observation[field]]
        if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
            raise ProtocolError('INVALID_REQUEST', f'Invalid or duplicate {field} IDs')
    for agent in observation['agents']:
        if agent['position'] is None and agent['kind'] not in ('digital', 'operator'):
            raise ProtocolError('INVALID_REQUEST', 'Spatial agent requires position', {'agent_id': agent['id']})
        for key, resource in agent['resources'].items():
            if key != resource['id'] or not resource['minimum'] <= resource['value'] <= resource['maximum']:
                raise ProtocolError('INVALID_REQUEST', 'Invalid resource bounds', {'agent_id': agent['id'], 'resource_id': key})
        for data in agent.get('freshness', {}).values():
            observed, received = data.get('observed_at'), data.get('received_at')
            for stamp in (observed, received):
                if stamp is not None and (type(stamp) not in (int, float) or stamp < 0):
                    raise ProtocolError('INVALID_REQUEST', 'Invalid freshness timestamp')
            if observed is not None and received is not None and not 0 <= observed <= received <= observation['time']:
                raise ProtocolError('INVALID_REQUEST', 'Freshness timestamps are not causal')
    return observation


def validate_episode_response(response, *, step=False):
    validate(response, STEP_RESPONSE if step else RESET_RESPONSE)
    observation = validate_observation(response['observation'])
    for key in ('episode_id', 'request_id'):
        if response[key] != observation[key]:
            raise ProtocolError('INVALID_REQUEST', f'Response and observation disagree on {key}')
    if abs(response['time'] - observation['time']) > TIME_EPSILON:
        raise ProtocolError('INVALID_REQUEST', 'Response and observation time differ')
    return response


def validate_decision(decision, observation, capabilities):
    if isinstance(decision, dict) and decision.get('protocol_version', VERSION) != VERSION:
        raise ProtocolError('UNSUPPORTED_PROTOCOL_VERSION', 'Unsupported protocol version')
    validate(decision, DECISION)
    if decision['episode_id'] != observation['episode_id']:
        raise ProtocolError('UNKNOWN_EPISODE', 'Episode does not match observation')
    if abs(decision['time'] - observation['time']) > TIME_EPSILON:
        raise ProtocolError('INVALID_REQUEST', 'Decision time is stale or in the future')
    agents = {agent['id']: agent for agent in observation['agents']}
    for agent_id in decision['role_assignments']:
        if agent_id not in agents:
            raise ProtocolError('INVALID_REQUEST', 'Unknown role participant', {'agent_id': agent_id})
    for command in decision['commands']:
        agent = agents.get(command['agent_id'])
        action = command['action']
        if agent is None or action not in {item['action'] for item in agent['available_actions']}:
            raise ProtocolError('INVALID_COMMAND', 'Action is unavailable', {'agent_id': command['agent_id'], 'action': action})
        descriptor = capabilities.get('supported_actions', {}).get(action)
        if descriptor is None or not set(descriptor.get('required_capabilities', [])) <= set(agent['capabilities']):
            raise ProtocolError('INVALID_COMMAND', 'Required capability is unavailable')
        validate(command['parameters'], descriptor['parameters_schema'], 'INVALID_COMMAND')
    grouped = set()
    for group in decision.get('metaevolution', {}).get('command_groups', []):
        indices = group.get('command_indices', [])
        if not indices:
            raise ProtocolError('INVALID_REQUEST', 'Empty command group')
        for index in indices:
            if type(index) is not int or not 0 <= index < len(decision['commands']) or index in grouped:
                raise ProtocolError('INVALID_REQUEST', 'Invalid or repeated command group index')
            grouped.add(index)
    return decision
