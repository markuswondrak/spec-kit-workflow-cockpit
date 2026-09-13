import tempfile
import unittest
from pathlib import Path

from tests.support import (
    FakeGit,
    FakeSupervisor,
    compatibility_result,
    write_registry,
    write_run,
    write_workflow,
)
from workflow_cockpit.services.definition import WorkflowDefinitionResolver
from workflow_cockpit.services.registry import WorkflowRegistry
from workflow_cockpit.session.cockpit_session import CockpitSession, SessionError, generate_run_id


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
        git = kwargs.pop("git", FakeGit())
        return CockpitSession(
            self.root,
            compatibility_result(),
            registry=WorkflowRegistry(self.root),
            resolver=WorkflowDefinitionResolver(self.root),
            git=git,
            supervisor=self.supervisor,
            clock=lambda: 10.0,
        )

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

    def test_decide_builds_structured_resume_argv(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        final = self._paused_gate(session, snapshot.run_id)
        self.assertTrue(final.gate.structured)
        session.decide("reject")
        run_id, argv = self.supervisor.resume_calls[-1]
        self.assertEqual(run_id, snapshot.run_id)
        self.assertEqual(argv[1:4], ["workflow", "resume", snapshot.run_id])
        self.assertIn("spec=reject", argv)
        self.assertIn("--json", argv)

    def test_decide_rejects_unknown_option(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        self._paused_gate(session, snapshot.run_id)
        with self.assertRaises(SessionError):
            session.decide("maybe")

    def test_decide_rejects_while_process_live(self):
        session = self.make_session()
        session.select("demo")
        session.start({"spec": "search"})
        with self.assertRaises(SessionError):
            session.decide("approve")

    def test_decide_rejects_malformed_gate(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        self._paused_gate(session, snapshot.run_id, output={"message": "Review"})
        with self.assertRaises(SessionError):
            session.decide("approve")

    def test_decide_rejects_after_abort(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        self._paused_gate(session, snapshot.run_id)
        session.abort()
        with self.assertRaisesRegex(SessionError, "aborted"):
            session.decide("approve")

    def test_failed_resume_keeps_paused_gate_and_reports_diagnostic(self):
        session = self.make_session()
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        self._paused_gate(session, snapshot.run_id)
        session.decide("approve")
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

    def test_branch_refreshes_without_changing_baseline(self):
        git = FakeGit(branch_value="main")
        session = self.make_session(git=git)
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        write_run(self.root, snapshot.run_id, status="running")
        git.branch_value = "feature/runway"
        refreshed = session.snapshot()
        self.assertEqual(refreshed.branch, "feature/runway")
        self.assertEqual(refreshed.baseline_commit, "a" * 40)


if __name__ == "__main__":
    unittest.main()
