from copy import deepcopy
import unittest

from controller.communication_log import CommunicationLog


CAPABILITIES = {'extensions': ['metarescue.radio_transport.v1', 'metarescue.aid_and_peer_messages.v1']}


class CommunicationLogTests(unittest.TestCase):
    def test_delivered_reports_keep_evidence_and_are_deduplicated(self):
        event = {'id': 'event-1', 'type': 'target_detected', 'time': 12.5, 'received_at': 14,
                 'source': 'drone-3', 'targets': ['person-1'], 'status': 'new', 'confidence': .94,
                 'parameters': {'message_id': 'packet-1'}}
        target = {'id': 'person-1', 'message_id': 'packet-1', 'position': [42, 18, 0],
                  'priority': 3, 'confidence': .94}
        observation = {'request_id': 'obs-1', 'events': [event], 'targets': [target], 'zones': [], 'agents': []}
        before = deepcopy(observation)
        log = CommunicationLog(CAPABILITIES)
        rows = list(log.observe(observation))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row['sender'], row['receiver'], row['signal']), ('drone-3', 'rescue-base', 'TARGET_DETECTED'))
        self.assertEqual((row['timestamp'], row['received_at'], row['message_id']), (12.5, 14, 'packet-1'))
        self.assertEqual(row['data']['observations'], [target])
        self.assertNotIn('requires_ack', row)
        self.assertEqual(list(log.observe(observation)), [])
        self.assertEqual(observation, before)

    def test_hazard_resolution_and_matching_prevent_stale_details(self):
        event = {'id': 'packet-zone', 'type': 'environment_change', 'time': 20, 'received_at': 22,
                 'source': 'drone-1', 'targets': ['zone-1'], 'status': 'resolved',
                 'parameters': {'message_id': 'packet-new', 'active': False, 'kinds': []}}
        obs = {'events': [event], 'zones': [{'id': 'zone-1', 'message_id': 'packet-old'}]}
        row = list(CommunicationLog(CAPABILITIES).observe(obs))[0]
        self.assertEqual(row['signal'], 'ENVIRONMENT_CHANGE')
        self.assertEqual(row['data']['event']['status'], 'resolved')
        self.assertNotIn('observations', row['data'])

    def test_peer_message_is_taken_from_the_recipient_inbox(self):
        message = {'message_id': 'cmd-1', 'sender_id': 'relay', 'recipient_id': 'rescuer',
                   'received_at': 8, 'payload': {'signal': 'HELP_REQUEST', 'count': 2}}
        obs = {'request_id': 'obs-2', 'agents': [{'id': 'rescuer', 'communication': {'inbox': [message]}}]}
        log = CommunicationLog(CAPABILITIES)
        row = list(log.observe(obs))[0]
        self.assertEqual((row['sender'], row['receiver'], row['data']), ('relay', 'rescuer', message['payload']))
        self.assertNotIn('timestamp', row)  # The inbox supplies receipt time only.
        self.assertEqual(list(log.observe(obs)), [])
        obs['agents'][0]['id'] = 'another-agent'
        self.assertEqual(list(CommunicationLog(CAPABILITIES).observe(obs)), [])

    def test_no_claim_for_unadvertised_or_unlinked_events(self):
        obs = {'events': [{'id': 'e', 'type': 'hazard_appeared', 'source': 'd', 'parameters': {}}],
               'agents': [{'id': 'r', 'communication': {'inbox': [
                   {'message_id': 'x', 'sender_id': 's', 'recipient_id': 'r'}]}}]}
        self.assertEqual(list(CommunicationLog({}).observe(obs)), [])
        self.assertEqual(list(CommunicationLog({'extensions': ['metarescue.radio_transport.v1']}).observe(obs)), [])


if __name__ == '__main__':
    unittest.main()
