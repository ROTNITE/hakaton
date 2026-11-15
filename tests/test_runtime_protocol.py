"""Production codec regressions independent of the existing authored-example tests."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from contracts.protocol import (ProtocolError, strict_json, encode,
                                validate_observation, validate_decision)


class RuntimeProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples = json.loads((Path(__file__).parents[1] / 'contracts/examples/interaction-v1.json').read_text(encoding='utf-8'))

    def test_all_authored_observations_and_decisions_validate(self):
        for observation in self.examples['observations'].values():
            validate_observation(observation)
        for operation, decision in self.examples['decisions'].items():
            observation = self.examples['observations'][self.examples['decision_contexts'][operation]]
            validate_decision(decision, observation, self.examples['capabilities'])

    def test_wire_rejects_ambiguous_and_nonfinite_json(self):
        for raw in ('{"x":1,"x":2}', '{"x":1e999}', '{"x":NaN}', b'\xff'):
            with self.subTest(raw=raw), self.assertRaises(ProtocolError):
                strict_json(raw)
        with self.assertRaises(ProtocolError):
            encode({'x': float('inf')})
        with self.assertRaises(ProtocolError):
            strict_json('{"x":' + '9' * 5000 + '}')

    def test_wrong_protocol_version_has_normative_error_code(self):
        observation = deepcopy(self.examples['observations']['initial'])
        observation['protocol_version'] = '2.0'
        with self.assertRaises(ProtocolError) as result:
            validate_observation(observation)
        self.assertEqual(result.exception.code, 'UNSUPPORTED_PROTOCOL_VERSION')

    def test_unknown_optional_fields_do_not_break_core(self):
        observation = deepcopy(self.examples['observations']['initial'])
        observation.pop('metaevolution')
        observation['unrecognized_extension'] = {'example': True}
        for agent in observation['agents']:
            agent.pop('freshness')
        validate_observation(strict_json(encode(observation)))

    def test_bool_position_resource_and_future_data_are_rejected(self):
        for mutate in (lambda a: a.update(position=[True, 0, 0]),
                       lambda a: a['resources']['energy'].update(value=True),
                       lambda a: a['freshness']['position'].update(received_at=1)):
            observation = deepcopy(self.examples['observations']['initial'])
            mutate(observation['agents'][0])
            with self.assertRaises(ProtocolError):
                validate_observation(observation)

    def test_spatial_null_and_inverted_resource_bounds_are_rejected(self):
        for mutate in (lambda a: a.update(position=None),
                       lambda a: a['resources']['energy'].update(minimum=.95)):
            observation = deepcopy(self.examples['observations']['initial'])
            mutate(observation['agents'][0])
            with self.assertRaises(ProtocolError):
                validate_observation(observation)

    def test_duplicate_command_group_cannot_execute_twice(self):
        decision = deepcopy(self.examples['decisions']['select'])
        decision['metaevolution'] = {'command_groups': [
            {'id': 'one', 'command_indices': [0]}, {'id': 'two', 'command_indices': [0]}]}
        with self.assertRaises(ProtocolError):
            validate_decision(decision, self.examples['observations']['initial'], self.examples['capabilities'])


if __name__ == '__main__':
    unittest.main()
