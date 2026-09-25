import unittest
from pathlib import Path

from tests.fakes import FakeSupervisor
from workflow_cockpit.engine.supervisor import ProcessCondition, StdinPolicy
from workflow_cockpit.services.graph import WorkflowDefinitionParser
from workflow_cockpit.services.run_state import RunStateData
from workflow_cockpit.session.resume import (
    ResumeCoordinator,
    ResumeError,
    ResumeState,
)

EXECUTABLE = Path("/usr/bin/specify")

GRAPH = WorkflowDefinitionParser().parse(
    (
        {"id": "prepare", "command": "demo.prepare"},
        {"id": "review", "type": "gate", "message": "Review", "options": ["approve"]},
        {"id": "finish", "command": "demo.finish"},
    )
)

NESTED_GRAPH = WorkflowDefinitionParser().parse(
    (
        {"id": "prepare", "command": "demo.prepare"},
        {
            "id": "loop",
            "type": "while",
            "steps": [
                {"id": "review", "type": "gate", "message": "Review", "options": ["approve"]}
            ],
        },
    )
)


def condition(live=False, reaped=True, aborting=False, stdin_pty=False) -> ProcessCondition:
    return ProcessCondition(
        live=live, exit_code=None, reaped=reaped, aborting=aborting, stdin_pty=stdin_pty
    )


def failed_state(step="review") -> RunStateData:
    return RunStateData(status="failed", current_step_id=step)


