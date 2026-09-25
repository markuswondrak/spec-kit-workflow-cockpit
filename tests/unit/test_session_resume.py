"""Session-level resume tests, split from ``test_session.py`` (over its cap)."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.fakes import FakeGit, FakeReviewService, FakeSupervisor
from tests.resume_support import seed_failed_run
from tests.support import compatibility_result, write_run
from workflow_cockpit.session.cockpit_session import CockpitSession, SessionError
from workflow_cockpit.session.dependencies import (
    CockpitEnvironment,
    CockpitServices,
    EngineRuntime,
)

ADOPT_WORKFLOW = {
    "schema_version": "1.0",
    "workflow": {"id": "demo", "name": "Demo Workflow", "version": "1.0.0"},
    "inputs": {"spec": {"type": "string", "required": True}},
    "steps": [
        {"id": "prepare", "command": "demo.prepare"},
        {
            "id": "review",
            "type": "gate",
            "message": "Review it",
            "options": ["approve", "reject"],
            "verdict_input": "review_verdict",
        },
        {"id": "finish", "command": "demo.finish"},
    ],
}


def read_dir(path: Path) -> dict[str, bytes]:
    return {item.name: item.read_bytes() for item in sorted(path.iterdir()) if item.is_file()}


class SessionResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify" / "workflows" / "runs").mkdir(parents=True)
        self.supervisor = FakeSupervisor()

    def tearDown(self):
        self.tmp.cleanup()

    def seed(self, run_id, status="failed"):
        seed_failed_run(self.root, run_id, workflow=ADOPT_WORKFLOW, status=status)
        return run_id

    def make_session(self):
        environment = CockpitEnvironment(self.root, compatibility_result("1.0.6"))
        services = replace(
            CockpitServices.for_environment(environment),
            git=FakeGit(),
            review_source=FakeReviewService(),
        )
        engine = replace(
            EngineRuntime.for_environment(environment, clock=lambda: 10.0),
            supervisor=self.supervisor,
        )
        return CockpitSession(environment, services=services, engine=engine)

    def test_resume_run_writes_once_and_rereads_status(self):
        run_id = self.seed("run-failed")
        session = self.make_session()
        session.adopt(run_id)
        decision = session.resume_decision()
        self.assertIsNotNone(decision)
        self.assertTrue(decision.available)
        returned = session.resume_run(decision.token)
        self.assertEqual(returned.run_id, run_id)
        self.assertEqual(len(self.supervisor.resume_calls), 1)
        _run_id, argv = self.supervisor.resume_calls[-1]
        self.assertEqual(argv[1:4], ["workflow", "resume", run_id])
        self.assertNotIn("-i", argv)
        # The status is re-read from persisted files, never inferred.
        write_run(self.root, run_id, status="completed", current_step_id="finish")
        self.supervisor.finish(exit_code=0)
        final = session.snapshot()
        self.assertEqual(final.engine_status, "completed")
        self.assertEqual(final.outcome.kind.value, "success")

    def test_resume_run_rejects_stale_token_and_leaves_run_unchanged(self):
        run_id = self.seed("run-failed")
        session = self.make_session()
        session.adopt(run_id)
        run_dir = self.root / ".specify" / "workflows" / "runs" / run_id
        before = read_dir(run_dir)
        with self.assertRaises(SessionError):
            session.resume_run("stale-token")
        self.assertEqual(self.supervisor.resume_calls, [])
        self.assertEqual(read_dir(run_dir), before)

    def test_resume_run_refused_when_status_moves_out_of_eligibility(self):
        run_id = self.seed("run-failed")
        session = self.make_session()
        session.adopt(run_id)
        decision = session.resume_decision()
        write_run(self.root, run_id, status="running", current_step_id="review")
        with self.assertRaises(SessionError):
            session.resume_run(decision.token)
        self.assertEqual(self.supervisor.resume_calls, [])

    def test_two_rapid_resumes_write_once(self):
        run_id = self.seed("run-failed")
        session = self.make_session()
        session.adopt(run_id)
        decision = session.resume_decision()
        session.resume_run(decision.token)
        with self.assertRaises(SessionError):
            session.resume_run(decision.token)
        self.assertEqual(len(self.supervisor.resume_calls), 1)

    def test_resume_run_refused_in_read_only_mode(self):
        run_id = self.seed("run-failed")
        session = self.make_session()
        session.inspect(run_id)
        with self.assertRaises(SessionError):
            session.resume_run("anything")
        self.assertEqual(self.supervisor.resume_calls, [])

    def test_resume_decision_is_none_for_non_failed_run(self):
        run_id = self.seed("run-paused", status="paused")
        session = self.make_session()
        session.adopt(run_id)
        self.assertIsNone(session.resume_decision())


if __name__ == "__main__":
    unittest.main()
