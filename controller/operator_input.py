"""Local operator requests enter the normal Core command/delivery path."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from contracts.protocol import ProtocolError, strict_json, validate
from controller.operator_directives import FORMAT

INPUT_FORMAT = 'metarescue.operator_input.v1'


def validate_public_parameters(parameters, observation, operator_id):
    """Reject impossible local input before it can invalidate a whole Step."""
    def reject(reason):
        raise ValueError(reason)
    def text(value, limit):
        return (isinstance(value,str) and 0<len(value.encode('utf-16-le'))//2<=limit and
                all(ord(c)>=32 for c in value))
    if not text(parameters.get('reason'),128):reject('Operator reason is empty, too long or contains control characters')
    action=parameters['action']
    if action in ('cancel','clarify','confirm','request_confirmation'):
        ref=next((row for row in observation['mission'].get('directives',()) if row.get('id')==parameters.get('directive_id')),None)
        if not ref or ref.get('format')!=FORMAT or ref.get('source')!=operator_id:
            reject('Unknown or foreign operator requirement')
        if (ref.get('revision')!=parameters.get('expected_revision') or
                ref.get('expires_at',-1)<=observation['time']):reject('Stale operator requirement revision')
        if ref.get('status')=='cancelled' and action!='request_confirmation':reject('Operator requirement is already cancelled')
        if action=='confirm' and ref.get('status')!='pending_confirmation':reject('Operator requirement cannot be confirmed')
        if action=='clarify':validate_public_parameters(parameters['instruction'],observation,operator_id)
    elif action=='hold':
        target=next((a for a in observation['agents'] if a['id']==parameters['target_id']),None)
        if not target or 'move' not in target.get('capabilities',()):reject('Unknown or immobile hold recipient')
    elif action=='set_priority':
        if not any(t['id']==parameters['target_id'] for t in observation['targets']):reject('Priority target is not publicly known')
    elif action=='message':
        if not text(parameters.get('text'),512):reject('Operator message is empty, too long or contains control characters')
    elif action=='restrict_zone':
        bounds=observation.get('metaevolution',{}).get('announced_map',{}).get('bounds')
        box=parameters['bounds']
        if (not bounds or any(not bounds['min'][i]<=box['min'][i]<box['max'][i]<=bounds['max'][i] for i in range(3))):
            reject('Operator restriction is outside the announced map or is inverted')


class OperatorInput:
    def __init__(self, path, capabilities):
        self.path = Path(path)
        self.schema = capabilities.get('supported_actions', {}).get('issue_directive', {}).get('parameters_schema')
        self.enabled = FORMAT in capabilities.get('extensions', ()) and bool(self.schema)
        self.episode = None
        self.requests = {}
        self.messages = []
        self.last_error = None

    def _record(self, **row):
        self.messages.append(row)

    def drain(self):
        rows, self.messages = self.messages, []
        return rows

    def append(self, observation, request):
        if self.episode != observation['episode_id']:
            self.episode = observation['episode_id']
            self.requests.clear()
            self.last_error = None
        try:
            with self.path.open('rb') as stream:
                document = strict_json(stream.read(65537), maximum_bytes=65536)
            if (not isinstance(document, dict) or set(document) != {'format','episode_id','requests'} or
                    document['format'] != INPUT_FORMAT or document['episode_id'] != self.episode or
                    not isinstance(document['requests'], list) or len(document['requests']) > 64):
                raise ValueError('Operator input must name the current episode and at most 64 requests')
            if not self.enabled:
                raise ValueError('Environment does not advertise operator directives')
            pending = []
            seen = set()
            for row in document['requests']:
                if (not isinstance(row, dict) or set(row) != {'id','expires_at','parameters'} or
                        not isinstance(row['id'], str) or not 0 < len(row['id']) <= 100 or
                        any(ord(c)<32 for c in row['id']) or row['id'] in seen or
                        type(row['expires_at']) not in (int,float) or not math.isfinite(row['expires_at'])):
                    raise ValueError('Invalid or duplicate operator request')
                seen.add(row['id'])
                try:
                    validate(row['parameters'], self.schema)
                    validation_error = None
                except ProtocolError as error:
                    validation_error = str(error)
                pending.append((row, hashlib.sha256(json.dumps(row,sort_keys=True,
                    ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest(),validation_error))
            if len(set(self.requests)|seen)>256:
                raise ValueError('Operator input episode limit is 256 request IDs')
            for row, checksum, validation_error in pending:
                old = self.requests.get(row['id'])
                if old:
                    if old['sha256'] != checksum and old.get('rejected_sha256') != checksum:
                        self._record(request_id=row['id'], state='rejected', reason='request_id_reused_with_different_input')
                        old['rejected_sha256'] = checksum
                    continue
                if validation_error:
                    self.requests[row['id']]={'sha256':checksum,'state':'rejected'}
                    self._record(request_id=row['id'],state='rejected',reason=validation_error,time=observation['time'])
                    continue
                if row['expires_at'] <= observation['time']:
                    self.requests[row['id']]={'sha256':checksum,'state':'expired'}
                    self._record(request_id=row['id'],state='expired',time=observation['time'])
                    continue
                if request.get('operation')=='safe_stop':
                    break
                operator = next((a for a in observation['agents'] if a['kind']=='operator' and
                    a.get('status') not in ('failed','offline','unknown') and
                    a.get('communication',{}).get('reachable') is not False and
                    any(c.get('action')=='issue_directive' for c in a.get('available_actions',()))), None)
                if operator is None:
                    break
                try:
                    validate_public_parameters(row['parameters'],observation,operator['id'])
                except ValueError as error:
                    self.requests[row['id']]={'sha256':checksum,'state':'rejected'}
                    self._record(request_id=row['id'],state='rejected',reason=str(error),time=observation['time'])
                    continue
                index = len(request['commands'])
                request['commands'].append({'agent_id':operator['id'],'action':'issue_directive',
                                            'parameters':deepcopy(row['parameters'])})
                self.requests[row['id']]={'sha256':checksum,'state':'submitted','decision_id':request['decision_id'],
                    'command_index':index,'agent_id':operator['id']}
                self._record(request_id=row['id'],state='submitted',time=observation['time'],
                             decision_id=request['decision_id'],command_index=index,parameters=row['parameters'])
                break
            self.last_error = None
        except FileNotFoundError:
            return
        except (OSError, ValueError, ProtocolError) as error:
            reason = type(error).__name__+': '+str(error)
            if reason != self.last_error:
                self._record(state='rejected',reason=reason,time=observation['time'])
            self.last_error = reason

    def observe(self, response):
        for ident, pending in self.requests.items():
            if pending['state'] != 'submitted':
                continue
            result = next((row for row in response.get('command_results',()) if
                row.get('decision_id')==pending['decision_id'] and row.get('command_index')==pending['command_index'] and
                row.get('agent_id')==pending['agent_id']), None)
            if result and (result.get('execution_status') in ('completed','failed','cancelled') or
                           result.get('validation_status')=='rejected' or result.get('delivery_status') in ('expired','lost')):
                pending['state']='finished'
                self._record(request_id=ident,state='finished',result=deepcopy(result),time=response['time'])
