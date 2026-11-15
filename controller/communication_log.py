"""Readable views of communication evidenced by delivered Core observations.

These records are derived from public observations, not new radio messages.
"""


class CommunicationLog:
    def __init__(self, capabilities):
        extensions = capabilities.get('extensions', [])
        self.radio = isinstance(extensions, list) and 'metarescue.radio_transport.v1' in extensions
        self.peer = isinstance(extensions, list) and 'metarescue.aid_and_peer_messages.v1' in extensions
        self.seen = set()

    def observe(self, observation):
        """Yield each evidenced report or inbox message once per controller run."""
        if self.radio:
            targets = {item.get('id'): item for item in observation.get('targets', []) if isinstance(item, dict)}
            zones = {item.get('id'): item for item in observation.get('zones', []) if isinstance(item, dict)}
            for event in observation.get('events', []):
                if not isinstance(event, dict) or event.get('type') not in (
                        'target_detected', 'hazard_appeared', 'environment_change'):
                    continue
                parameters = event.get('parameters')
                if not isinstance(parameters, dict) or not isinstance(parameters.get('message_id'), str):
                    continue
                event_id, sender = event.get('id'), event.get('source')
                if not isinstance(event_id, str) or not isinstance(sender, str):
                    continue
                key = ('report', event_id, event.get('status'))
                if key in self.seen:
                    continue
                self.seen.add(key)
                subjects = event.get('targets', [])
                data = {'event': event}
                if isinstance(subjects, list):
                    source = targets if event['type'] == 'target_detected' else zones
                    matches = [source[identifier] for identifier in subjects
                               if isinstance(identifier, str) and identifier in source
                               and source[identifier].get('message_id') == parameters['message_id']]
                    if matches:
                        data['observations'] = matches
                yield {'representation': 'delivered_report_view', 'sender': sender, 'receiver': 'rescue-base',
                       'signal': event['type'].upper(), 'timestamp': event.get('time'),
                       'received_at': event.get('received_at'), 'message_id': parameters['message_id'],
                       'event_id': event_id, 'observation_request_id': observation.get('request_id'), 'data': data}
        if self.peer:
            for agent in observation.get('agents', []):
                if not isinstance(agent, dict) or not isinstance(agent.get('communication'), dict):
                    continue
                for message in agent['communication'].get('inbox', []):
                    if not isinstance(message, dict):
                        continue
                    identifier, sender, recipient = (message.get('message_id'), message.get('sender_id'),
                                                     message.get('recipient_id'))
                    if not all(isinstance(value, str) and value for value in (identifier, sender, recipient)):
                        continue
                    if recipient != agent.get('id') or ('peer', identifier) in self.seen:
                        continue
                    self.seen.add(('peer', identifier))
                    yield {'representation': 'delivered_peer_message_view', 'sender': sender, 'receiver': recipient,
                           'signal': 'PEER_MESSAGE', 'received_at': message.get('received_at'),
                           'message_id': identifier, 'observation_request_id': observation.get('request_id'),
                           'data': message.get('payload')}
