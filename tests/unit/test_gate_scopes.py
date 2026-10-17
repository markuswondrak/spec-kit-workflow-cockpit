"""Gate snapshots for a composed run come from the active node, per scope."""

import unittest

from tests.composition_support import coordinator, state_data
from tests.fixtures import composition as fx
from workflow_cockpit.engine.supervisor import ProcessCondition
from workflow_cockpit.services.snapshot import GateState


def condition(*, live=False, stdin_pty=False, reaped=True, aborting=False) -> ProcessCondition:
    return ProcessCondition(
        live=live,
        exit_code=None if live else 0,
        reaped=reaped,
        aborting=aborting,
        stdin_pty=stdin_pty,
    )


class ComposedGateTests(unittest.TestCase):
    def project(self, scenario, *, gate_attempt=1, read_only=False):
        gate, _supervisor = coordinator(read_only=read_only)
        snapshot = gate.project(
            state=state_data(scenario),
            run_id="run-1",
            condition=condition(),
            gate_attempt=gate_attempt,
        )
        return snapshot, gate

    def test_child_gate_shows_its_own_message_options_and_scope(self):
        gate, _ = self.project("reference")
        self.assertEqual(gate.state, GateState.READY)
        self.assertTrue(gate.selectable)
        self.assertEqual(gate.message, "Approve the release notes?")
        self.assertEqual(gate.options, ("approve", "reject"))
        self.assertEqual(gate.display_scope_path, "review-release > review")
        self.assertEqual(gate.root_input, "approval")

    def test_colliding_root_step_is_not_shown(self):
        gate, _ = self.project("collision")
        self.assertEqual(gate.step_id, "review")
        self.assertEqual(gate.display_scope_path, "review-release > review")
        # The root gate's evidence is "Approve the root release?"; the child's is
        # the release-notes gate, so the root result was not consulted.
        self.assertEqual(gate.message, "Approve the release notes?")
        self.assertEqual(gate.options, ("approve", "reject"))

    def test_gate_two_calls_deep_names_both_calls(self):
        gate, _ = self.project("depth2")
        self.assertEqual(gate.display_scope_path, "middle-call > inner-call > deep-review")
        self.assertEqual(gate.root_input, "approval")
        self.assertEqual(gate.options, ("approve", "reject"))

    def test_same_named_call_in_another_scope_does_not_change_the_traced_input(self):
        # A finished root call named like the nested ``inner-call`` comes first in
        # tree order; the chain must still follow the calls that enclose the gate.
        from workflow_cockpit.services.execution_tree import parse as parse_execution

        raw = fx.with_earlier_decoy_call(
            fx.load_state("depth2"), "inner-call", {"approval": "{{ inputs.decoy }}"}
        )
        gate, _ = coordinator()
        snapshot = gate.project(
            state=state_data("depth2", execution=parse_execution(raw)),
            run_id="run-1",
            condition=condition(),
            gate_attempt=1,
        )
        self.assertEqual(snapshot.state, GateState.READY)
        self.assertEqual(snapshot.root_input, "approval")

    def test_root_gate_has_no_scope_line(self):
        gate, _ = self.project("dynamic-target")
        self.assertEqual(gate.display_scope_path, "pre-gate")
        self.assertFalse(gate.nested)
        self.assertEqual(gate.root_input, "go")

    def test_interactive_gate_under_a_fanout_is_abort_only(self):
        gate, _ = self.project("fanout")
        self.assertEqual(gate.state, GateState.BLOCKED)
        self.assertEqual(gate.reason_kind, "undecidable")
        self.assertFalse(gate.selectable)
        self.assertIsNone(gate.token)
        self.assertIn("fan > 0 > notes > review", gate.reason)

    def test_verdict_gate_under_a_fanout_is_abort_only(self):
        gate, _ = self.project("fanout-verdict")
        self.assertEqual(gate.state, GateState.BLOCKED)
        self.assertEqual(gate.reason_kind, "undecidable")
        self.assertIn("verdict_input", gate.reason)

    def test_unresolved_position_is_abort_only_and_never_guesses(self):
        from workflow_cockpit.services.execution_tree import parse as parse_execution

        gate, _ = coordinator()
        # A tree whose persisted position disagrees with its active node yields
        # no guessed gate: only the named Abort-only state.
        raw = fx.with_current_step_id(fx.load_state("reference"), "publish")
        snapshot = gate.project(
            state=state_data("reference", execution=parse_execution(raw)),
            run_id="run-1",
            condition=condition(),
            gate_attempt=1,
        )
        self.assertEqual(snapshot.state, GateState.BLOCKED)
        self.assertEqual(snapshot.reason_kind, "unresolved")
        self.assertIn("unresolved", snapshot.reason.lower())

    def test_unsupported_version_is_abort_only(self):
        from workflow_cockpit.services.execution_tree import parse as parse_execution

        state = fx.with_version(fx.load_state("reference"), 3)
        gate, _ = coordinator()
        snapshot = gate.project(
            state=state_data("reference", execution=parse_execution(state)),
            run_id="run-1",
            condition=condition(),
            gate_attempt=1,
        )
        self.assertEqual(snapshot.state, GateState.BLOCKED)
        self.assertEqual(snapshot.reason_kind, "unsupported-version")
        self.assertIn("3", snapshot.reason)

    def test_read_only_mode_blocks_the_child_gate(self):
        gate, _ = self.project("reference", read_only=True)
        self.assertEqual(gate.state, GateState.BLOCKED)
        self.assertIn("View-only", gate.reason)

    def test_submission_uses_the_traced_root_input(self):
        gate, supervisor = coordinator()
        state = state_data("reference")
        snapshot = gate.project(state=state, run_id="run-1", condition=condition(), gate_attempt=1)
        gate.submit(
            choice="approve",
            token=snapshot.token,
            state=state,
            run_id="run-1",
            condition=condition(),
            gate_attempt=1,
        )
        run_id, argv = supervisor.resume_calls[-1]
        self.assertEqual(run_id, "run-1")
        self.assertIn("approval=approve", argv)
        self.assertEqual(supervisor.writes, [])

    def test_colliding_gate_submission_still_uses_the_root_name(self):
        gate, supervisor = coordinator()
        state = state_data("collision")
        snapshot = gate.project(state=state, run_id="run-1", condition=condition(), gate_attempt=1)
        gate.submit(
            choice="reject",
            token=snapshot.token,
            state=state,
            run_id="run-1",
            condition=condition(),
            gate_attempt=1,
        )
        _run_id, argv = supervisor.resume_calls[-1]
        self.assertIn("approval=reject", argv)
        self.assertNotIn("root_approval=reject", argv)

    def test_write_once_holds_per_scope_occurrence(self):
        gate, supervisor = coordinator()
        first = gate.project(
            state=state_data("loop-paused"), run_id="run-1", condition=condition(), gate_attempt=1
        )
        gate.submit(
            choice="approve",
            token=first.token,
            state=state_data("loop-paused"),
            run_id="run-1",
            condition=condition(),
            gate_attempt=1,
        )
        self.assertEqual(len(supervisor.resume_calls), 1)
        after = gate.project(
            state=state_data("loop-paused"), run_id="run-1", condition=condition(), gate_attempt=1
        )
        self.assertEqual(after.state, GateState.SUBMITTED)
        self.assertFalse(after.selectable)

    def test_a_gate_in_another_scope_is_a_fresh_attempt(self):
        # The child ``review`` is decided; the root ``review`` shares its bare id
        # but is a different scope, so it mints its own token and stays READY.
        from workflow_cockpit.services.execution_tree import parse as parse_execution

        gate, supervisor = coordinator()
        child_state = state_data("collision")
        child = gate.project(state=child_state, run_id="run-1", condition=condition(), gate_attempt=1)
        gate.submit(
            choice="approve",
            token=child.token,
            state=child_state,
            run_id="run-1",
            condition=condition(),
            gate_attempt=1,
        )
        raw = fx.with_root_gate_paused(fx.load_state("collision"), "review")
        root = gate.project(
            state=state_data("collision", execution=parse_execution(raw)),
            run_id="run-1",
            condition=condition(),
            gate_attempt=1,
        )
        self.assertEqual(root.state, GateState.READY)
        self.assertEqual(root.display_scope_path, "review")
        self.assertEqual(root.root_input, "root_approval")
        self.assertNotEqual(root.token, child.token)
        self.assertEqual(len(supervisor.resume_calls), 1)

    def test_a_settled_run_projects_no_gate(self):
        gate, _ = coordinator()
        snapshot = gate.project(
            state=state_data("loop-twice"), run_id="run-1", condition=condition(), gate_attempt=1
        )
        self.assertIsNone(snapshot)


if __name__ == "__main__":
    unittest.main()
