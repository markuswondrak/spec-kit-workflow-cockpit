import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.support import (
    FakeGit,
    FakeReviewService,
    FakeSupervisor,
    compatibility_result,
    write_registry,
    write_run,
    write_workflow,
)
from workflow_cockpit.engine.supervisor import StdinPolicy
from workflow_cockpit.services.snapshot import GateState
from workflow_cockpit.session.cockpit_session import CockpitSession, SessionError, generate_run_id
from workflow_cockpit.session.dependencies import (
    CockpitEnvironment,
    CockpitServices,
    EngineRuntime,
)

NON_VERDICT_WORKFLOW = {
    "schema_version": "1.0",
    "workflow": {"id": "demo", "name": "Demo", "version": "1.0.0", "description": "demo"},
    "inputs": {"spec": {"type": "string", "required": True}},
    "steps": [
        {"id": "prepare", "command": "demo.prepare"},
        {
            "id": "review",
            "type": "gate",
            "message": "Approve the plan?",
            "options": ["approve", "reject"],
            "on_reject": "skip",
        },
        {"id": "finish", "command": "demo.finish"},
    ],
}


def non_verdict_workflow(options):
    workflow = {**NON_VERDICT_WORKFLOW, "steps": list(NON_VERDICT_WORKFLOW["steps"])}
    workflow["steps"][1] = {**workflow["steps"][1], "options": list(options)}
    return workflow


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_workflow(self.root)
        write_registry(self.root)
        self.supervisor = FakeSupervisor()

    def tearDown(self):
        self.tmp.cleanup()

    def make_session(self, **kwargs):
        environment = CockpitEnvironment(
            self.root, compatibility_result(kwargs.pop("version", "1.0.0"))
        )
        services = replace(
            CockpitServices.for_environment(environment),
            git=kwargs.pop("git", FakeGit()),
            review_source=kwargs.pop("review_source", FakeReviewService()),
        )
        context_writer = kwargs.pop("context_writer", None)
        if context_writer is not None:
            services = replace(services, context_writer=context_writer)
        engine = replace(
            EngineRuntime.for_environment(environment, clock=kwargs.pop("clock", lambda: 10.0)),
            supervisor=self.supervisor,
        )
        return CockpitSession(environment, services=services, engine=engine)

    def test_select_and_validate(self):
        session = self.make_session()
        definition = session.select("demo")
        self.assertEqual(definition.id, "demo")
        _resolved, errors = session.validate({"spec": ""})
        self.assertIn("spec", errors)

    def test_start_allocates_collision_free_id(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        self.assertTrue(snapshot.run_id.startswith("cockpit-"))
        self.assertFalse((self.root / ".specify" / "workflows" / "runs" / snapshot.run_id).exists())
        self.assertIn("workflow", self.supervisor.started_argv)
        self.assertIn("demo", self.supervisor.started_argv)
        self.assertIs(self.supervisor.stdin_policy, StdinPolicy.DEVNULL)

    def test_start_writes_context_index(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        self.assertEqual(snapshot.context_path, ".specify/workflows/runs/current_run")
        self.assertEqual(snapshot.context_error, "")
        self.assertTrue(
            (self.root / ".specify" / "workflows" / "runs" / "current_run").is_file()
        )

    def test_context_failure_does_not_interrupt_run(self):
        class BrokenWriter:
            def write(self, **_kwargs):
                raise RuntimeError("disk full")

        session = self.make_session(context_writer=BrokenWriter())
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        self.assertTrue(snapshot.run_id.startswith("cockpit-"))
        self.assertEqual(snapshot.context_path, "")
        self.assertIn("disk full", snapshot.context_error)
        self.assertIn("disk full", session.context_error)

    def test_second_start_rejected(self):
        session = self.make_session()
        session.select("demo")
        session.start({"spec": "search"})
        with self.assertRaises(SessionError):
            session.start({"spec": "other"})

    def test_success_outcome_after_reap(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        write_run(self.root, snapshot.run_id, status="completed")
        self.supervisor.finish(exit_code=0)
        final = session.snapshot()
        self.assertIsNotNone(final.outcome)
        self.assertEqual(final.outcome.kind.value, "success")

    def test_failure_outcome_includes_persisted_cause(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        write_run(self.root, snapshot.run_id, status="failed", error="boom")
        self.supervisor.finish(exit_code=1)
        final = session.snapshot()
        self.assertEqual(final.outcome.kind.value, "failure")
        self.assertEqual(final.outcome.detail, "boom")

    def test_abort_outcome_even_when_state_paused(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        write_run(self.root, snapshot.run_id, status="paused")
        session.abort()
        final = session.snapshot()
        self.assertEqual(final.outcome.kind.value, "abort")
        self.assertEqual(self.supervisor.abort_calls, 1)

    def test_partial_state_preserves_last_good_then_recovers(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        run_id = snapshot.run_id
        write_run(self.root, run_id, status="running", current_step_id="prepare")
        good = session.snapshot()
        self.assertEqual(good.status, "running")
        self.assertFalse(good.stale)

        state_path = self.root / ".specify" / "workflows" / "runs" / run_id / "state.json"
        state_path.write_text('{"status": "run', encoding="utf-8")
        stale = session.snapshot()
        self.assertTrue(stale.stale)
        self.assertEqual(stale.status, "running")
        self.assertIn("state.json", stale.diagnostic)

        write_run(self.root, run_id, status="paused")
        recovered = session.snapshot()
        self.assertFalse(recovered.stale)
        self.assertEqual(recovered.engine_status, "paused")

    def test_missing_state_after_good_read_is_stale(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        run_id = snapshot.run_id
        write_run(self.root, run_id, status="running")
        self.assertFalse(session.snapshot().stale)
        (self.root / ".specify" / "workflows" / "runs" / run_id / "state.json").unlink()
        stale = session.snapshot()
        self.assertTrue(stale.stale)
        self.assertEqual(stale.status, "running")

    def test_abort_records_cleanup_result(self):
        session = self.make_session()
        session.select("demo")
        session.start({"spec": "search"})
        session.abort()
        result = session.last_abort_result
        self.assertIsNotNone(result)
        self.assertTrue(result.reaped)
        self.assertEqual(self.supervisor.abort_calls, 1)

    def test_paused_with_exited_process_is_not_terminal(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        write_run(self.root, snapshot.run_id, status="paused")
        self.supervisor.finish(exit_code=0)
        final = session.snapshot()
        self.assertIsNone(final.outcome)
        self.assertEqual(final.status, "paused")

    def test_generate_run_id_avoids_existing(self):
        runs = self.root / ".specify" / "workflows" / "runs"
        candidate = generate_run_id(runs)
        self.assertFalse((runs / candidate).exists())

    def test_persisted_definition_match_keeps_running(self):
        import yaml

        from tests.support import LINEAR_WORKFLOW

        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        run_dir = self.root / ".specify" / "workflows" / "runs" / snapshot.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "workflow.yml").write_text(yaml.safe_dump(LINEAR_WORKFLOW), encoding="utf-8")
        final = session.snapshot()
        self.assertIsNone(final.outcome)
        self.assertEqual(self.supervisor.abort_calls, 0)

    def test_persisted_definition_mismatch_is_fatal(self):
        import yaml

        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        run_dir = self.root / ".specify" / "workflows" / "runs" / snapshot.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "workflow.yml").write_text(
            yaml.safe_dump(
                {
                    "workflow": {"id": "demo", "name": "Demo"},
                    "inputs": {"spec": {"type": "string", "required": True}},
                    "steps": [{"id": "totally-different"}],
                }
            ),
            encoding="utf-8",
        )
        final = session.snapshot()
        self.assertIsNotNone(final.outcome)
        self.assertEqual(final.outcome.kind.value, "failure")
        self.assertEqual(self.supervisor.abort_calls, 1)

    def _paused_gate(self, session, run_id, output=None):
        write_run(
            self.root,
            run_id,
            status="paused",
            current_step_id="review",
            step_results={
                "review": {
                    "type": "gate",
                    "output": output
                    or {"message": "Review it", "options": ["approve", "reject"], "on_reject": "retry"},
                }
            },
        )
        self.supervisor.finish(exit_code=0)
        return session.snapshot()

    def test_submit_builds_structured_resume_argv(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        final = self._paused_gate(session, snapshot.run_id)
        self.assertEqual(final.gate.state, GateState.READY)
        session.submit_decision("reject", final.gate.token)
        run_id, argv = self.supervisor.resume_calls[-1]
        self.assertEqual(run_id, snapshot.run_id)
        self.assertEqual(argv[1:4], ["workflow", "resume", snapshot.run_id])
        self.assertIn("review_verdict=reject", argv)
        self.assertIn("--json", argv)

    def test_submit_rejects_unknown_option(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        final = self._paused_gate(session, snapshot.run_id)
        with self.assertRaises(SessionError):
            session.submit_decision("maybe", final.gate.token)

    def test_submit_rejects_while_process_live(self):
        session = self.make_session()
        session.select("demo")
        session.start({"spec": "search"})
        with self.assertRaises(SessionError):
            session.submit_decision("approve", None)

    def test_submit_rejects_malformed_gate(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        final = self._paused_gate(session, snapshot.run_id, output={"message": "Review"})
        self.assertEqual(final.gate.state, GateState.BLOCKED)
        with self.assertRaises(SessionError):
            session.submit_decision("approve", None)

    def test_submit_rejects_after_abort(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        final = self._paused_gate(session, snapshot.run_id)
        session.abort()
        with self.assertRaisesRegex(SessionError, "aborted"):
            session.submit_decision("approve", final.gate.token)

    def test_failed_resume_keeps_paused_gate_and_reports_diagnostic(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        final = self._paused_gate(session, snapshot.run_id)
        session.submit_decision("approve", final.gate.token)
        self.supervisor.finish(exit_code=3)
        final = session.snapshot()
        self.assertEqual(final.status, "paused")
        self.assertIsNotNone(final.gate)
        self.assertIn("exited with code 3", final.diagnostic)

    def test_refresh_review_caches_and_increments_revision(self):
        session = self.make_session()
        session.select("demo")
        session.start({"spec": "search"})
        first = session.refresh_review()
        second = session.refresh_review()
        self.assertEqual(first.revision, 0)
        self.assertEqual(second.revision, 1)
        self.assertIs(session.snapshot().review, second)

    def test_branch_refreshes_after_start(self):
        git = FakeGit(branch_value="main")
        session = self.make_session(git=git)
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        write_run(self.root, snapshot.run_id, status="running")
        git.branch_value = "feature/runway"
        session.refresh_branch()
        refreshed = session.snapshot()
        self.assertEqual(refreshed.branch, "feature/runway")

    def test_git_failure_preserves_previous_branch_and_marks_stale(self):
        git = FakeGit(branch_value="main")
        session = self.make_session(git=git)
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        write_run(self.root, snapshot.run_id, status="running")
        git.branch_error = "Git branch lookup timed out."
        session.refresh_branch()
        refreshed = session.snapshot()
        self.assertEqual(refreshed.branch, "main")
        self.assertTrue(refreshed.stale)
        self.assertIn("timed out", refreshed.diagnostic)
        git.branch_error = ""
        session.refresh_branch()
        self.assertFalse(session.snapshot().stale)


class InteractiveSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_workflow(self.root, NON_VERDICT_WORKFLOW)
        write_registry(self.root)
        self.supervisor = FakeSupervisor()
        self.now = [100.0]

    def tearDown(self):
        self.tmp.cleanup()

    def make_session(self, version="1.0.6"):
        environment = CockpitEnvironment(self.root, compatibility_result(version))
        services = replace(
            CockpitServices.for_environment(environment),
            git=FakeGit(),
            review_source=FakeReviewService(),
        )
        engine = replace(
            EngineRuntime.for_environment(environment, clock=lambda: self.now[0]),
            supervisor=self.supervisor,
        )
        return CockpitSession(environment, services=services, engine=engine)

    def _start_live_gate(self, version="1.0.6"):
        session = self.make_session(version)
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        write_run(self.root, snapshot.run_id, status="running", current_step_id="review")
        return session, snapshot.run_id

    def test_contract_enables_interactive_stdin_policy(self):
        session = self.make_session()
        session.select("demo")
        session.start({"spec": "search"})
        self.assertIs(self.supervisor.stdin_policy, StdinPolicy.PTY)
        self.assertEqual(session.compatibility_error, "")

    def test_verdict_gate_definition_keeps_stdin_closed(self):
        from tests.support import LINEAR_WORKFLOW

        write_workflow(self.root, LINEAR_WORKFLOW)
        session = self.make_session()
        session.select("demo")
        session.start({"spec": "search"})
        self.assertIs(self.supervisor.stdin_policy, StdinPolicy.DEVNULL)

    def test_unverified_version_is_rejected_before_start(self):
        session = self.make_session("1.0.5")
        session.select("demo")
        self.assertIn("not verified", session.compatibility_error)
        with self.assertRaisesRegex(SessionError, "not verified"):
            session.start({"spec": "search"})
        self.assertIsNone(self.supervisor.started_argv)

    def test_live_non_verdict_gate_is_ready(self):
        session, _ = self._start_live_gate()
        gate = session.snapshot().gate
        self.assertEqual(gate.state, GateState.READY)
        self.assertEqual(gate.options, ("approve", "reject"))
        self.assertTrue(gate.token)

    def test_submit_writes_mapped_choice_exactly_once(self):
        session, _ = self._start_live_gate()
        gate = session.snapshot().gate
        session.submit_decision("approve", gate.token)
        self.assertEqual(self.supervisor.writes, [b"1\n"])
        after = session.snapshot().gate
        self.assertEqual(after.state, GateState.SUBMITTED)
        self.assertFalse(after.selectable)
        with self.assertRaises(SessionError):
            session.submit_decision("reject", gate.token)
        self.assertEqual(self.supervisor.writes, [b"1\n"])

    def test_repeated_snapshots_do_not_rewrite(self):
        session, _ = self._start_live_gate()
        gate = session.snapshot().gate
        session.submit_decision("approve", gate.token)
        for _ in range(5):
            session.snapshot()
        self.assertEqual(self.supervisor.writes, [b"1\n"])

    def test_watch_expiry_marks_unverified(self):
        session, _ = self._start_live_gate()
        gate = session.snapshot().gate
        session.submit_decision("approve", gate.token)
        self.now[0] += 10.0
        after = session.snapshot().gate
        self.assertEqual(after.state, GateState.UNVERIFIED)
        self.assertFalse(after.selectable)

    def test_stale_token_is_rejected_without_write(self):
        session, _ = self._start_live_gate()
        with self.assertRaisesRegex(SessionError, "stale"):
            session.submit_decision("approve", "not-the-token")
        self.assertEqual(self.supervisor.writes, [])

    def test_advancement_clears_gate(self):
        session, run_id = self._start_live_gate()
        gate = session.snapshot().gate
        session.submit_decision("approve", gate.token)
        write_run(self.root, run_id, status="completed", current_step_id="finish")
        self.supervisor.finish(exit_code=0)
        final = session.snapshot()
        self.assertIsNone(final.gate)

    def test_reaped_process_blocks_the_gate(self):
        session, _ = self._start_live_gate()
        self.supervisor.finish(exit_code=0)
        gate = session.snapshot().gate
        self.assertEqual(gate.state, GateState.BLOCKED)
        self.assertIn("live", gate.reason)

    def test_unknown_choice_is_rejected(self):
        session, _ = self._start_live_gate()
        gate = session.snapshot().gate
        with self.assertRaises(SessionError):
            session.submit_decision("maybe", gate.token)
        self.assertEqual(self.supervisor.writes, [])

    def test_not_running_state_blocks_the_gate(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        write_run(self.root, snapshot.run_id, status="created", current_step_id="review")
        gate = session.snapshot().gate
        self.assertEqual(gate.state, GateState.BLOCKED)
        self.assertIn("not waiting", gate.reason)

    def test_empty_options_are_rejected_before_start(self):
        write_workflow(self.root, non_verdict_workflow([]))
        session = self.make_session()
        session.select("demo")
        self.assertIn("no options", session.compatibility_error)
        with self.assertRaises(SessionError):
            session.start({"spec": "search"})
        self.assertIsNone(self.supervisor.started_argv)

    def test_structured_gate_never_uses_pty(self):
        from tests.support import LINEAR_WORKFLOW

        write_workflow(self.root, LINEAR_WORKFLOW)
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        write_run(
            self.root,
            snapshot.run_id,
            status="paused",
            current_step_id="review",
            step_results={
                "review": {
                    "type": "gate",
                    "output": {"message": "Review it", "options": ["approve", "reject"], "on_reject": "retry"},
                }
            },
        )
        self.supervisor.finish(exit_code=0)
        final = session.snapshot()
        self.assertEqual(final.gate.state, GateState.READY)
        session.submit_decision("approve", final.gate.token)
        self.assertEqual(self.supervisor.writes, [])
        self.assertTrue(self.supervisor.resume_calls)


if __name__ == "__main__":
    unittest.main()
