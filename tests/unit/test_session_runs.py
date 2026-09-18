import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.support import FakeGit, FakeReviewService, FakeSupervisor, compatibility_result, write_run
from tests.unit.test_run_catalog import write_launch_copy
from workflow_cockpit.session.cockpit_session import CockpitSession
from workflow_cockpit.session.dependencies import (
    CockpitEnvironment,
    CockpitServices,
    EngineRuntime,
)


class SessionExistingRunsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify" / "workflows" / "runs").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def make_session(self):
        environment = CockpitEnvironment(self.root, compatibility_result("1.0.0"))
        services = replace(
            CockpitServices.for_environment(environment),
            git=FakeGit(),
            review_source=FakeReviewService(),
        )
        engine = replace(
            EngineRuntime.for_environment(environment, clock=lambda: 10.0),
            supervisor=FakeSupervisor(),
        )
        return CockpitSession(environment, services=services, engine=engine)

    def test_empty_directory_lists_nothing(self):
        self.assertEqual(self.make_session().list_existing_runs(), ())

    def test_lists_existing_run_from_persisted_files(self):
        write_run(self.root, "cockpit-a", status="paused")
        write_launch_copy(self.root, "cockpit-a")
        descriptors = self.make_session().list_existing_runs()
        self.assertEqual(len(descriptors), 1)
        self.assertEqual(descriptors[0].run_id, "cockpit-a")
        self.assertEqual(descriptors[0].status, "paused")

    def test_inspect_running_run_is_read_only(self):
        from workflow_cockpit.session.cockpit_session import SessionError

        write_run(self.root, "cockpit-running", status="running", current_step_id="prepare")
        write_launch_copy(self.root, "cockpit-running")
        session = self.make_session()
        snapshot = session.inspect("cockpit-running")
        self.assertEqual(snapshot.run_id, "cockpit-running")
        self.assertEqual(snapshot.status, "running")
        self.assertTrue(snapshot.read_only)
        self.assertFalse(snapshot.adopted)
        self.assertTrue(session.read_only)
        self.assertEqual(session.run_id, "cockpit-running")
        # Assert no ownership claim was written
        claim_file = self.root / ".specify" / "workflows" / "runs" / "cockpit-running" / ".cockpit-owner.json"
        self.assertFalse(claim_file.exists())
        # Assert supervisor has not bound a process
        self.assertIsNone(session.engine.supervisor.run_id)
        # Assert abort and gate submit are refused
        with self.assertRaises(SessionError):
            session.abort()
        with self.assertRaises(SessionError):
            session.submit_decision("approve", "dummy-token")

    def test_inspect_at_gate_projects_blocked_gate(self):
        write_run(
            self.root,
            "cockpit-gate",
            status="paused",
            current_step_id="review",
            step_results={
                "review": {
                    "type": "gate",
                    "output": {"message": "Review it", "options": ["approve", "reject"]},
                }
            },
        )
        write_launch_copy(self.root, "cockpit-gate")
        session = self.make_session()
        snapshot = session.inspect("cockpit-gate")
        self.assertIsNotNone(snapshot.gate)
        self.assertFalse(snapshot.gate.selectable)
        self.assertIn("View-only", snapshot.gate.reason)

    def test_delete_terminal_run_removes_directory(self):
        write_run(self.root, "cockpit-done", status="completed", current_step_id="finish")
        write_launch_copy(self.root, "cockpit-done")
        session = self.make_session()
        session.delete_existing_run("cockpit-done")
        run_dir = self.root / ".specify" / "workflows" / "runs" / "cockpit-done"
        self.assertFalse(run_dir.exists())

    def test_delete_clears_current_run_index(self):
        write_run(self.root, "cockpit-done", status="completed", current_step_id="finish")
        write_launch_copy(self.root, "cockpit-done")
        index = self.root / ".specify" / "workflows" / "runs" / "current_run"
        index.write_text("# Cockpit run context\n- Run ID: `cockpit-done`\n", encoding="utf-8")
        self.make_session().delete_existing_run("cockpit-done")
        self.assertFalse(index.exists())

    def test_delete_refuses_run_open_in_this_session(self):
        from workflow_cockpit.session.cockpit_session import SessionError

        write_run(self.root, "cockpit-open", status="paused", current_step_id="review")
        write_launch_copy(self.root, "cockpit-open")
        session = self.make_session()
        session.inspect("cockpit-open")
        with self.assertRaises(SessionError):
            session.delete_existing_run("cockpit-open")
        run_dir = self.root / ".specify" / "workflows" / "runs" / "cockpit-open"
        self.assertTrue(run_dir.exists())


if __name__ == "__main__":
    unittest.main()
