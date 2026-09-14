import unittest
from pathlib import Path

from tests.support import FakeSupervisor
from workflow_cockpit.engine.pty_session import WriteOutcome
from workflow_cockpit.engine.supervisor import ProcessCondition, StdinPolicy
from workflow_cockpit.services.graph import WorkflowDefinitionParser
from workflow_cockpit.services.run_state import RunStateData
from workflow_cockpit.services.snapshot import GateState
from workflow_cockpit.session.gate_decision import (
    GateDecisionCoordinator,
    GateDecisionError,
    validate_shape,
)

STRUCTURED_STEPS = (
    {"id": "prepare", "command": "demo.prepare"},
    {
        "id": "review",
        "type": "gate",
        "message": "Approve the plan?",
        "options": ["approve", "reject"],
        "verdict_input": "decision",
        "on_reject": "retry",
    },
    {"id": "finish", "command": "demo.finish"},
)

INTERACTIVE_STEPS = (
    {"id": "prepare", "command": "demo.prepare"},
    {
        "id": "review",
        "type": "gate",
        "message": "Approve the plan?",
        "options": ["approve", "reject"],
        "on_reject": "skip",
    },
    {"id": "finish", "command": "demo.finish"},
)


def graph_for(steps):
    return WorkflowDefinitionParser().parse(steps)


def paused_state(**kwargs) -> RunStateData:
    output = kwargs.pop(
        "output",
        {"message": "Approve the plan?", "options": ["approve", "reject"], "on_reject": "retry"},
    )
    return RunStateData(
        status=kwargs.pop("status", "paused"),
        current_step_id=kwargs.pop("current_step_id", "review"),
        step_results={"review": {"type": "gate", "output": output}},
        complete=True,
        **kwargs,
    )


def live_state(**kwargs) -> RunStateData:
    return RunStateData(
        status=kwargs.pop("status", "running"),
        current_step_id=kwargs.pop("current_step_id", "review"),
        step_results={},
        complete=True,
        **kwargs,
    )


def condition(*, live=False, stdin_pty=False, reaped=True, aborting=False) -> ProcessCondition:
    return ProcessCondition(
        live=live,
        exit_code=None if live else 0,
        reaped=reaped,
        aborting=aborting,
        stdin_pty=stdin_pty,
    )


class GateCoordinatorStructuredTests(unittest.TestCase):
    def setUp(self):
        self.supervisor = FakeSupervisor()
        self.supervisor.run_id = "run-1"
        self.graph = graph_for(STRUCTURED_STEPS)

    def make(self, *, version="1.0.6", clock=None, watch=10.0):
        return GateDecisionCoordinator(
            graph=self.graph,
            supervisor=self.supervisor,
            executable=Path("/usr/bin/specify"),
            version=version,
            clock=clock or (lambda: 100.0),
            watch_seconds=watch,
        )

    def test_structured_gate_is_ready_and_selectable(self):
        gate = self.make().project(
            state=paused_state(), run_id="run-1", condition=condition(), gate_attempt=1
        )
        self.assertEqual(gate.state, GateState.READY)
        self.assertTrue(gate.selectable)
        self.assertTrue(gate.token)
        self.assertEqual(gate.options, ("approve", "reject"))

    def test_structured_submission_resumes_and_then_reads_submitted(self):
        coordinator = self.make()
        gate = coordinator.project(
            state=paused_state(), run_id="run-1", condition=condition(), gate_attempt=1
        )
        coordinator.submit(
            choice="approve",
            token=gate.token,
            state=paused_state(),
            run_id="run-1",
            condition=condition(),
            gate_attempt=1,
        )
        run_id, argv = self.supervisor.resume_calls[-1]
        self.assertEqual(run_id, "run-1")
        self.assertIn("decision=approve", argv)
        self.assertEqual(self.supervisor.writes, [])
        after = coordinator.project(
            state=paused_state(), run_id="run-1", condition=condition(), gate_attempt=1
        )
        self.assertEqual(after.state, GateState.SUBMITTED)
        self.assertFalse(after.selectable)
        self.assertIn("authoritative", after.acknowledged)

    def test_stale_token_is_rejected_before_write(self):
        coordinator = self.make()
        coordinator.project(
            state=paused_state(), run_id="run-1", condition=condition(), gate_attempt=1
        )
        with self.assertRaisesRegex(GateDecisionError, "stale"):
            coordinator.submit(
                choice="approve",
                token="not-the-token",
                state=paused_state(),
                run_id="run-1",
                condition=condition(),
                gate_attempt=1,
            )
        self.assertEqual(self.supervisor.resume_calls, [])

    def test_malformed_evidence_is_blocked(self):
        gate = self.make().project(
            state=paused_state(output={"message": "Review"}),
            run_id="run-1",
            condition=condition(),
            gate_attempt=1,
        )
        self.assertEqual(gate.state, GateState.BLOCKED)
        self.assertIn("options", gate.reason)

    def test_updated_at_change_alone_never_permits_resend(self):
        coordinator = self.make()
        gate = coordinator.project(
            state=paused_state(), run_id="run-1", condition=condition(), gate_attempt=1
        )
        coordinator.submit(
            choice="approve",
            token=gate.token,
            state=paused_state(),
            run_id="run-1",
            condition=condition(),
            gate_attempt=1,
        )
        changed = paused_state(updated_at="2099-01-01T00:00:00+00:00")
        after = coordinator.project(
            state=changed, run_id="run-1", condition=condition(), gate_attempt=1
        )
        self.assertEqual(after.state, GateState.SUBMITTED)
        with self.assertRaises(GateDecisionError):
            coordinator.submit(
                choice="reject",
                token=gate.token,
                state=changed,
                run_id="run-1",
                condition=condition(),
                gate_attempt=1,
            )

    def test_new_gate_attempt_after_advancement_is_ready_again(self):
        coordinator = self.make()
        gate = coordinator.project(
            state=paused_state(), run_id="run-1", condition=condition(), gate_attempt=1
        )
        coordinator.submit(
            choice="reject",
            token=gate.token,
            state=paused_state(),
            run_id="run-1",
            condition=condition(),
            gate_attempt=1,
        )
        # A retry re-executes the gate: the step-started attempt count advances.
        retried = coordinator.project(
            state=paused_state(), run_id="run-1", condition=condition(), gate_attempt=2
        )
        self.assertEqual(retried.state, GateState.READY)
        self.assertNotEqual(retried.token, gate.token)

    def test_leaving_the_gate_clears_the_attempt(self):
        coordinator = self.make()
        coordinator.project(
            state=paused_state(), run_id="run-1", condition=condition(), gate_attempt=1
        )
        moved = RunStateData(status="completed", current_step_id="finish", complete=True)
        self.assertIsNone(
            coordinator.project(state=moved, run_id="run-1", condition=condition(), gate_attempt=0)
        )


