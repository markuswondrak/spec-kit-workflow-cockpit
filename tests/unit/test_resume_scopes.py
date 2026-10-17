"""Resume of a composed run names the real nested step and its call."""

import unittest
from pathlib import Path

from tests.composition_support import state_data, tree_graph
from tests.fakes import FakeSupervisor
from workflow_cockpit.engine.supervisor import ProcessCondition
from workflow_cockpit.session.resume import ResumeCoordinator


def condition(*, live=False, reaped=True) -> ProcessCondition:
    return ProcessCondition(
        live=live,
        exit_code=None if live else 0,
        reaped=reaped,
        aborting=False,
        stdin_pty=False,
    )


def coordinator(scenario: str, *, adopted: bool = True):
    _tree, graph = tree_graph(scenario)
    supervisor = FakeSupervisor()
    supervisor.run_id = "run-1"
    return (
        ResumeCoordinator(
            graph=graph,
            supervisor=supervisor,
            executable=Path("/usr/bin/specify"),
            adopted=adopted,
            clock=lambda: 100.0,
        ),
        supervisor,
    )


class ComposedResumeTests(unittest.TestCase):
    def test_resume_point_names_the_failed_child_step_and_its_call(self):
        resume, _ = coordinator("failed-child")
        decision = resume.project(
            state=state_data("failed-child"), run_id="run-1", condition=condition()
        )
        self.assertTrue(decision.available)
        self.assertEqual(decision.step_id, "boom")
        self.assertEqual(decision.step_label, "boom")
        self.assertTrue(decision.nested)
        self.assertEqual(decision.parent_label, "broken-call")

    def test_a_root_failure_stays_a_root_resume(self):
        resume, _ = coordinator("failed-child")
        state = state_data("failed-child", execution=None, current_step_id="build")
        decision = resume.project(state=state, run_id="run-1", condition=condition())
        self.assertFalse(decision.nested)
        self.assertEqual(decision.step_id, "build")

    def test_handled_call_failure_does_not_change_the_persisted_status(self):
        from tests.fixtures import composition as fx
        from workflow_cockpit.services.execution_tree import parse as parse_execution
        from workflow_cockpit.services.execution_walk import find_node

        tree = parse_execution(fx.load_state("continue-on-error"))
        call = find_node(tree, (), "broken-call")
        self.assertTrue(call.handled_failure)
        self.assertEqual(tree.run_status, "completed")
        # A completed run is not resumable and its displayed status is unchanged.
        resume, _ = coordinator("continue-on-error")
        state = state_data("continue-on-error")
        self.assertEqual(state.status, "completed")
        self.assertIsNone(resume.project(state=state, run_id="run-1", condition=condition()))

    def test_submission_issues_one_bare_resume(self):
        resume, supervisor = coordinator("failed-child")
        state = state_data("failed-child")
        decision = resume.project(state=state, run_id="run-1", condition=condition())
        resume.submit(token=decision.token, state=state, run_id="run-1", condition=condition())
        self.assertEqual(len(supervisor.resume_calls), 1)
        self.assertEqual(supervisor.resume_calls[0][0], "run-1")

    def test_read_only_never_offers_resume(self):
        resume, _ = coordinator("failed-child", adopted=False)
        state = state_data("failed-child")
        decision = resume.project(state=state, run_id="run-1", condition=condition())
        self.assertFalse(decision.available)
        self.assertIn("adopted", decision.reason)


if __name__ == "__main__":
    unittest.main()
