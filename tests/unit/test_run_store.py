import tempfile
import unittest
from pathlib import Path

from tests.support import write_run
from tests.unit.test_run_catalog import write_launch_copy
from workflow_cockpit.services.run_claim import OwnershipClaim, RunClaimStore
from workflow_cockpit.services.run_store import RunStore


class RunStoreDeleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify" / "workflows" / "runs").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def seed(self, run_id, status="completed"):
        write_run(self.root, run_id, status=status, current_step_id="finish")
        write_launch_copy(self.root, run_id)
        return run_id

    def run_dir(self, run_id):
        return self.root / ".specify" / "workflows" / "runs" / run_id

    def claim(self, run_id, owner_id, *, pid_alive, start_time):
        claims = RunClaimStore(
            self.root,
            host="test-host",
            pid_alive=pid_alive,
            start_time=start_time,
        )
        claims.acquire(
            run_id,
            OwnershipClaim(
                run_id=run_id,
                owner_id=owner_id,
                host="test-host",
                pid=4321,
                pgid=4321,
                process_start="100",
                created_at="2026-09-18T00:00:00+00:00",
            ),
        )
        return claims

    def test_deletes_terminal_run(self):
        run_id = self.seed("run-done", "completed")
        result = RunStore(self.root).delete(run_id)
        self.assertTrue(result.deleted)
        self.assertFalse(self.run_dir(run_id).exists())

    def test_refuses_running_run(self):
        run_id = self.seed("run-live", "running")
        result = RunStore(self.root).delete(run_id)
        self.assertFalse(result.deleted)
        self.assertIn("running", result.reason)
        self.assertTrue(self.run_dir(run_id).exists())

    def test_refuses_initializing_run(self):
        run_id = self.seed("run-init", "initializing")
        result = RunStore(self.root).delete(run_id)
        self.assertFalse(result.deleted)
        self.assertTrue(self.run_dir(run_id).exists())

    def test_refuses_missing_run(self):
        result = RunStore(self.root).delete("absent")
        self.assertFalse(result.deleted)
        self.assertIn("missing", result.reason)

    def test_refuses_path_traversal(self):
        for bad in ("", ".", "..", "a/b", "../evil", "a\\b", "x\x00y"):
            result = RunStore(self.root).delete(bad)
            self.assertFalse(result.deleted, bad)

    def test_refuses_protected_run(self):
        run_id = self.seed("run-current", "paused")
        result = RunStore(self.root).delete(run_id, protected_run_id=run_id)
        self.assertFalse(result.deleted)
        self.assertIn("active", result.reason)
        self.assertTrue(self.run_dir(run_id).exists())

    def test_refuses_live_foreign_claim(self):
        run_id = self.seed("run-owned", "completed")
        claims = self.claim(
            run_id, "other", pid_alive=lambda pid: True, start_time=lambda pid: "100"
        )
        result = RunStore(self.root, owner_id="me", claims=claims).delete(run_id)
        self.assertFalse(result.deleted)
        self.assertIn("live Cockpit", result.reason)
        self.assertTrue(self.run_dir(run_id).exists())

    def test_stale_claim_does_not_block_delete(self):
        run_id = self.seed("run-stale", "completed")
        claims = self.claim(
            run_id, "crashed", pid_alive=lambda pid: False, start_time=lambda pid: "100"
        )
        result = RunStore(self.root, owner_id="me", claims=claims).delete(run_id)
        self.assertTrue(result.deleted)
        self.assertFalse(self.run_dir(run_id).exists())

    def test_refuses_unusable_run(self):
        run_dir = self.root / ".specify" / "workflows" / "runs" / "run-broken"
        run_dir.mkdir(parents=True)
        write_launch_copy(self.root, "run-broken")
        result = RunStore(self.root).delete("run-broken")
        self.assertFalse(result.deleted)
        self.assertIn("state.json", result.reason)

    def test_refuses_symlink_escape(self):
        outside = self.root / "outside"
        outside.mkdir()
        link = self.root / ".specify" / "workflows" / "runs" / "link"
        link.symlink_to(outside, target_is_directory=True)
        write_run(self.root, "link", status="completed", current_step_id="finish")
        write_launch_copy(self.root, "link")
        result = RunStore(self.root).delete("link")
        self.assertFalse(result.deleted)
        self.assertIn("outside", result.reason)
        self.assertTrue(outside.exists())


if __name__ == "__main__":
    unittest.main()