class GateCoordinatorInteractiveTests(unittest.TestCase):
    def setUp(self):
        self.supervisor = FakeSupervisor()
        self.supervisor.run_id = "run-1"
        self.supervisor.stdin_policy = StdinPolicy.PTY
        self.graph = graph_for(INTERACTIVE_STEPS)
        self.now = [100.0]

    def make(self, *, version="1.0.6"):
        return GateDecisionCoordinator(
            graph=self.graph,
            supervisor=self.supervisor,
            executable=Path("/usr/bin/specify"),
            version=version,
            clock=lambda: self.now[0],
            watch_seconds=10.0,
        )

    def _live(self):
        return condition(live=True, stdin_pty=True, reaped=False)

    def test_interactive_gate_uses_declared_values_and_is_ready(self):
        gate = self.make().project(
            state=live_state(), run_id="run-1", condition=self._live(), gate_attempt=1
        )
        self.assertEqual(gate.state, GateState.READY)
        self.assertEqual(gate.message, "Approve the plan?")
        self.assertEqual(gate.options, ("approve", "reject"))

    def test_interactive_submission_writes_index_once(self):
        coordinator = self.make()
        gate = coordinator.project(
            state=live_state(), run_id="run-1", condition=self._live(), gate_attempt=1
        )
        coordinator.submit(
            choice="reject",
            token=gate.token,
            state=live_state(),
            run_id="run-1",
            condition=self._live(),
            gate_attempt=1,
        )
        self.assertEqual(self.supervisor.writes, [b"2\n"])
        after = coordinator.project(
            state=live_state(), run_id="run-1", condition=self._live(), gate_attempt=1
        )
        self.assertEqual(after.state, GateState.SUBMITTED)
        with self.assertRaises(GateDecisionError):
            coordinator.submit(
                choice="approve",
                token=gate.token,
                state=live_state(),
                run_id="run-1",
                condition=self._live(),
                gate_attempt=1,
            )
        self.assertEqual(self.supervisor.writes, [b"2\n"])

    def test_no_live_process_blocks_with_abort_only(self):
        gate = self.make().project(
            state=live_state(), run_id="run-1", condition=condition(), gate_attempt=1
        )
        self.assertEqual(gate.state, GateState.BLOCKED)
        self.assertIn("No live engine process", gate.reason)

    def test_missing_pty_stdin_blocks(self):
        gate = self.make().project(
            state=live_state(),
            run_id="run-1",
            condition=condition(live=True, stdin_pty=False, reaped=False),
            gate_attempt=1,
        )
        self.assertEqual(gate.state, GateState.BLOCKED)
        self.assertIn("interactive prompt", gate.reason)

    def test_unverified_version_blocks(self):
        gate = self.make(version="1.0.5").project(
            state=live_state(), run_id="run-1", condition=self._live(), gate_attempt=1
        )
        self.assertEqual(gate.state, GateState.BLOCKED)
        self.assertIn("not verified", gate.reason)

    def test_watch_expiry_marks_unverified_and_stays_consumed(self):
        coordinator = self.make()
        gate = coordinator.project(
            state=live_state(), run_id="run-1", condition=self._live(), gate_attempt=1
        )
        coordinator.submit(
            choice="approve",
            token=gate.token,
            state=live_state(),
            run_id="run-1",
            condition=self._live(),
            gate_attempt=1,
        )
        self.now[0] += 10.0
        after = coordinator.project(
            state=live_state(), run_id="run-1", condition=self._live(), gate_attempt=1
        )
        self.assertEqual(after.state, GateState.UNVERIFIED)
        self.assertFalse(after.selectable)
        with self.assertRaises(GateDecisionError):
            coordinator.submit(
                choice="reject",
                token=gate.token,
                state=live_state(),
                run_id="run-1",
                condition=self._live(),
                gate_attempt=1,
            )
        self.assertEqual(self.supervisor.writes, [b"1\n"])

    def test_not_written_releases_reservation(self):
        self.supervisor.write_result = WriteOutcome.NOT_WRITTEN
        coordinator = self.make()
        gate = coordinator.project(
            state=live_state(), run_id="run-1", condition=self._live(), gate_attempt=1
        )
        with self.assertRaises(GateDecisionError):
            coordinator.submit(
                choice="approve",
                token=gate.token,
                state=live_state(),
                run_id="run-1",
                condition=self._live(),
                gate_attempt=1,
            )
        after = coordinator.project(
            state=live_state(), run_id="run-1", condition=self._live(), gate_attempt=1
        )
        self.assertEqual(after.state, GateState.READY)
        self.assertEqual(self.supervisor.writes, [])

    def test_uncertain_write_is_consumed_and_unverified(self):
        self.supervisor.write_result = WriteOutcome.UNCERTAIN
        coordinator = self.make()
        gate = coordinator.project(
            state=live_state(), run_id="run-1", condition=self._live(), gate_attempt=1
        )
        coordinator.submit(
            choice="approve",
            token=gate.token,
            state=live_state(),
            run_id="run-1",
            condition=self._live(),
            gate_attempt=1,
        )
        after = coordinator.project(
            state=live_state(), run_id="run-1", condition=self._live(), gate_attempt=1
        )
        self.assertEqual(after.state, GateState.UNVERIFIED)
        self.assertFalse(after.selectable)

    def test_advancement_clears_interactive_attempt(self):
        coordinator = self.make()
        gate = coordinator.project(
            state=live_state(), run_id="run-1", condition=self._live(), gate_attempt=1
        )
        coordinator.submit(
            choice="approve",
            token=gate.token,
            state=live_state(),
            run_id="run-1",
            condition=self._live(),
            gate_attempt=1,
        )
        completed = RunStateData(status="completed", current_step_id="finish", complete=True)
        self.assertIsNone(
            coordinator.project(
                state=completed, run_id="run-1", condition=condition(), gate_attempt=0
            )
        )


