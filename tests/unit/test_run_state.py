import json
import tempfile
import unittest
from pathlib import Path

from tests.support import write_run
from workflow_cockpit.services.run_state import RunStateReader


class RunStateReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_run(self.root, "cockpit-a", status="running", current_step_id="prepare")

    def tearDown(self):
        self.tmp.cleanup()

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


if __name__ == "__main__":
    unittest.main()
