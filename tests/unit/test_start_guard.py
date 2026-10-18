"""The shared Start guard: refuse a non-terminal current run, allow the rest."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import run_trees as rt
from workflow_cockpit.services.start_guard import StartGuard


class StartGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.guard = StartGuard(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_pointer_allows_start(self):
        rt.no_run(self.root)
        self.assertIsNone(self.guard.check())

    def test_terminal_run_allows_start(self):
        rt.live_flat(self.root, status="completed")
        self.assertIsNone(self.guard.check())

    def test_running_run_is_refused_with_alternatives(self):
        rt.live_flat(self.root, status="running")
        refusal = self.guard.check()
        self.assertIsNotNone(refusal)
        self.assertEqual(refusal.run_id, rt.RUN_ID)
        self.assertEqual(refusal.status, "running")
        self.assertIn(rt.RUN_ID, refusal.message)
        self.assertIn("Adopt", refusal.message)
        self.assertIn("abort", refusal.message.lower())
        self.assertEqual(refusal.code, "run_in_progress")
        self.assertEqual(refusal.details()["run_id"], rt.RUN_ID)

    def test_paused_run_is_refused(self):
        rt.paused_gate(self.root)
        refusal = self.guard.check()
        self.assertIsNotNone(refusal)
        self.assertEqual(refusal.status, "paused")

    def test_pointer_naming_a_missing_run_allows_start(self):
        rt.write_pointer(self.root, "cockpit-gone")
        self.assertIsNone(self.guard.check())

    def test_disagreement_is_refused_as_a_repair(self):
        rt.live_flat(self.root)
        (self.root / ".specify" / "workflows" / "runs" / "current_run.json").write_text(
            json.dumps({"schema_version": 1, "run_id": "cockpit-other"}), encoding="utf-8"
        )
        refusal = self.guard.check()
        self.assertIsNotNone(refusal)
        self.assertIn("inconsistent", refusal.message)
        self.assertIn("pointer", refusal.action)

    def test_unreadable_state_allows_start(self):
        rt.unreadable_state(self.root)
        # The run is unusable, so no non-terminal run can be established.
        self.assertIsNone(self.guard.check())


if __name__ == "__main__":
    unittest.main()
