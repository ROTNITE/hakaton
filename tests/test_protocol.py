"""Checks authored protocol examples, not a running environment or a full validator."""
from copy import deepcopy
import json
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "contracts" / "examples" / "interaction-v1.json"
OBSERVATION_FIELDS = {
    "protocol_version", "episode_id", "request_id", "time", "mission", "agents",
    "infrastructure", "targets", "zones", "network", "events", "constraints",
    "metrics", "observation_quality",
}
DECISION_FIELDS = {
    "protocol_version", "episode_id", "decision_id", "request_id", "time",
    "operation", "previous_configuration", "selected_configuration",
    "candidate_evaluations", "role_assignments", "commands",
    "constraint_checks", "explanation",
}
OPERATIONS = {"keep", "select", "switch", "modify", "compose", "synthesize", "safe_stop"}
AGENT_KINDS = {
    "aerial", "ground", "underground", "surface_water", "underwater",
    "infrastructure", "digital", "operator",
}
ACTIONS = {"move", "observe", "inspect", "deliver", "relay", "send_message", "hold", "charge"}
PREDICATES = {
    "and", "or", "not", "eq", "ne", "lt", "le", "gt", "ge",
    "exists", "in", "all", "any", "count", "sum",
}


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"Non-finite JSON number: {value}")
        return result

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant,
                      parse_float=finite_float)


class ProtocolExamplesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples = strict_json(EXAMPLES.read_text(encoding="utf-8"))

    def number(self, value):
        self.assertIn(type(value), (int, float))
        self.assertTrue(math.isfinite(value))

    def point(self, value):
        self.assertIsInstance(value, list)
        self.assertEqual(len(value), 3)
        for component in value:
            self.number(component)

    def check_observation(self, obs):
        self.assertTrue(OBSERVATION_FIELDS <= obs.keys())
        self.assertEqual(obs["protocol_version"], "1.0")
        self.number(obs["time"])
        self.assertGreaterEqual(obs["time"], 0)
        ids = [a["id"] for a in obs["agents"]]
        self.assertEqual(len(ids), len(set(ids)))
        for agent in obs["agents"]:
            if agent["position"] is None:
                self.assertIn(agent["kind"], {"digital", "operator"})
            else:
                self.point(agent["position"])
            for key, resource in agent["resources"].items():
                self.assertEqual(key, resource["id"])
                for name in ("minimum", "value", "maximum"):
                    self.number(resource[name])
                self.assertLessEqual(0, resource["minimum"])
                self.assertLessEqual(resource["minimum"], resource["value"])
                self.assertLessEqual(resource["value"], resource["maximum"])
                self.assertLessEqual(resource["maximum"], 1)
            for data in agent.get("freshness", {}).values():
                if data["observed_at"] is not None and data["received_at"] is not None:
                    self.assertLessEqual(0, data["observed_at"])
                    self.assertLessEqual(data["observed_at"], data["received_at"])
                    self.assertLessEqual(data["received_at"], obs["time"])
        network = obs["network"]
        for key in ("connectivity_score", "reachable_agent_ratio", "average_link_quality"):
            self.number(network[key])
            self.assertLessEqual(0, network[key])
            self.assertLessEqual(network[key], 1)
        self.assertIs(type(network["partition_count"]), int)
        self.assertGreaterEqual(network["partition_count"], 0)
        quality = obs["observation_quality"]
        for key in ("global_completeness", "stale_data_ratio", "unknown_state_ratio"):
            self.number(quality[key])
            self.assertLessEqual(0, quality[key])
            self.assertLessEqual(quality[key], 1)
        self.number(quality["maximum_delay"])
        self.assertGreaterEqual(quality["maximum_delay"], 0)
        self.assertIs(type(quality["contradiction_count"]), int)
        self.assertGreaterEqual(quality["contradiction_count"], 0)

    def check_decision(self, decision, obs):
        self.assertTrue(DECISION_FIELDS <= decision.keys())
        self.assertIn(decision["operation"], OPERATIONS)
        self.assertEqual(decision["protocol_version"], "1.0")
        self.assertEqual(decision["episode_id"], obs["episode_id"])
        self.assertEqual(decision["time"], obs["time"])
        agents = {a["id"]: a for a in obs["agents"]}
        if "metaevolution" in obs:
            self.assertEqual(decision["previous_configuration"],
                             obs["metaevolution"]["plan"]["accepted_configuration"])
        for agent_id in decision["role_assignments"]:
            self.assertIn(agent_id, agents)
        cap = self.examples["capabilities"]
        for command in decision["commands"]:
            self.assertIn(command["agent_id"], agents)
            agent = agents[command["agent_id"]]
            action = command["action"]
            self.assertIn(action, cap["supported_actions"])
            self.assertIn(action, {item["action"] for item in agent["available_actions"]})
            self.assertTrue(set(cap["supported_actions"][action]["required_capabilities"])
                            <= set(agent["capabilities"]))
            self.assertIsInstance(command["parameters"], dict)
            if action == "move":
                self.point(command["parameters"]["target"])
            if action == "observe":
                radius = command["parameters"]["radius"]
                self.number(radius)
                self.assertGreater(radius, 0)
                self.assertLessEqual(radius, agent["sensors"]["maximum_radius"])
        constraints = {item["id"] for item in obs["constraints"]}
        constraints.update(item["id"] for agent in agents.values()
                           for item in agent["constraints"])
        for check in decision["constraint_checks"]:
            self.assertIn(check["constraint_id"], constraints)
        known_refs = {obs["request_id"]} | {event["id"] for event in obs["events"]}
        self.assertTrue(set(decision["explanation"]["observation_refs"]) <= known_refs)
        grouped = []
        for group in decision.get("metaevolution", {}).get("command_groups", []):
            self.assertTrue(group["command_indices"])
            for index in group["command_indices"]:
                self.assertIs(type(index), int)
                self.assertGreaterEqual(index, 0)
                self.assertLess(index, len(decision["commands"]))
                grouped.append(index)
        self.assertEqual(len(grouped), len(set(grouped)))

    def test_full_catalog_and_all_seven_operations(self):
        cap = self.examples["capabilities"]
        self.assertEqual(set(cap["agent_kinds"]), AGENT_KINDS)
        self.assertEqual(set(cap["supported_actions"]), ACTIONS)
        self.assertEqual(set(cap["predicate_operators"]), PREDICATES)
        self.assertEqual(set(self.examples["decisions"]), OPERATIONS)
        for operation, decision in self.examples["decisions"].items():
            with self.subTest(operation=operation):
                self.assertEqual(decision["operation"], operation)
                name = self.examples["decision_contexts"][operation]
                self.check_decision(decision, self.examples["observations"][name])

    def test_observations_and_parameter_schema_references(self):
        cap = self.examples["capabilities"]
        for name, obs in self.examples["observations"].items():
            with self.subTest(observation=name):
                self.check_observation(obs)
                for agent in obs["agents"]:
                    for item in agent["available_actions"]:
                        self.assertIn(item["action"], cap["supported_actions"])
                        document, pointer = item["parameters_schema_ref"].split("#")
                        self.assertEqual(document, "/v1/environment/capabilities")
                        value = cap
                        for key in pointer.lstrip("/").split("/"):
                            value = value[key.replace("~1", "/").replace("~0", "~")]
                        self.assertEqual(value,
                                         cap["supported_actions"][item["action"]]["parameters_schema"])

    def test_select_response_is_linked_and_not_a_second_decision(self):
        reset = self.examples["reset_response"]
        decision = self.examples["decisions"]["select"]
        response = self.examples["step_response"]
        self.assertEqual(reset["observation"], self.examples["observations"]["initial"])
        self.assertEqual(reset["time"], decision["time"])
        self.assertEqual(response["request_id"], decision["request_id"])
        self.assertEqual(response["time"], response["observation"]["time"])
        self.assertEqual(response["episode_id"], response["observation"]["episode_id"])
        self.assertEqual(response["metrics"], response["observation"]["metrics"])
        self.assertEqual(response["events"], response["observation"]["events"])
        self.assertEqual(response["observation"], self.examples["observations"]["after_select"])
        for result in response["command_results"]:
            self.assertEqual(result["decision_id"], decision["decision_id"])
            command = decision["commands"][result["command_index"]]
            self.assertEqual(result["agent_id"], command["agent_id"])
            self.assertEqual(result["action"], command["action"])
        self.assertGreater(response["time"], decision["time"])

    def test_delayed_and_unknown_results_keep_original_command_reference(self):
        examples = self.examples["asynchronous_results"]
        decision = self.examples["decisions"]["select"]
        for key in ("initial_queued", "acknowledgement_unknown", "later_public_result"):
            result = examples[key]
            self.assertEqual(result["decision_id"], decision["decision_id"])
            self.assertEqual(result["command_index"], 0)
        self.assertEqual(examples["initial_queued"]["execution_status"], "not_started")
        self.assertEqual(examples["acknowledgement_unknown"]["delivery_status"], "unknown")
        self.assertEqual(examples["acknowledgement_unknown"]["execution_status"], "unknown")
        self.assertEqual(examples["later_public_result"]["execution_status"], "completed")

    def test_synthesized_program_has_bound_roles_and_closed_transitions(self):
        decision = self.examples["decisions"]["synthesize"]
        scenario = decision["selected_configuration"]["synthesized_scenario"]
        self.assertNotIn(scenario["id"], self.examples["capabilities"]["scenario_ids"])
        self.assertEqual(decision["selected_configuration"]["scenario_ids"], [scenario["id"]])
        parameters = decision["selected_configuration"]["parameters"]
        self.assertTrue(set(scenario["parameter_schema"]["required"]) <= parameters.keys())
        roles = {item["id"]: item for item in scenario["roles"]}
        obs = self.examples["observations"]["confirmed_target"]
        agents = {a["id"]: a for a in obs["agents"]}
        for role, declaration in roles.items():
            assigned = [agents[aid] for aid, name in decision["role_assignments"].items()
                        if name == role]
            self.assertGreaterEqual(len(assigned), declaration["minimum"])
            self.assertLessEqual(len(assigned), declaration["maximum"])
            for agent in assigned:
                self.assertTrue(set(declaration["required_capabilities"]) <= set(agent["capabilities"]))
        program = scenario["execution_rules"]
        self.assertEqual(program["grammar"], "metaevolution.fsm.v1")
        states = {state["id"]: state for state in program["states"]}
        self.assertEqual(len(states), len(program["states"]))
        self.assertIn(program["initial_state"], states)
        for state in states.values():
            if "outcome" in state:
                self.assertNotIn("commands", state)
                continue
            self.assertGreater(state["timeout"]["seconds"], 0)
            for target in (state["transition"]["on_success"],
                           state["transition"]["on_failure"], state["timeout"]["on_timeout"]):
                self.assertIn(target, states)
            for template in state["commands"]:
                self.assertIn(template["role"], roles)
                self.assertIn(template["action"], scenario["allowed_actions"])
                for value in template["parameters"].values():
                    if isinstance(value, dict) and "parameter" in value:
                        self.assertIn(value["parameter"], parameters)

    def test_keep_and_modify_preserve_their_promised_structure(self):
        keep = self.examples["decisions"]["keep"]
        self.assertEqual(keep["previous_configuration"]["scenario_ids"],
                         keep["selected_configuration"]["scenario_ids"])
        self.assertEqual(keep["previous_configuration"]["parameters"],
                         keep["selected_configuration"]["parameters"])
        self.assertEqual(keep["previous_configuration"]["role_assignments"],
                         keep["role_assignments"])
        modify = self.examples["decisions"]["modify"]
        self.assertEqual(modify["previous_configuration"]["scenario_ids"],
                         modify["selected_configuration"]["scenario_ids"])
        self.assertEqual(modify["previous_configuration"]["role_assignments"],
                         modify["role_assignments"])
        self.assertNotEqual(modify["previous_configuration"]["parameters"],
                            modify["selected_configuration"]["parameters"])

    def test_unknown_optional_fields_and_absent_extensions_are_structurally_tolerated(self):
        obs = deepcopy(self.examples["observations"]["initial"])
        obs["unrecognized_optional_field"] = {"example": True}
        obs.pop("metaevolution")
        for agent in obs["agents"]:
            agent.pop("freshness")
        self.check_observation(obs)

    def test_spatial_null_and_invalid_resource_are_detected(self):
        obs = deepcopy(self.examples["observations"]["initial"])
        obs["agents"][0]["position"] = None
        with self.assertRaises(AssertionError):
            self.check_observation(obs)
        obs = deepcopy(self.examples["observations"]["initial"])
        obs["agents"][0]["resources"]["energy"]["value"] = 1.1
        with self.assertRaises(AssertionError):
            self.check_observation(obs)

    def test_digital_null_is_structurally_allowed(self):
        obs = deepcopy(self.examples["observations"]["initial"])
        agent = obs["agents"][0]
        agent.update(kind="digital", position=None, capabilities=["compute"], available_actions=[])
        self.check_observation(obs)

    def test_missing_field_and_dangling_constraint_are_detected(self):
        obs = deepcopy(self.examples["observations"]["initial"])
        del obs["network"]
        with self.assertRaises(AssertionError):
            self.check_observation(obs)
        decision = deepcopy(self.examples["decisions"]["select"])
        decision["constraint_checks"][0]["constraint_id"] = "missing_constraint"
        with self.assertRaises(AssertionError):
            self.check_decision(decision, self.examples["observations"]["initial"])

    def test_undeclared_action_and_invalid_group_index_are_detected(self):
        obs = self.examples["observations"]["initial"]
        decision = deepcopy(self.examples["decisions"]["select"])
        decision["commands"][0]["action"] = "teleport"
        with self.assertRaises(AssertionError):
            self.check_decision(decision, obs)
        decision = deepcopy(self.examples["decisions"]["select"])
        decision["metaevolution"] = {"command_groups": [{"id": "bad", "command_indices": [99]}]}
        with self.assertRaises(AssertionError):
            self.check_decision(decision, obs)

    def test_invalid_json_numbers_and_duplicate_keys_are_rejected(self):
        for raw in ('{"x": NaN}', '{"x": Infinity}', '{"x": 1e999}', '{"x": 1, "x": 2}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                strict_json(raw)
        with self.assertRaises(AssertionError):
            self.number(True)

    def test_roles_are_supported_by_scenarios_and_agent_capabilities(self):
        cap = self.examples["capabilities"]
        for operation, decision in self.examples["decisions"].items():
            with self.subTest(operation=operation):
                obs = self.examples["observations"][self.examples["decision_contexts"][operation]]
                agents = {a["id"]: a for a in obs["agents"]}
                selected = decision["selected_configuration"]
                roles = {}
                for scenario_id in selected["scenario_ids"]:
                    if scenario_id in cap["supported_scenarios"]:
                        scenario = cap["supported_scenarios"][scenario_id]
                    else:
                        scenario = selected["synthesized_scenario"]
                    for role in scenario["roles"]:
                        roles[role["id"]] = role
                for agent_id, role in decision["role_assignments"].items():
                    self.assertIn(role, roles)
                    self.assertTrue(set(roles[role]["required_capabilities"])
                                    <= set(agents[agent_id]["capabilities"]))
                for scenario_id, members in decision.get("metaevolution", {}).get("scenario_participants", {}).items():
                    self.assertIn(scenario_id, selected["scenario_ids"])
                    self.assertTrue(set(members) <= decision["role_assignments"].keys())

    def test_parameter_descriptors_are_complete_and_scoped_in_composition(self):
        cap = self.examples["capabilities"]
        for action, descriptor in cap["supported_actions"].items():
            schema = descriptor["parameters_schema"]
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertEqual(schema["type"], "object")
            self.assertTrue(set(schema["required"]) <= schema["properties"].keys())
        for operation, decision in self.examples["decisions"].items():
            selected = decision["selected_configuration"]
            for scenario_id in selected["scenario_ids"]:
                with self.subTest(operation=operation, scenario=scenario_id):
                    if scenario_id in cap["supported_scenarios"]:
                        schema = cap["supported_scenarios"][scenario_id]["parameters_schema"]
                    else:
                        schema = selected["synthesized_scenario"]["parameter_schema"]
                    params = selected["parameters"]
                    if operation == "compose":
                        params = params["by_scenario"][scenario_id]
                    self.assertTrue(set(schema["required"]) <= params.keys())

    def test_administrative_close_does_not_claim_safe_or_successful_mission(self):
        request = self.examples["close_request"]
        response = self.examples["close_response"]
        self.assertEqual(response["request_id"], request["request_id"])
        self.assertEqual(response["episode_id"], request["episode_id"])
        self.assertIs(response["closed"], True)
        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["reason_code"], "closed_by_client")


if __name__ == "__main__":
    unittest.main()
