"""Host lifetime: run-scoped exit rules and the catchable-death abort hook."""

from __future__ import annotations

import unittest

from tests.fakes import FakeSession, FakeSupervisor
from workflow_cockpit.host.lifetime import (
    EXITED,
    RELEASING,
    RUN_NONE,
    RUN_PAUSED,
    RUN_RUNNING,
    RUN_TERMINAL,
    SERVING,
    STARTING,
    HostLifetime,
    catchable_death_abort,
    run_state_for,
)


class RunStateMappingTests(unittest.TestCase):
    def test_maps_persisted_statuses(self):
        self.assertEqual(run_state_for(None), RUN_NONE)
        self.assertEqual(run_state_for(""), RUN_NONE)
        self.assertEqual(run_state_for("running"), RUN_RUNNING)
        self.assertEqual(run_state_for("initializing"), RUN_RUNNING)
        self.assertEqual(run_state_for("paused"), RUN_PAUSED)
        self.assertEqual(run_state_for("completed"), RUN_TERMINAL)
        self.assertEqual(run_state_for("failed"), RUN_TERMINAL)
        self.assertEqual(run_state_for("aborted"), RUN_TERMINAL)


class LifetimeTests(unittest.TestCase):
    def setUp(self):
        self.lifetime = HostLifetime(grace_seconds=2.0)

    def test_starts_in_starting_then_serves(self):
        self.assertEqual(self.lifetime.state, STARTING)
        self.assertEqual(self.lifetime.observe(run_status="running", clients=1, now=0.0), SERVING)
        self.assertTrue(self.lifetime.serving)

    def test_terminal_run_releases_immediately(self):
        self.assertEqual(self.lifetime.observe(run_status="completed", clients=1, now=0.0), RELEASING)
        self.assertTrue(self.lifetime.released)

    def test_never_releases_while_a_step_runs(self):
        self.lifetime.observe(run_status="running", clients=0, now=0.0)
        self.assertEqual(self.lifetime.observe(run_status="running", clients=0, now=100.0), SERVING)

    def test_paused_with_a_client_stays_alive(self):
        self.lifetime.observe(run_status="paused", clients=1, now=0.0)
        self.assertEqual(self.lifetime.observe(run_status="paused", clients=1, now=100.0), SERVING)

    def test_paused_with_no_client_releases_after_the_grace_window(self):
        self.lifetime.observe(run_status="paused", clients=0, now=0.0)
        self.assertEqual(self.lifetime.observe(run_status="paused", clients=0, now=1.0), SERVING)
        self.assertEqual(self.lifetime.observe(run_status="paused", clients=0, now=2.0), RELEASING)

    def test_reconnect_inside_the_grace_window_is_not_raced(self):
        self.lifetime.observe(run_status="paused", clients=0, now=0.0)
        self.assertEqual(self.lifetime.observe(run_status="paused", clients=1, now=1.0), SERVING)
        self.assertEqual(self.lifetime.observe(run_status="paused", clients=0, now=2.5), SERVING)
        self.assertEqual(self.lifetime.observe(run_status="paused", clients=0, now=4.5), RELEASING)

    def test_no_run_keeps_the_host_alive_for_a_start_request(self):
        self.lifetime.observe(run_status=None, clients=0, now=0.0)
        self.assertEqual(self.lifetime.observe(run_status=None, clients=0, now=100.0), SERVING)

    def test_released_state_is_terminal(self):
        self.lifetime.observe(run_status="aborted", clients=0, now=0.0)
        self.lifetime.exit()
        self.assertEqual(self.lifetime.state, EXITED)
        self.assertEqual(self.lifetime.observe(run_status="running", clients=1, now=5.0), EXITED)

    def test_snapshot_reports_state_run_and_pid(self):
        self.lifetime.observe(run_status="paused", clients=1, now=0.0)
        snapshot = self.lifetime.snapshot()
        self.assertEqual(snapshot["state"], SERVING)
        self.assertEqual(snapshot["run"], RUN_PAUSED)
        self.assertIsInstance(snapshot["pid"], int)


class CatchableDeathTests(unittest.TestCase):
    def test_aborts_through_the_session_and_reports_the_result(self):
        session = FakeSession(status="running")
        result = catchable_death_abort(session)
        self.assertTrue(session.aborted)
        self.assertTrue(result["signalled"])
        self.assertTrue(result["reaped"])
        self.assertEqual(result["escalation"], "SIGINT")

    def test_reports_a_refusal_instead_of_raising(self):
        class Broken:
            def abort(self):
                raise RuntimeError("no live group")

            last_abort_result = None

        result = catchable_death_abort(Broken())
        self.assertFalse(result["aborted"])
        self.assertIn("no live group", result["reason"])

    def test_signals_nothing_when_no_group_is_live(self):
        supervisor = FakeSupervisor(live=False)
        result = catchable_death_abort(supervisor)
        self.assertFalse(result["signalled"])


if __name__ == "__main__":
    unittest.main()
