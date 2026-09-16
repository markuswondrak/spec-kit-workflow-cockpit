import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from workflow_cockpit.services.graph import WorkflowDefinitionParser, resolve_declared_id
from workflow_cockpit.services.log_aggregator import RunLogAggregator, StepTiming
from workflow_cockpit.services.projection import GraphProjector
from workflow_cockpit.services.run_state import RunStateData

WORKFLOW = (
    {"id": "prepare", "command": "demo.prepare"},
    {
        "id": "check",
        "type": "if",
        "condition": "{{ inputs.enabled }}",
        "then": [{"id": "then-step", "command": "demo.then"}],
        "else": [{"id": "else-step", "command": "demo.else"}],
    },
    {
        "id": "route",
        "type": "switch",
        "expression": "{{ inputs.route }}",
        "cases": {"fast": [{"id": "fast-step", "command": "demo.fast"}]},
        "default": [{"id": "fallback", "command": "demo.default"}],
    },
    {
        "id": "retry",
        "type": "while",
        "condition": "{{ inputs.retry }}",
        "max_iterations": 3,
        "steps": [{"id": "verify", "command": "demo.verify"}],
    },
    {
        "id": "fan",
        "type": "fan-out",
        "items": "{{ inputs.items }}",
        "step": {"id": "worker", "command": "demo.worker"},
    },
    {"id": "join", "type": "fan-in", "wait_for": ["fan", "retry"]},
    {"id": "review", "type": "gate", "message": "Review", "options": ["approve", "reject"]},
)


class GraphParserTests(unittest.TestCase):
    def setUp(self):
        self.graph = WorkflowDefinitionParser().parse(WORKFLOW)

    def test_parses_declared_branches_loops_fanout_and_join(self):
        self.assertEqual(
            [node.id for node in self.graph.nodes],
            [
                "prepare",
                "check",
                "then-step",
                "else-step",
                "route",
                "fast-step",
                "fallback",
                "retry",
                "verify",
                "fan",
                "worker",
                "join",
                "review",
            ],
        )
        self.assertTrue(self.graph.by_id["review"].gate)
        self.assertTrue(self.graph.by_id["worker"].is_template)
        kinds = {(edge.source, edge.target, edge.kind, edge.label) for edge in self.graph.edges}
        self.assertIn(("check", "then-step", "branch", "then"), kinds)
        self.assertIn(("check", "else-step", "branch", "else"), kinds)
        self.assertIn(("then-step", "route", "sequence", ""), kinds)
        self.assertIn(("else-step", "route", "sequence", ""), kinds)
        self.assertIn(("verify", "retry", "loop", "repeat"), kinds)
        self.assertIn(("retry", "fan", "sequence", ""), kinds)
        self.assertIn(("fan", "worker", "fanout", "each"), kinds)
        self.assertIn(("fan", "join", "join", "join"), kinds)
        self.assertIn(("fast-step", "retry", "sequence", ""), kinds)
        self.assertIn(("fallback", "retry", "sequence", ""), kinds)
        # Branch containers never fall through themselves.
        self.assertNotIn(("check", "route", "sequence", ""), kinds)
        self.assertNotIn(("route", "retry", "sequence", ""), kinds)

    def test_if_without_else_falls_through_from_container(self):
        graph = WorkflowDefinitionParser().parse(
            (
                {"id": "check", "type": "if", "condition": "true", "then": [{"id": "then-step"}]},
                {"id": "after"},
            )
        )
        kinds = {(edge.source, edge.target, edge.kind) for edge in graph.edges}
        self.assertIn(("then-step", "after", "sequence"), kinds)
        self.assertIn(("check", "after", "sequence"), kinds)

    def test_maps_engine_generated_runtime_ids(self):
        ids = self.graph.declared_ids
        self.assertEqual(resolve_declared_id("retry:verify:2", ids), "verify")
        self.assertEqual(resolve_declared_id("fan:worker:0", ids), "worker")
        self.assertIsNone(resolve_declared_id("unknown:step:0", ids))

    def test_numeric_index_does_not_shadow_declared_step(self):
        graph = WorkflowDefinitionParser().parse(({"id": "2"}, {"id": "verify"}))
        self.assertEqual(resolve_declared_id("retry:verify:2", graph.declared_ids), "verify")


class LogProjectionTests(unittest.TestCase):
    def setUp(self):
        self.graph = WorkflowDefinitionParser().parse(WORKFLOW)
        self.now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)

    def test_projects_status_attempts_active_path_and_durations(self):
        timing_start = self.now - timedelta(seconds=8)
        projection = GraphProjector().project(
            self.graph,
            RunStateData(
                status="paused",
                current_step_id="review",
                step_results={
                    "prepare": {"status": "completed"},
                    "retry:verify:1": {"status": "completed"},
                },
            ),
            {
                "prepare": StepTiming(1, timing_start, timing_start + timedelta(seconds=3), "completed"),
                "verify": StepTiming(2, timing_start, timing_start + timedelta(seconds=5), "completed"),
            },
            now=self.now,
        )
        nodes = projection.by_id
        self.assertEqual(nodes["prepare"].status, "completed")
        self.assertEqual(nodes["verify"].attempts, 2)
        self.assertEqual(nodes["verify"].duration_seconds, 5)
        self.assertEqual(nodes["review"].status, "paused")
        self.assertTrue(nodes["review"].active)

    def test_next_node_skips_untaken_branch(self):
        projection = GraphProjector().project(
            self.graph,
            RunStateData(
                status="running",
                current_step_id="then-step",
                step_results={
                    "prepare": {"status": "completed"},
                    "check": {"status": "completed"},
                    "then-step": {"status": "completed"},
                },
            ),
        )
        self.assertEqual(projection.next_node_id, "route")

    def test_next_node_ignores_unrun_loop_body(self):
        projection = GraphProjector().project(
            self.graph,
            RunStateData(
                status="running",
                current_step_id="fan",
                step_results={
                    "prepare": {"status": "completed"},
                    "check": {"status": "completed"},
                    "then-step": {"status": "completed"},
                    "route": {"status": "completed"},
                    "fast-step": {"status": "completed"},
                    "retry": {"status": "completed"},
                },
            ),
        )
        self.assertNotEqual(projection.next_node_id, "verify")

    def test_incremental_log_aggregation_handles_partial_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            aggregate = RunLogAggregator(self.graph.declared_ids)
            path.write_text(
                '{"event":"step_started","step_id":"retry:verify:1","timestamp":"2026-09-13T12:00:00+00:00"}',
                encoding="utf-8",
            )
            self.assertEqual(aggregate.update(path), {})
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    '\n{"event":"step_completed","step_id":"retry:verify:1",'
                    '"status":"completed","timestamp":"2026-09-13T12:00:04+00:00"}\n'
                    '{"event":"step_started","step_id":"retry:verify:2",'
                    '"timestamp":"2026-09-13T12:00:05+00:00"}\n'
                )
            timing = aggregate.update(path)["verify"]
            self.assertEqual(timing.attempts, 2)
            self.assertEqual(timing.status, "running")
            self.assertEqual(timing.started_at, datetime(2026, 9, 13, 12, 0, 5, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
