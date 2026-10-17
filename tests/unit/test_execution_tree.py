"""The persisted execution tree is read as a structure, version-guarded."""

import unittest

import yaml

from tests.fixtures import composition as fx
from workflow_cockpit.services import execution_tree as et
from workflow_cockpit.services.execution_tree import (
    ExecutionTree,
    Resolution,
    UnsupportedExecution,
)


class VersionGuardTests(unittest.TestCase):
    def test_absent_execution_is_a_legacy_run(self):
        self.assertIsNone(et.parse({"status": "paused"}))

    def test_unsupported_versions_are_not_interpreted(self):
        state = fx.load_state("reference")
        for version in (1, 3, 0, None, "2"):
            with self.subTest(version=version):
                parsed = et.parse(fx.with_version(state, version))
                self.assertIsInstance(parsed, UnsupportedExecution)
                self.assertEqual(parsed.version, version)

    def test_non_mapping_execution_is_unsupported(self):
        state = fx.load_state("reference")
        state["execution"] = ["not", "a", "mapping"]
        parsed = et.parse(state)
        self.assertIsInstance(parsed, UnsupportedExecution)
        self.assertIsNone(parsed.version)

    def test_corrupt_tree_is_unresolved_not_an_exception(self):
        parsed = et.parse(fx.corrupt_tree(fx.load_state("reference")))
        self.assertIsInstance(parsed, ExecutionTree)
        self.assertFalse(parsed.structurally_valid)
        self.assertIs(parsed.resolution, Resolution.UNRESOLVED)
        self.assertIsNone(parsed.active)

    def test_sequence_length_mismatch_is_invalid(self):
        parsed = et.parse(fx.with_sequence_length_mismatch(fx.load_state("reference")))
        self.assertIsInstance(parsed, ExecutionTree)
        self.assertFalse(parsed.structurally_valid)

    def test_absent_unfinished_node_is_unresolved(self):
        parsed = et.parse(fx.without_unfinished_node(fx.load_state("reference")))
        self.assertTrue(parsed.structurally_valid)
        self.assertIsNone(parsed.active)
        self.assertIs(parsed.resolution, Resolution.UNRESOLVED)

    def test_mismatched_current_step_id_is_unresolved(self):
        state = fx.with_current_step_id(fx.load_state("reference"), "publish")
        parsed = et.parse(state)
        self.assertIsNotNone(parsed.active)
        self.assertIs(parsed.resolution, Resolution.UNRESOLVED)


class StructureTests(unittest.TestCase):
    def test_root_steps_are_zipped_with_nodes(self):
        tree = et.parse(fx.load_state("reference"))
        self.assertEqual([step.step_id for step in tree.root.steps], ["build", "review-release", "publish"])
        self.assertEqual(tree.root.workflow_id, "release")
        self.assertEqual(tree.version, 2)
        self.assertEqual(tree.offset, 0)

    def test_missing_step_id_defaults_to_index(self):
        state = fx.load_state("reference")
        sequence = state["execution"]["sequence"]
        steps = yaml.safe_load(sequence["source"])
        steps[0].pop("id")
        sequence["source"] = yaml.safe_dump(steps, sort_keys=False)
        tree = et.parse(state)
        self.assertEqual(tree.root.steps[0].step_id, "step-0")

    def test_call_children_come_from_the_frozen_binding(self):
        tree = et.parse(fx.load_state("reference"))
        call = tree.root.steps[1]
        self.assertTrue(call.is_call)
        self.assertTrue(call.is_bound)
        self.assertEqual(call.binding.workflow, "release-notes")
        child = call.children[0]
        self.assertEqual(child.workflow_id, "release-notes")
        self.assertEqual([step.step_id for step in child.steps], ["draft", "review", "publish-notes"])
        self.assertEqual(child.steps[1].verdict_input, "approval")

    def test_loop_iterations_after_the_first_share_child_zero_steps(self):
        tree = et.parse(fx.load_state("loop-twice"))
        loop = tree.root.steps[0]
        self.assertEqual(loop.kind, "do-while")
        self.assertEqual(len(loop.children), 2)
        self.assertEqual(
            [step.step_id for step in loop.children[1].steps],
            [step.step_id for step in loop.children[0].steps],
        )

    def test_fanout_items_come_from_the_template(self):
        tree = et.parse(fx.load_state("fanout"))
        fan = tree.root.steps[1]
        self.assertEqual(fan.kind, "fan-out")
        self.assertEqual(len(fan.children), 2)
        self.assertEqual([step.step_id for step in fan.children[0].steps], ["notes"])
        self.assertEqual(fan.children[0].steps[0].kind, "workflow")

    def test_dynamic_target_is_visible_and_unbound(self):
        tree = et.parse(fx.load_state("dynamic-target"))
        call = tree.root.steps[1]
        self.assertTrue(call.is_call)
        self.assertFalse(call.is_bound)
        self.assertTrue(call.dynamic_target)
        self.assertEqual(call.target, "{{ inputs.target }}")

    def test_yaml_strings_are_decoded_once_per_parse(self):
        import workflow_cockpit.services.execution_parse as module

        calls = {"count": 0}
        original = module.yaml.safe_load

        def counting(text):
            calls["count"] += 1
            return original(text)

        module.yaml.safe_load = counting
        try:
            tree = et.parse(fx.load_state("loop-twice"))
        finally:
            module.yaml.safe_load = original
        # root source + loop body source + one frozen definition = 3 distinct
        # strings, however many loop iterations and nodes reference them.
        self.assertEqual(calls["count"], 3)
        self.assertEqual(len(tree.root.steps[0].children), 2)

    def test_handled_failure_is_derived(self):
        tree = et.parse(fx.load_state("continue-on-error"))
        call = tree.root.steps[1]
        self.assertEqual(call.outcome, "completed")
        self.assertEqual(call.result["status"], "failed")
        self.assertTrue(call.continue_on_error)
        self.assertTrue(call.handled_failure)


if __name__ == "__main__":
    unittest.main()