class ResumeCoordinatorTests(unittest.TestCase):
    def make(self, *, graph=GRAPH, adopted=True, read_only=False, stdin=StdinPolicy.PTY):
        supervisor = FakeSupervisor()
        supervisor.bind_existing("run-1")
        coordinator = ResumeCoordinator(
            graph=graph,
            supervisor=supervisor,
            executable=EXECUTABLE,
            adopted=adopted,
            read_only=read_only,
            clock=lambda: 10.0,
            stdin=stdin,
        )
        return coordinator, supervisor

    def test_project_returns_none_unless_persisted_failed(self):
        coordinator, _ = self.make()
        for status in ("paused", "running", "completed", "aborted", "initializing"):
            with self.subTest(status=status):
                self.assertIsNone(
                    coordinator.project(
                        state=RunStateData(status=status, current_step_id="review"),
                        run_id="run-1",
                        condition=condition(),
                    )
                )

    def test_project_names_step_and_mints_exactly_one_token(self):
        coordinator, _ = self.make()
        state = failed_state()
        first = coordinator.project(state=state, run_id="run-1", condition=condition())
        second = coordinator.project(state=state, run_id="run-1", condition=condition())
        self.assertTrue(first.available)
        self.assertEqual(first.step_id, "review")
        self.assertEqual(first.step_label, "review")
        self.assertFalse(first.nested)
        self.assertEqual(first.parent_label, "")
        self.assertIsNotNone(first.token)
        self.assertEqual(first.token, second.token)

    def test_project_marks_nested_step_and_parent(self):
        coordinator, _ = self.make(graph=NESTED_GRAPH)
        decision = coordinator.project(
            state=failed_state("review"), run_id="run-1", condition=condition()
        )
        self.assertTrue(decision.nested)
        self.assertEqual(decision.parent_label, "loop")
        self.assertEqual(decision.step_label, "review")

    def test_project_unavailable_when_read_only_or_not_adopted(self):
        for kwargs in ({"read_only": True}, {"adopted": False}):
            with self.subTest(**kwargs):
                coordinator, _ = self.make(**kwargs)
                decision = coordinator.project(
                    state=failed_state(), run_id="run-1", condition=condition()
                )
                self.assertFalse(decision.available)
                self.assertIsNone(decision.token)

    def test_submit_issues_exactly_one_bare_resume_and_consumes_token(self):
        coordinator, supervisor = self.make()
        state = failed_state()
        decision = coordinator.project(state=state, run_id="run-1", condition=condition())
        coordinator.submit(token=decision.token, state=state, run_id="run-1", condition=condition())
        self.assertEqual(len(supervisor.resume_calls), 1)
        run_id, argv = supervisor.resume_calls[0]
        self.assertEqual(run_id, "run-1")
        self.assertEqual(argv, [str(EXECUTABLE), "workflow", "resume", "run-1"])
        self.assertEqual(argv[1:4], ["workflow", "resume", "run-1"])
        self.assertNotIn("-i", argv)
        self.assertEqual(supervisor.resume_stdin, [StdinPolicy.PTY])
        # While the resumed child is live the consumed attempt yields no token.
        live = condition(live=True, reaped=False)
        consumed = coordinator.project(state=state, run_id="run-1", condition=live)
        self.assertIsNone(consumed.token)

    def test_two_rapid_submits_write_once(self):
        coordinator, supervisor = self.make()
        state = failed_state()
        decision = coordinator.project(state=state, run_id="run-1", condition=condition())
        coordinator.submit(token=decision.token, state=state, run_id="run-1", condition=condition())
        with self.assertRaises(ResumeError):
            coordinator.submit(token=decision.token, state=state, run_id="run-1", condition=condition())
        self.assertEqual(len(supervisor.resume_calls), 1)

    def test_absent_or_stale_token_is_refused_without_write(self):
        coordinator, supervisor = self.make()
        state = failed_state()
        with self.assertRaises(ResumeError):
            coordinator.submit(token=None, state=state, run_id="run-1", condition=condition())
        with self.assertRaises(ResumeError):
            coordinator.submit(token="stale", state=state, run_id="run-1", condition=condition())
        self.assertEqual(supervisor.resume_calls, [])

    def test_status_outside_eligibility_is_refused_without_write(self):
        coordinator, supervisor = self.make()
        state = failed_state()
        coordinator.project(state=state, run_id="run-1", condition=condition())
        for status in ("running", "completed", "aborted"):
            with self.subTest(status=status):
                with self.assertRaises(ResumeError):
                    coordinator.submit(
                        token="anything",
                        state=RunStateData(status=status, current_step_id="review"),
                        run_id="run-1",
                        condition=condition(),
                    )
        self.assertEqual(supervisor.resume_calls, [])

    def test_not_written_releases_reservation_and_stays_resumable(self):
        coordinator, supervisor = self.make()
        state = failed_state()
        decision = coordinator.project(state=state, run_id="run-1", condition=condition())
        supervisor.resume_error = "spawn failed"
        with self.assertRaises(ResumeError):
            coordinator.submit(token=decision.token, state=state, run_id="run-1", condition=condition())
        self.assertEqual(supervisor.resume_calls, [])
        supervisor.resume_error = ""
        retry = coordinator.project(state=state, run_id="run-1", condition=condition())
        self.assertEqual(retry.token, decision.token)
        coordinator.submit(token=retry.token, state=state, run_id="run-1", condition=condition())
        self.assertEqual(len(supervisor.resume_calls), 1)

    def test_advancing_status_clears_the_consumed_attempt(self):
        coordinator, _ = self.make()
        state = failed_state()
        decision = coordinator.project(state=state, run_id="run-1", condition=condition())
        coordinator.submit(token=decision.token, state=state, run_id="run-1", condition=condition())
        self.assertIsNone(
            coordinator.project(
                state=RunStateData(status="completed", current_step_id="finish"),
                run_id="run-1",
                condition=condition(),
            )
        )
        # A later fresh failure mints a new token and a new attempt.
        again = coordinator.project(state=state, run_id="run-1", condition=condition())
        self.assertIsNotNone(again.token)
        self.assertNotEqual(again.token, decision.token)

    def test_reaped_failure_mints_a_fresh_token(self):
        coordinator, supervisor = self.make()
        state = failed_state()
        decision = coordinator.project(state=state, run_id="run-1", condition=condition())
        coordinator.submit(token=decision.token, state=state, run_id="run-1", condition=condition())
        supervisor.finish(exit_code=1)
        reaped = coordinator.project(state=state, run_id="run-1", condition=condition(live=False, reaped=True))
        self.assertTrue(reaped.available)
        self.assertIsNotNone(reaped.token)
        self.assertNotEqual(reaped.token, decision.token)
        self.assertIsNotNone(coordinator._attempt)
        self.assertEqual(coordinator._attempt.state, ResumeState.READY)


if __name__ == "__main__":
    unittest.main()
