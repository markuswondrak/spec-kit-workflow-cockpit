import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.support import LINEAR_WORKFLOW, write_run
from workflow_cockpit.services import run_catalog
from workflow_cockpit.services.run_catalog import (
    MAX_STATE_BYTES,
    RunCatalog,
    RunCatalogError,
)


def write_launch_copy(root: Path, run_id: str, workflow=None) -> None:
    run_dir = root / ".specify" / "workflows" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "workflow.yml").write_text(
        yaml.safe_dump(workflow or LINEAR_WORKFLOW, sort_keys=False), encoding="utf-8"
    )


class RunCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify" / "workflows" / "runs").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def seed(self, run_id, status="paused", *, workflow=True, step="review", mtime=None):
        write_run(self.root, run_id, status=status, current_step_id=step)
        if workflow:
            write_launch_copy(self.root, run_id)
        if mtime is not None:
            run_dir = self.root / ".specify" / "workflows" / "runs" / run_id
            os.utime(run_dir, ns=(mtime, mtime))
        return run_id

    def test_lists_kept_status_values(self):
        self.seed("run-paused", "paused")
        self.seed("run-done", "completed")
        catalog = RunCatalog(self.root)
        by_id = {descriptor.run_id: descriptor for descriptor in catalog.list_runs()}
        self.assertEqual(by_id["run-paused"].status, "paused")
        self.assertTrue(by_id["run-paused"].adoptable)
        self.assertTrue(by_id["run-paused"].viewable)
        self.assertEqual(by_id["run-done"].status, "completed")
        self.assertFalse(by_id["run-done"].adoptable)
        self.assertTrue(by_id["run-done"].viewable)

    def test_unknown_status_is_readable_but_not_adoptable(self):
        self.seed("run-weird", "frobnicating")
        descriptor = RunCatalog(self.root).describe("run-weird")
        self.assertTrue(descriptor.usable)
        self.assertTrue(descriptor.viewable)
        self.assertEqual(descriptor.status, "frobnicating")
        self.assertFalse(descriptor.adoptable)

    def test_workflow_metadata_reads_launch_copy(self):
        self.seed("run-meta")
        descriptor = RunCatalog(self.root).describe("run-meta")
        self.assertEqual(descriptor.workflow_id, "demo")
        self.assertEqual(descriptor.workflow_name, "Demo Workflow")

    def test_missing_state_is_unusable_with_reason(self):
        run_dir = self.root / ".specify" / "workflows" / "runs" / "run-broken"
        run_dir.mkdir(parents=True)
        write_launch_copy(self.root, "run-broken")
        descriptor = RunCatalog(self.root).describe("run-broken")
        self.assertFalse(descriptor.usable)
        self.assertIn("state.json", descriptor.reason)
        self.assertEqual(descriptor.status, "unusable")

    def test_truncated_state_is_unusable_with_reason(self):
        self.seed("run-truncated")
        run_dir = self.root / ".specify" / "workflows" / "runs" / "run-truncated"
        (run_dir / "state.json").write_text('{"status": "pau', encoding="utf-8")
        descriptor = RunCatalog(self.root).describe("run-truncated")
        self.assertFalse(descriptor.usable)
        self.assertIn("JSON", descriptor.reason)

    def test_oversized_state_is_unusable_with_reason(self):
        self.seed("run-big")
        run_dir = self.root / ".specify" / "workflows" / "runs" / "run-big"
        (run_dir / "state.json").write_text(
            json.dumps({"status": "paused", "blob": "x" * (MAX_STATE_BYTES + 10)}),
            encoding="utf-8",
        )
        descriptor = RunCatalog(self.root).describe("run-big")
        self.assertFalse(descriptor.usable)
        self.assertIn("exceeds", descriptor.reason)

    def test_oversized_launch_copy_is_unusable(self):
        self.seed("run-big-wf")
        run_dir = self.root / ".specify" / "workflows" / "runs" / "run-big-wf"
        (run_dir / "workflow.yml").write_bytes(b"workflow: {id: demo}\n" + b"#" * (600 * 1024))
        descriptor = RunCatalog(self.root).describe("run-big-wf")
        self.assertFalse(descriptor.usable)
        self.assertIn("workflow.yml", descriptor.reason)

    def test_missing_launch_copy_is_readable_but_not_adoptable(self):
        self.seed("run-no-wf", workflow=False)
        descriptor = RunCatalog(self.root).describe("run-no-wf")
        self.assertTrue(descriptor.usable)
        self.assertFalse(descriptor.launch_copy)
        self.assertFalse(descriptor.adoptable)
        self.assertFalse(descriptor.viewable)

    def test_directory_name_and_log_are_not_inferred(self):
        self.seed("cockpit-completed", "paused")
        run_dir = self.root / ".specify" / "workflows" / "runs" / "cockpit-completed"
        (run_dir / "log.jsonl").write_text(
            json.dumps({"event": "status", "status": "completed"}) + "\n", encoding="utf-8"
        )
        descriptor = RunCatalog(self.root).describe("cockpit-completed")
        self.assertEqual(descriptor.status, "paused")

    def test_skips_non_directory_entries(self):
        self.seed("run-a")
        (self.root / ".specify" / "workflows" / "runs" / "current_run").write_text(
            "# index\n- Run ID: `run-a`\n", encoding="utf-8"
        )
        ids = [descriptor.run_id for descriptor in RunCatalog(self.root).list_runs()]
        self.assertEqual(ids, ["run-a"])

    def test_newest_first_and_max_runs_bound(self):
        self.seed("run-old", mtime=1_000)
        self.seed("run-mid", mtime=2_000)
        self.seed("run-new", mtime=3_000)
        catalog = RunCatalog(self.root, max_runs=2)
        ids = [descriptor.run_id for descriptor in catalog.list_runs()]
        self.assertEqual(ids, ["run-new", "run-mid"])

    def test_current_run_marks_default_suggestion(self):
        self.seed("run-a")
        self.seed("run-b")
        (self.root / ".specify" / "workflows" / "runs" / "current_run").write_text(
            "# Cockpit run context\n- Run ID: `run-b`\n", encoding="utf-8"
        )
        by_id = {descriptor.run_id: descriptor for descriptor in RunCatalog(self.root).list_runs()}
        self.assertTrue(by_id["run-b"].is_default)
        self.assertFalse(by_id["run-a"].is_default)

    def test_missing_directory_describe_raises(self):
        with self.assertRaises(RunCatalogError):
            RunCatalog(self.root).describe("nope")

    def test_empty_runs_dir_lists_nothing(self):
        self.assertEqual(RunCatalog(self.root).list_runs(), ())

    def test_failed_run_is_adoptable_and_other_statuses_are_not(self):
        self.seed("run-failed", "failed")
        for status in ("running", "aborted", "completed", "initializing"):
            self.seed(f"run-{status}", status)
        descriptor = RunCatalog(self.root).describe("run-failed")
        self.assertTrue(descriptor.adoptable)
        self.assertTrue(descriptor.viewable)
        for status in ("running", "aborted", "completed", "initializing"):
            with self.subTest(status=status):
                self.assertFalse(RunCatalog(self.root).describe(f"run-{status}").adoptable)

    def test_failed_run_without_launch_copy_is_not_adoptable(self):
        self.seed("run-no-copy", "failed", workflow=False)
        descriptor = RunCatalog(self.root).describe("run-no-copy")
        self.assertFalse(descriptor.launch_copy)
        self.assertFalse(descriptor.adoptable)

    def test_failed_run_with_unreadable_launch_copy_is_unusable(self):
        self.seed("run-bad-wf", "failed")
        run_dir = self.root / ".specify" / "workflows" / "runs" / "run-bad-wf"
        (run_dir / "workflow.yml").write_text("workflow: [unclosed", encoding="utf-8")
        descriptor = RunCatalog(self.root).describe("run-bad-wf")
        self.assertFalse(descriptor.usable)
        self.assertFalse(descriptor.adoptable)
        self.assertIn("workflow.yml", descriptor.reason)

    def test_failed_run_with_oversized_launch_copy_is_unusable(self):
        self.seed("run-big-failed", "failed")
        run_dir = self.root / ".specify" / "workflows" / "runs" / "run-big-failed"
        (run_dir / "workflow.yml").write_bytes(b"workflow: {id: demo}\n" + b"#" * (600 * 1024))
        descriptor = RunCatalog(self.root).describe("run-big-failed")
        self.assertFalse(descriptor.usable)
        self.assertFalse(descriptor.adoptable)

    def test_failed_run_with_live_foreign_owner_is_not_adoptable(self):
        from tests.resume_support import HOST, PROCESS_START, seed_failed_run
        from workflow_cockpit.services.run_claim import ClaimState, RunClaimStore

        seed_failed_run(self.root, "run-foreign", claim_state=ClaimState.LIVE_FOREIGN)
        store = RunClaimStore(
            self.root,
            host=HOST,
            pid_alive=lambda pid: True,
            start_time=lambda pid: PROCESS_START,
        )
        descriptor = RunCatalog(self.root, owner_id="me", claim_store=store).describe(
            "run-foreign"
        )
        self.assertEqual(descriptor.claim_state, ClaimState.LIVE_FOREIGN)
        self.assertFalse(descriptor.adoptable)

    def test_module_imports_no_engine_internals(self):
        source = inspect.getsource(run_catalog)
        self.assertNotIn("workflow_cockpit.engine", source)
        self.assertNotIn("from ..engine", source)
        self.assertNotIn("from .engine", source)


if __name__ == "__main__":
    unittest.main()
