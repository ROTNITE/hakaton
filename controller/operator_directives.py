"""Interpret the advertised operator extension using delivered Core data only."""
from __future__ import annotations

from copy import deepcopy
import math

FORMAT = 'metarescue.operator_directives.v1'


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


class OperatorDirectives:
    """Bounded feedback state; a submitted message is never a delivered ACK."""

    def __init__(self, capabilities):
        self.enabled = FORMAT in capabilities.get('extensions', ())
        self.episode = None
        self.checks = []
        self.feedback = {}
        self.fingerprint = None
        self.changed = False

    def prepare(self, observation):
        if self.episode != observation['episode_id']:
            self.episode = observation['episode_id']
            self.feedback.clear()
            self.fingerprint = None
        self.checks = []
        self.changed = False
        if not self.enabled:
            return observation
        now = observation['time']
        agents = {a['id']: a for a in observation['agents']}
        targets = {t['id']: t for t in observation['targets']}
        zones = {z.get('id'): z for z in observation.get('zones', ())}
        priorities = {}
        requirements = []
        valid_holds = set()
        for order in observation['mission'].get('directives', ()):
            if order.get('format') != FORMAT:
                continue
            ident, revision = order.get('id'), order.get('revision')
            issued, expires, updated = (order.get(k) for k in ('issued_at', 'expires_at', 'updated_at'))
            action, status = order.get('action'), order.get('status')
            row = {'directive_id': ident, 'revision': revision, 'source': order.get('source'),
                   'action': action, 'status': status, 'outcome': 'invalid_requirement',
                   'reason': order.get('reason'), 'confirmation_requested': order.get('confirmation_requested', False)}
            self.checks.append(row)
            if (not isinstance(ident, str) or not ident or type(revision) is not int or revision < 1 or
                    not all(_number(v) for v in (issued, expires, updated)) or not issued <= updated <= now < expires):
                row['outcome'] = 'stale_or_invalid_requirement'
                continue
            source = agents.get(order.get('source'))
            if source is None or source.get('kind') != 'operator':
                row['outcome'] = 'unverified_operator_source'
                continue
            requirements.append((ident, revision, status))
            if status in ('cancelled', 'expired'):
                row['outcome'] = status
            elif status == 'needs_clarification':
                row['outcome'] = 'request_clarification'
            elif status == 'pending_confirmation':
                row['outcome'] = 'request_confirmation'
            elif status != 'active':
                row['outcome'] = 'unsupported_requirement_state'
            elif action == 'hold':
                row['agent_id'] = order.get('agent_id')
                if row['agent_id'] in agents:
                    row['outcome'] = 'awaiting_safe_hold_check'
                    valid_holds.add(ident)
                else:
                    row['outcome'] = 'agent_unavailable'
            elif action == 'set_priority':
                target, priority = order.get('target_id'), order.get('priority')
                row['target_id'] = target
                if target not in targets or targets[target].get('evacuation_state') == 'evacuated':
                    row['outcome'] = 'target_unavailable'
                elif type(priority) is not int or not 1 <= priority <= 3:
                    row['outcome'] = 'invalid_priority'
                else:
                    priorities.setdefault(target, []).append(((updated, revision, ident), priority, row))
            elif action == 'restrict_zone':
                row['zone_id'] = order.get('zone_id')
                row['outcome'] = ('applied_restriction' if zones.get(order.get('zone_id'), {}).get('type') == 'restricted'
                                  else 'awaiting_published_restriction')
            else:
                row['outcome'] = 'unsupported_requirement_action'
        fingerprint = tuple(sorted(requirements))
        self.changed = self.fingerprint is not None and fingerprint != self.fingerprint
        self.fingerprint = fingerprint
        filtered_holds = [row for row in observation['mission'].get('directives', ()) if
                          row.get('format') == FORMAT and row.get('action') == 'hold' and
                          row.get('status') == 'active' and row.get('id') not in valid_holds]
        if not priorities and not filtered_holds:
            return observation
        projected = deepcopy(observation)
        projected['mission']['directives'] = [row for row in projected['mission'].get('directives', ()) if
            not (row.get('format') == FORMAT and row.get('action') == 'hold' and
                 row.get('status') == 'active' and row.get('id') not in valid_holds)]
        projected_targets = {t['id']: t for t in projected['targets']}
        for target, choices in priorities.items():
            choices.sort(key=lambda choice: choice[0])
            for _, _, row in choices[:-1]:
                row.update(outcome='superseded_priority', superseded_by=choices[-1][2]['directive_id'])
            _, priority, row = choices[-1]
            entry = projected_targets[target]
            row.update(outcome='applied_priority', base_priority=entry.get('priority'), priority=priority)
            entry.update(priority=priority / 3, operator_priority=priority / 3,
                         operator_directive_id=row['directive_id'])
        return projected

    def apply(self, observation, request):
        if not self.checks:
            return
        holds = {r.get('directive_id'): r for r in request.get('metaevolution', {}).get('directive_checks', ())}
        for row in self.checks:
            if row['outcome'] == 'awaiting_safe_hold_check':
                row['outcome'] = holds.get(row['directive_id'], {}).get('outcome', 'hold_not_scheduled')
        trace = {'requirements': deepcopy(self.checks),
                 'scenario_ids': list(request['selected_configuration']['scenario_ids']),
                 'feedback': []}
        request.setdefault('metaevolution', {})['operator_interpretation'] = trace
        request['explanation']['reason_codes'].append('delivered_operator_requirements_checked')
        now = observation['time']
        agents = {a['id']: a for a in observation['agents']}
        # Forgotten terminal requirements need no in-memory history; their ACKs
        # and interpretations remain in the immutable controller/native journal.
        visible = {(row['directive_id'], row['revision'], row['outcome']) for row in self.checks
                   if isinstance(row['directive_id'],str) and type(row['revision']) is int}
        self.feedback = {key: value for key, value in self.feedback.items() if key in visible}
        for row in self.checks:
            key = (row['directive_id'], row['revision'], row['outcome'])
            if not isinstance(key[0], str) or type(key[1]) is not int:
                continue
            previous = self.feedback.get(key)
            if previous:
                if previous['state'] == 'delivered':
                    continue
                if previous['attempts'] >= 3 or now < previous['sent_at'] + 35:
                    continue
            recipient = agents.get(row['source'])
            if recipient is None or recipient.get('kind') != 'operator':
                continue
            choices = [a for a in agents.values() if a['id'] != recipient['id'] and
                       a.get('status') not in ('failed', 'offline', 'unknown') and
                       a.get('communication', {}).get('reachable') is not False and
                       any(v.get('action') == 'send_message' for v in a.get('available_actions', ()))]
            if not choices:
                trace['feedback'].append({'directive_id': key[0], 'state': 'no_available_sender'})
                continue
            sender = min(choices, key=lambda a: (a['kind'] not in ('digital', 'infrastructure'), a['id']))
            index = len(request['commands'])
            request['commands'].append({'agent_id': sender['id'], 'action': 'send_message', 'parameters': {
                'recipient_id': recipient['id'], 'payload': {'format': FORMAT, 'directive_id': key[0],
                'revision': key[1], 'interpretation': row['outcome'], 'observed_at': now,
                'scenario_ids': trace['scenario_ids'], 'confirmation_reply': row['confirmation_requested']}}})
            self.feedback[key] = {'decision_id': request['decision_id'], 'command_index': index,
                                  'agent_id': sender['id'], 'sent_at': now,
                                  'attempts': 1 + (previous['attempts'] if previous else 0), 'state': 'submitted'}
            trace['feedback'].append({'directive_id': key[0], 'revision': key[1], 'command_index': index,
                                      'sender_id': sender['id'], 'state': 'submitted'})
            break

    def observe(self, response):
        for pending in self.feedback.values():
            if pending['state'] == 'delivered':
                continue
            result = next((r for r in response.get('command_results', ()) if
                           r.get('decision_id') == pending['decision_id'] and
                           r.get('command_index') == pending['command_index'] and
                           r.get('agent_id') == pending['agent_id']), None)
            if result and result.get('execution_status') == 'completed' and result.get('delivery_status') == 'delivered':
                pending['state'] = 'delivered'
