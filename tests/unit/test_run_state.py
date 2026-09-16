import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import write_run
from workflow_cockpit.services.run_state import Freshness, RunStateReader


class RunStateReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_run(self.root, "cockpit-a", status="running", current_step_id="prepare")

    def tearDown(self):
        self.tmp.cleanup()

    def _run_dir(self) -> Path:
        return self.root / ".specify" / "workflows" / "runs" / "cockpit-a"

    def _write_state(self, text: str) -> None:
        (self._run_dir() / "state.json").write_text(text, encoding="utf-8")

    def test_reads_state_and_inputs(self):
        data = RunStateReader(self.root, "cockpit-a").read()
        self.assertIsNotNone(data)
        self.assertEqual(data.status, "running")
        self.assertEqual(data.current_step_id, "prepare")
        self.assertEqual(data.inputs["spec"], "search")

    def test_missing_run_returns_none(self):
        self.assertIsNone(RunStateReader(self.root, "cockpit-missing").read())

    def test_partial_trailing_log_record_ignored(self):
        run_dir = self.root / ".specify" / "workflows" / "runs" / "cockpit-a"
        (run_dir / "log.jsonl").write_text('{"event":"a"}\n{"event":', encoding="utf-8")
        data = RunStateReader(self.root, "cockpit-a").read()
        self.assertEqual([entry["event"] for entry in data.log_tail], ["a"])

    def test_partial_state_is_tolerated(self):
        run_dir = self.root / ".specify" / "workflows" / "runs" / "cockpit-a"
        (run_dir / "state.json").write_text('{"status": "run', encoding="utf-8")
        data = RunStateReader(self.root, "cockpit-a").read()
        self.assertFalse(data.complete)
        self.assertEqual(data.status, "initializing")

    def test_atomic_replacement_detected(self):
        reader = RunStateReader(self.root, "cockpit-a")
        first = reader.read()
        run_dir = self.root / ".specify" / "workflows" / "runs" / "cockpit-a"
        state = json.loads((run_dir / "state.json").read_text())
        state["status"] = "paused"
        tmp = run_dir / "state.json.tmp"
        tmp.write_text(json.dumps(state))
        tmp.replace(run_dir / "state.json")
        second = reader.read()
        self.assertEqual(first.status, "running")
        self.assertEqual(second.status, "paused")

    def test_startup_partial_state_is_not_stale(self):
        (self._run_dir() / "state.json").write_text('{"status": "run', encoding="utf-8")
        data = RunStateReader(self.root, "cockpit-a").read()
        self.assertFalse(data.complete)
        self.assertFalse(data.stale)
        self.assertEqual(data.state_freshness, Freshness.PENDING)
        self.assertEqual(data.diagnostic, "")

    def test_stable_failed_state_after_good_read_is_stale(self):
        reader = RunStateReader(self.root, "cockpit-a")
        self.assertEqual(reader.read().status, "running")
        self._write_state('{"status": "pause')  # stable, undecodable/partial
        data = reader.read()
        self.assertTrue(data.stale)
        self.assertEqual(data.status, "running")
        self.assertIn("state.json", data.diagnostic)
        self.assertEqual(data.state_freshness, Freshness.STALE)

    def test_structurally_invalid_state_after_good_read_is_stale(self):
        reader = RunStateReader(self.root, "cockpit-a")
        self.assertEqual(reader.read().status, "running")
        self._write_state("[]")
        data = reader.read()
        self.assertTrue(data.stale)
        self.assertEqual(data.status, "running")
        self.assertIn("state.json", data.diagnostic)

    def test_structurally_invalid_inputs_after_good_read_are_preserved(self):
        reader = RunStateReader(self.root, "cockpit-a")
        self.assertEqual(reader.read().inputs, {"spec": "search"})
        (self._run_dir() / "inputs.json").write_text('{"inputs": []}', encoding="utf-8")
        data = reader.read()
        self.assertTrue(data.stale)
        self.assertEqual(data.inputs, {"spec": "search"})
        self.assertIn("inputs.json", data.diagnostic)

    def test_in_progress_replacement_is_not_stale(self):
        reader = RunStateReader(self.root, "cockpit-a")
        self.assertEqual(reader.read().status, "running")
        original = reader._signature
        state_calls = {"count": 0}

        def flaky(path):
            signature = original(path)
            if path.name == "state.json":
                state_calls["count"] += 1
                if state_calls["count"] % 2 == 1:
                    return (signature[0], signature[1] + 1, signature[2])
            return signature

        with mock.patch.object(RunStateReader, "_signature", staticmethod(flaky)):
            data = reader.read()
        self.assertEqual(data.status, "running")
        self.assertFalse(data.stale)
        self.assertEqual(data.state_freshness, Freshness.UNSTABLE)

    def test_unstable_read_does_not_cache_the_stale_value_as_fresh(self):
        reader = RunStateReader(self.root, "cockpit-a")
        self.assertEqual(reader.read().status, "running")
        original = reader._signature
        calls = {"count": 0}

        def flaky(path):
            signature = original(path)
            if path.name == "state.json":
                calls["count"] += 1
                if calls["count"] % 2 == 1:
                    return (signature[0], signature[1] + 1, signature[2])
            return signature

        with mock.patch.object(RunStateReader, "_signature", staticmethod(flaky)):
            unstable = reader.read()
        self.assertEqual(unstable.state_freshness, Freshness.UNSTABLE)
        self.assertEqual(unstable.status, "running")

        self._write_state(json.dumps({"status": "paused"}))
        data = reader.read()
        self.assertEqual(data.status, "paused")
        self.assertEqual(data.state_freshness, Freshness.OK)

    def test_unchanged_sources_are_not_reparsed(self):
        reader = RunStateReader(self.root, "cockpit-a")
        reader.read()
        real_loads = json.loads
        calls = {"count": 0}

        def counting(*args, **kwargs):
            calls["count"] += 1
            return real_loads(*args, **kwargs)

        with mock.patch("workflow_cockpit.services.run_state.json.loads", side_effect=counting):
            reader.read()
        self.assertEqual(calls["count"], 0)

    def test_partial_trailing_log_is_not_stale_and_complete_diagnostic(self):
        run_dir = self._run_dir()
        (run_dir / "log.jsonl").write_text('{"event":"step_started"}\n{"event":', encoding="utf-8")
        data = RunStateReader(self.root, "cockpit-a").read()
        self.assertFalse(data.stale)
        self.assertEqual(data.log_freshness, Freshness.OK)
        self.assertEqual(data.diagnostic, "")

    def test_complete_malformed_log_event_is_diagnostic_only(self):
        run_dir = self._run_dir()
        (run_dir / "log.jsonl").write_text('{"event":"step_started"}\nnot json\n', encoding="utf-8")
        data = RunStateReader(self.root, "cockpit-a").read()
        self.assertFalse(data.stale)
        self.assertIn("malformed", data.diagnostic)

    def test_missing_log_after_good_read_is_stale(self):
        reader = RunStateReader(self.root, "cockpit-a")
        run_dir = self._run_dir()
        (run_dir / "log.jsonl").write_text('{"event":"step_started"}\n', encoding="utf-8")
        self.assertTrue(reader.read().log_tail)
        (run_dir / "log.jsonl").unlink()
        data = reader.read()
        self.assertTrue(data.stale)
        self.assertEqual(data.log_freshness, Freshness.STALE)

    def test_missing_empty_log_after_good_read_is_stale(self):
        reader = RunStateReader(self.root, "cockpit-a")
        run_dir = self._run_dir()
        (run_dir / "log.jsonl").write_text("", encoding="utf-8")
        self.assertEqual(reader.read().log_tail, ())
        (run_dir / "log.jsonl").unlink()
        data = reader.read()
        self.assertTrue(data.stale)
        self.assertEqual(data.log_freshness, Freshness.STALE)

    def test_bounded_log_tail_window_reads_end_of_file(self):
        run_dir = self._run_dir()
        lines = "".join(json.dumps({"event": "noise", "n": index}) + "\n" for index in range(2000))
        lines += json.dumps({"event": "step_started", "step_id": "prepare"}) + "\n"
        (run_dir / "log.jsonl").write_text(lines, encoding="utf-8")
        reader = RunStateReader(self.root, "cockpit-a", log_tail=5, log_window_bytes=512)
        data = reader.read()
        self.assertLessEqual(len(data.log_tail), 5)
        self.assertEqual(data.log_tail[-1]["event"], "step_started")


if __name__ == "__main__":
    unittest.main()
