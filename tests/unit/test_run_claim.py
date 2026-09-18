import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from workflow_cockpit.services.run_claim import (
    ClaimOutcome,
    ClaimState,
    OwnershipClaim,
    RunClaimStore,
    current_claim,
)


def make_claim(**overrides):
    values = {
        "run_id": "cockpit-abc123",
        "owner_id": "owner-1",
        "host": "test-host",
        "pid": 4321,
        "pgid": 4321,
        "process_start": "123456",
        "created_at": "2026-09-18T00:00:00+00:00",
        "branch": "main",
    }
    values.update(overrides)
    return OwnershipClaim(**values)


class ClaimValueObjectTests(unittest.TestCase):
    def test_claim_state_values(self):
        self.assertEqual(
            {state.value for state in ClaimState},
            {"none", "owned", "live_foreign", "stale"},
        )

    def test_claim_outcome_values(self):
        self.assertEqual(
            {outcome.value for outcome in ClaimOutcome},
            {"acquired", "held_by_live_foreign", "failed"},
        )

    def test_claim_is_frozen(self):
        claim = make_claim()
        with self.assertRaises(FrozenInstanceError):
            claim.owner_id = "other"

    def test_claim_round_trips_through_dict(self):
        claim = make_claim()
        restored = OwnershipClaim.from_dict(claim.to_dict())
        self.assertEqual(restored, claim)

    def test_from_dict_rejects_missing_required_fields(self):
        self.assertIsNone(OwnershipClaim.from_dict({"owner_id": "x"}))
        self.assertIsNone(OwnershipClaim.from_dict("not-a-dict"))
        self.assertIsNone(OwnershipClaim.from_dict({**make_claim().to_dict(), "pid": "nope"}))


class RunClaimStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runs = self.root / ".specify" / "workflows" / "runs"
        (self.runs / "run-1").mkdir(parents=True)
        self.alive: set[int] = set()
        self.starts: dict[int, str] = {}
        self.store = RunClaimStore(
            self.root,
            host="test-host",
            pid_alive=lambda pid: pid in self.alive,
            start_time=lambda pid: self.starts.get(pid),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _claim(self, owner_id="owner-1", pid=4321, process_start="100"):
        if pid:
            self.alive.add(pid)
            self.starts[pid] = process_start
        return OwnershipClaim(
            run_id="run-1",
            owner_id=owner_id,
            host="test-host",
            pid=pid,
            pgid=pid,
            process_start=process_start,
            created_at="2026-09-18T00:00:00+00:00",
        )

    def test_missing_run_directory_fails(self):
        outcome = self.store.acquire("nope", self._claim())
        self.assertEqual(outcome, ClaimOutcome.FAILED)

    def test_first_acquire_wins(self):
        outcome = self.store.acquire("run-1", self._claim())
        self.assertEqual(outcome, ClaimOutcome.ACQUIRED)
        self.assertTrue(self.store.claim_path("run-1").is_file())
        self.assertEqual(self.store.claim_state("run-1", "owner-1"), ClaimState.OWNED)

    def test_second_live_owner_is_refused(self):
        self.store.acquire("run-1", self._claim("owner-1"))
        self.alive.add(4321)
        outcome = self.store.acquire("run-1", self._claim("owner-2"))
        self.assertEqual(outcome, ClaimOutcome.HELD_BY_LIVE_FOREIGN)
        stored = self.store.read("run-1")
        self.assertEqual(stored.owner_id, "owner-1")
        self.assertEqual(self.store.claim_state("run-1", "owner-2"), ClaimState.LIVE_FOREIGN)

    def test_own_reacquire_is_allowed(self):
        self.store.acquire("run-1", self._claim("owner-1"))
        outcome = self.store.acquire("run-1", self._claim("owner-1"))
        self.assertEqual(outcome, ClaimOutcome.ACQUIRED)

    def test_release_only_removes_own_claim(self):
        self.store.acquire("run-1", self._claim("owner-1"))
        self.store.release("run-1", "owner-2")
        self.assertIsNotNone(self.store.read("run-1"))
        self.store.release("run-1", "owner-1")
        self.assertIsNone(self.store.read("run-1"))

    def test_claim_state_none_without_a_claim(self):
        self.assertEqual(self.store.claim_state("run-1", "owner-1"), ClaimState.NONE)

    def test_corrupt_claim_reads_as_none(self):
        self.store.claim_path("run-1").write_text("{not json", encoding="utf-8")
        self.assertIsNone(self.store.read("run-1"))
        self.assertEqual(self.store.claim_state("run-1", "owner-1"), ClaimState.NONE)

    def test_dead_owner_claim_is_stale_and_recovered(self):
        stored = self._claim("owner-1")
        self.store.acquire("run-1", stored)
        self.alive.discard(4321)
        self.assertEqual(self.store.claim_state("run-1", "owner-2"), ClaimState.STALE)
        outcome = self.store.acquire("run-1", replace(stored, owner_id="owner-2"))
        self.assertEqual(outcome, ClaimOutcome.ACQUIRED)
        self.assertEqual(self.store.read("run-1").owner_id, "owner-2")

    def test_cross_host_claim_is_always_live(self):
        stored = replace(self._claim("owner-1"), host="other-host")
        self.store.acquire("run-1", stored)
        self.alive.discard(4321)
        self.assertEqual(self.store.claim_state("run-1", "owner-2"), ClaimState.LIVE_FOREIGN)
        self.assertEqual(
            self.store.acquire("run-1", self._claim("owner-2")),
            ClaimOutcome.HELD_BY_LIVE_FOREIGN,
        )

    def test_reused_pid_with_changed_start_time_is_stale(self):
        self.store.acquire("run-1", self._claim("owner-1", pid=4321, process_start="100"))
        # The PID is alive again but with a different start time: it was reused.
        self.alive.add(4321)
        self.starts[4321] = "999"
        self.assertEqual(self.store.claim_state("run-1", "owner-2"), ClaimState.STALE)
        outcome = self.store.acquire("run-1", self._claim("owner-2", pid=4321, process_start="999"))
        self.assertEqual(outcome, ClaimOutcome.ACQUIRED)

    def test_missing_start_time_evidence_stays_live(self):
        stored = replace(self._claim("owner-1"), process_start=None)
        self.store.acquire("run-1", stored)
        self.starts.pop(4321, None)
        self.assertEqual(self.store.claim_state("run-1", "owner-2"), ClaimState.LIVE_FOREIGN)

    def test_acquisition_sends_no_signal(self):
        import inspect

        from workflow_cockpit.services import run_claim

        source = inspect.getsource(run_claim)
        self.assertNotIn("killpg", source)
        self.assertNotIn("SIGINT", source)
        self.assertNotIn("SIGTERM", source)

    def test_current_claim_records_process_identity(self):
        claim = current_claim("run-1", "owner-1", host="h", pid=999, pgid=999)
        self.assertEqual(claim.run_id, "run-1")
        self.assertEqual(claim.host, "h")
        self.assertEqual(claim.pid, 999)
        self.assertTrue(claim.created_at)


if __name__ == "__main__":
    unittest.main()
