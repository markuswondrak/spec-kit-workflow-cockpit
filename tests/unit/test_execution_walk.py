"""The execution walk reproduces the engine's own active node and scope paths.

The recorded ``status --json`` of every scenario is the engine's oracle: it
names the active node (``gate.step_id``) and the scope path the engine computed
from the same tree. These tests assert Cockpit's reading equals it, so the
re-implemented walk cannot drift silently without a live engine.
"""

import unittest

from tests.fixtures import composition as fx
from workflow_cockpit.services import execution_tree as et
from workflow_cockpit.services import execution_walk as ew


class OracleParityTests(unittest.TestCase):
    def test_active_node_matches_the_engine_for_every_scenario(self):
        for scenario in fx.SCENARIOS:
            with self.subTest(scenario=scenario):
                tree = et.parse(fx.load_state(scenario))
                oracle = fx.load_status(scenario)
                node = tree.active
                if oracle["status"] in ("paused", "failed", "aborted"):
                    self.assertIsNotNone(node)
                    self.assertEqual(node.qualified_id, oracle["current_step_id"])
                    self.assertIs(tree.resolution.value, "ok")
                else:
                    # A settled run has no unfinished node; that is unresolved by
                    # contract, and no gate is projected for it.
                    self.assertIsNone(node)

    def test_gate_scope_path_matches_the_engine(self):
        for scenario in fx.SCENARIOS:
            oracle = fx.load_status(scenario)
            gate = oracle.get("gate") or {}
            if not gate.get("step_id"):
                continue
            with self.subTest(scenario=scenario):
                tree = et.parse(fx.load_state(scenario))
                node = tree.active
                self.assertIsNotNone(node)
                self.assertEqual(node.step_id, gate["step_id"])
                self.assertEqual(
                    fx.normalized_scope_path(node.scope_path),
                    fx.normalized_scope_path(gate.get("scope_path")),
                )

    def test_workflow_scopes_match_the_engine(self):
        for scenario in fx.SCENARIOS:
            oracle = fx.load_status(scenario)
            scopes = oracle.get("workflow_scopes") or []
            if not scopes:
                continue
            with self.subTest(scenario=scenario):
                tree = et.parse(fx.load_state(scenario))
                calls = [node for node in ew.iter_steps(tree) if node.is_call and node.is_bound]
                engine_paths = {fx.normalized_scope_path(entry["scope_path"]) for entry in scopes}
                cockpit_paths = {
                    fx.normalized_scope_path(node.scope_path) for node in calls
                }
                self.assertTrue(engine_paths.issubset(cockpit_paths), cockpit_paths)


class ActiveNodeTests(unittest.TestCase):
    def test_enclosing_calls_are_reported_for_every_depth(self):
        expected = {
            "reference": ("review-release",),
            "collision": ("review-release",),
            "depth2": ("middle-call", "inner-call"),
            "loop-paused": ("notes-call",),
            "fanout": ("notes",),
            "failed-child": ("broken-call",),
        }
        for scenario, calls in expected.items():
            with self.subTest(scenario=scenario):
                node = et.parse(fx.load_state(scenario)).active
                self.assertEqual(node.enclosing_calls, calls)

    def test_enclosing_calls_are_the_call_ancestors(self):
        tree = et.parse(fx.load_state("depth2"))
        node = tree.active
        self.assertEqual(node.step_id, "deep-review")
        self.assertEqual(node.workflow_id, "inner")

    def test_collision_prefers_the_child_gate(self):
        tree = et.parse(fx.load_state("collision"))
        node = tree.active
        self.assertEqual(node.step_id, "review")
        self.assertEqual(node.qualified_id, "review")
        self.assertEqual(node.scope_path, ("review-release",))
        # The root step of the same id is a different node with its own path.
        root = ew.find_node(tree, (), "review")
        self.assertIsNotNone(root)
        self.assertEqual(root.phase, "done")
        self.assertIsNotNone(root.result)

    def test_qualified_ids_follow_the_engine_forms(self):
        loop = et.parse(fx.load_state("loop-twice"))
        calls = [node for node in ew.iter_steps(loop) if node.is_call and node.is_bound]
        self.assertEqual(
            [node.qualified_id for node in calls],
            ["notes-call", "notes-loop:notes-call:1"],
        )
        fan = et.parse(fx.load_state("fanout"))
        notes = [node for node in ew.iter_steps(fan) if node.is_call]
        self.assertEqual([node.qualified_id for node in notes], ["fan:notes:0", "fan:notes:1"])

    def test_occurrence_paths_match_the_log_execution_paths(self):
        for scenario in ("reference", "depth2", "loop-twice", "fanout"):
            with self.subTest(scenario=scenario):
                tree = et.parse(fx.load_state(scenario))
                index = ew.step_index(tree)
                for event in fx.load_log(scenario):
                    path = event.get("execution_path")
                    if not path:
                        continue
                    key = (
                        event.get("workflow_id", ""),
                        tuple(path),
                        event.get("step_id", ""),
                    )
                    matches = [node for node in index.values() if ew.timing_key(node) == key]
                    self.assertEqual(len(matches), 1, key)

    def test_root_scope_events_key_on_the_qualified_id(self):
        tree = et.parse(fx.load_state("loop-twice"))
        index = ew.step_index(tree)
        iteration_two = index[("notes-loop", 1, "notes-call")]
        self.assertEqual(ew.timing_key(iteration_two), ("", (), "notes-loop:notes-call:1"))
        child_gate = index[("notes-loop", 1, "notes-call", "review")]
        self.assertEqual(
            ew.timing_key(child_gate),
            ("release-notes", (0, 1, 0, "workflow", 1), "review"),
        )

    def test_done_subtree_is_skipped_whole(self):
        tree = et.parse(fx.load_state("continue-on-error"))
        # boom stays ``blocked`` under a call node the engine already completed.
        boom = ew.find_node(tree, ("broken-call",), "boom")
        self.assertEqual(boom.phase, "blocked")
        self.assertIsNone(tree.active)

    def test_display_scope_path_joins_names(self):
        node = et.parse(fx.load_state("reference")).active
        self.assertEqual(ew.display_scope_path(node.display_scope_path), "review-release > review")


if __name__ == "__main__":
    unittest.main()