class ShapeValidationTests(unittest.TestCase):
    def test_structured_only_keeps_devnull_stdin(self):
        support = validate_shape(graph_for(STRUCTURED_STEPS), "1.0.6")
        self.assertTrue(support.ok)
        self.assertEqual(support.stdin, StdinPolicy.DEVNULL)

    def test_verified_interactive_uses_pty_stdin(self):
        support = validate_shape(graph_for(INTERACTIVE_STEPS), "1.0.6")
        self.assertTrue(support.ok)
        self.assertEqual(support.stdin, StdinPolicy.PTY)

    def test_unverified_version_is_rejected(self):
        support = validate_shape(graph_for(INTERACTIVE_STEPS), "1.0.5")
        self.assertFalse(support.ok)
        self.assertIn("not verified", support.error)

    def test_mixed_gates_are_rejected(self):
        steps = (
            *INTERACTIVE_STEPS[:2],
            {
                "id": "second",
                "type": "gate",
                "message": "Again?",
                "options": ["approve", "reject"],
                "verdict_input": "decision",
            },
        )
        support = validate_shape(graph_for(steps), "1.0.6")
        self.assertFalse(support.ok)
        self.assertIn("mix", support.error)

    def test_retry_is_rejected_for_interactive(self):
        steps = list(INTERACTIVE_STEPS)
        steps[1] = {**steps[1], "on_reject": "retry"}
        support = validate_shape(graph_for(steps), "1.0.6")
        self.assertFalse(support.ok)
        self.assertIn("retry", support.error)

    def test_dynamic_values_are_rejected(self):
        steps = list(INTERACTIVE_STEPS)
        steps[1] = {**steps[1], "message": "Approve {{ inputs.spec }}?"}
        support = validate_shape(graph_for(steps), "1.0.6")
        self.assertFalse(support.ok)
        self.assertIn("dynamic", support.error)

    def test_parallel_gate_is_rejected(self):
        steps = (
            {
                "id": "each",
                "type": "fan-out",
                "over": "items",
                "step": {
                    "id": "review",
                    "type": "gate",
                    "message": "Approve?",
                    "options": ["approve", "reject"],
                },
            },
        )
        support = validate_shape(graph_for(steps), "1.0.6")
        self.assertFalse(support.ok)
        self.assertIn("fan-out", support.error)

    def test_missing_options_is_rejected(self):
        steps = (
            {"id": "review", "type": "gate", "message": "Approve?", "on_reject": "abort"},
        )
        support = validate_shape(graph_for(steps), "1.0.6")
        self.assertFalse(support.ok)
        self.assertIn("no options", support.error)


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
