"""Validate the private, time-ordered contest disturbances before Unreal starts."""
from __future__ import annotations

import math

from contracts.protocol import AGENT_KINDS, ProtocolError

FORMAT = 'metarescue.disturbances.v1'
PARAMETERS = {
    'agent_failure': {'reason'},
    'agent_degradation': {'speed_factor', 'sensor_factor'},
    'infrastructure_failure': {'reason'},
    'connectivity_loss': {'reason'},
    'mission_priority_change': {'priority'},
    'operator_directive': {'action', 'reason'},
    'restricted_zone_appeared': {'bounds', 'allowed_kinds'},
    'resource_shortage': {'remaining_wh'},
    'contradictory_information': {'position', 'confidence'},
}
TEMPORARY = {'agent_degradation', 'infrastructure_failure', 'connectivity_loss',
             'operator_directive', 'restricted_zone_appeared'}
ROWS = {'id', 'type', 'time', 'until', 'source', 'targets', 'parameters'}


def _number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def _point(value, bounds):
    return isinstance(value, list) and len(value) == 3 and all(
        _number(n, bounds['min'][axis], bounds['max'][axis]) for axis, n in enumerate(value))


def _identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 100 and not any(ord(c) < 32 for c in value)


def validate_tape(tape, world):
    def invalid(reason):
        raise ProtocolError('INVALID_REQUEST', 'Private contest disturbances: ' + reason)

    if (not isinstance(tape, dict) or set(tape) != {'format', 'events'} or tape['format'] != FORMAT
            or not isinstance(tape['events'], list) or len(tape['events']) > 256):
        invalid('format or event limit')
    agents = {a['id'] for a in world['spawns']}
    infrastructure = {n['id']: n['kind'] for n in world['infrastructure']}
    people = {'person-' + str(p['id']) for p in [*world['people'], *world.get('event_model', {}).get('late_people', ())]}
    horizon = world['settings']['horizon']
    bounds = world['bounds']
    previous = -1
    seen = set()
    for row in tape['events']:
        if not isinstance(row, dict) or set(row) != ROWS:
            invalid('invalid event row')
        ident, kind, time, until = (row[key] for key in ('id', 'type', 'time', 'until'))
        if (not _identifier(ident) or ident in seen or not _identifier(row['source'])
                or not isinstance(kind, str) or kind not in PARAMETERS or not _number(time, 0, horizon) or time < previous):
            invalid('identity, type or time order')
        if kind in TEMPORARY:
            if not _number(until, time, horizon) or until <= time:
                invalid(ident + ' requires a later end time')
        elif until is not None:
            invalid(ident + ' is a permanent change or one-time report')
        previous = time
        seen.add(ident)
        targets = row['targets']
        p = row['parameters']
        if (not isinstance(targets, list) or not all(_identifier(t) for t in targets)
                or len(set(targets)) != len(targets) or not isinstance(p, dict) or set(p) != PARAMETERS[kind]):
            invalid(ident + ' target/parameter shape')
        if kind == 'restricted_zone_appeared':
            box = p['bounds']; allowed = p['allowed_kinds']
            if (targets or not isinstance(box, dict) or set(box) != {'min', 'max'}
                    or not _point(box['min'], bounds) or not _point(box['max'], bounds)
                    or any(a >= b for a, b in zip(box['min'], box['max']))
                    or not isinstance(allowed, list) or not all(isinstance(a, str) and a in AGENT_KINDS for a in allowed)
                    or len(set(allowed)) != len(allowed)):
                invalid(ident + ' invalid restriction')
        elif kind == 'connectivity_loss':
            if not targets or not set(targets) <= agents or not _identifier(p['reason']):
                invalid(ident + ' invalid radio outage')
        elif len(targets) != 1:
            invalid(ident + ' requires one target')
        elif kind in ('agent_failure', 'agent_degradation', 'operator_directive') and targets[0] not in agents:
            invalid(ident + ' unknown agent')
        elif kind == 'agent_degradation' and not (_number(p['speed_factor'], .1, 1) and _number(p['sensor_factor'], 0, 1)):
            invalid(ident + ' invalid degradation factor')
        elif kind == 'operator_directive' and (p['action'] != 'hold' or not _identifier(p['reason'])):
            invalid(ident + ' unsupported directive')
        elif kind == 'agent_failure' and not _identifier(p['reason']):
            invalid(ident + ' invalid failure reason')
        elif kind == 'infrastructure_failure' and (targets[0] not in infrastructure or not _identifier(p['reason'])):
            invalid(ident + ' invalid infrastructure failure')
        elif kind == 'mission_priority_change' and (targets[0] not in people or type(p['priority']) is not int or not 1 <= p['priority'] <= 3):
            invalid(ident + ' invalid target priority')
        elif kind == 'resource_shortage' and (infrastructure.get(targets[0]) != 'charging_station'
                or world['settings']['resource_profile'] != 'contest' or not _number(p['remaining_wh'], 0, 1.e8)):
            invalid(ident + ' invalid energy shortage')
        elif kind == 'contradictory_information' and (targets[0] not in people or not _point(p['position'], bounds)
                or not _number(p['confidence'], 0, 1)):
            invalid(ident + ' invalid contradictory report')
    return tape
