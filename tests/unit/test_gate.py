import unittest

from workflow_cockpit.services.graph import GraphNode, WorkflowDefinitionParser
from workflow_cockpit.services.run_state import RunStateData
from workflow_cockpit.services.snapshot import extract_gate


def gate_node(**kwargs) -> GraphNode:
    defaults = {
        "id": "review",
        "label": "Review",
        "type": "gate",
        "parent_id": None,
        "branch": None,
        "depth": 0,
        "order": 0,
        "gate": True,
        "verdict_input": "decision",
        "on_reject": "retry",
    }
    defaults.update(kwargs)
    return GraphNode(**defaults)


def paused_state(runtime_id: str = "review", output=None, step_type: str = "gate") -> RunStateData:
    return RunStateData(
        status="paused",
        current_step_id=runtime_id,
        step_results={runtime_id: {"type": step_type, "output": output}},
    )


class ExtractGateTests(unittest.TestCase):
    def test_non_paused_is_none(self):
        state = RunStateData(status="running", current_step_id="review")
        self.assertIsNone(extract_gate(state, gate_node()))

    def test_non_gate_result_is_none(self):
        state = paused_state(step_type="shell", output={"message": "x", "options": ["a"]})
        self.assertIsNone(extract_gate(state, None))

    def test_valid_gate_uses_persisted_message_and_option_order(self):
        state = paused_state(
            output={"message": "Approve the plan?", "options": ["reject", "approve"], "on_reject": "retry"}
        )
        gate = extract_gate(state, gate_node())
        self.assertIsNotNone(gate)
        self.assertEqual(gate.message, "Approve the plan?")
        self.assertEqual(gate.options, ("reject", "approve"))
        self.assertEqual(gate.verdict_input, "decision")
        self.assertEqual(gate.on_reject, "retry")
        self.assertFalse(gate.malformed)
        self.assertTrue(gate.structured)

    def test_missing_options_is_malformed_but_present(self):
        state = paused_state(output={"message": "Review"})
        gate = extract_gate(state, gate_node())
        self.assertIsNotNone(gate)
        self.assertTrue(gate.malformed)
        self.assertFalse(gate.structured)

    def test_non_string_options_are_malformed(self):
        state = paused_state(output={"message": "Review", "options": ["ok", 3]})
        gate = extract_gate(state, gate_node())
        self.assertTrue(gate.malformed)
        self.assertEqual(gate.options, ("ok",))

    def test_verdict_from_node_is_required_for_structured(self):
        state = paused_state(output={"message": "Review", "options": ["go"]})
        gate = extract_gate(state, gate_node(verdict_input=None))
        self.assertFalse(gate.structured)
        self.assertFalse(gate.malformed)

    def test_missing_message_is_malformed(self):
        state = paused_state(output={"options": ["go"]})
        gate = extract_gate(state, gate_node())
        self.assertTrue(gate.malformed)
        self.assertFalse(gate.structured)
        self.assertIn("message", gate.error)

    def test_missing_result_is_abort_only_gate(self):
        state = RunStateData(status="paused", current_step_id="review")
        gate = extract_gate(state, gate_node())
        self.assertIsNotNone(gate)
        self.assertTrue(gate.malformed)
        self.assertFalse(gate.structured)
        self.assertIn("missing", gate.error)

    def test_declared_non_gate_is_not_a_gate(self):
        state = paused_state(output={"message": "Review", "options": ["go"]})
        self.assertIsNone(extract_gate(state, gate_node(gate=False, type="shell")))


class GraphGateMetadataTests(unittest.TestCase):
    def test_parser_carries_verdict_metadata_for_nested_gates(self):
        graph = WorkflowDefinitionParser().parse(
            (
                {"id": "prepare", "command": "demo.prepare"},
                {
                    "id": "branch",
                    "type": "if",
                    "condition": "x",
                    "then": [
                        {
                            "id": "nested-review",
                            "type": "gate",
                            "message": "Nested?",
                            "options": ["approve", "reject"],
                            "verdict_input": "decision",
                            "on_reject": "skip",
                        }
                    ],
                },
            )
        )
        node = graph.by_id["nested-review"]
        self.assertTrue(node.gate)
        self.assertEqual(node.verdict_input, "decision")
        self.assertEqual(node.on_reject, "skip")
        self.assertEqual(node.options, ("approve", "reject"))


if __name__ == "__main__":
    unittest.main()
