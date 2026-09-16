import json
import tempfile
import unittest
from pathlib import Path

from workflow_cockpit.services.log_aggregator import RunLogAggregator


def _event(**values) -> str:
    return json.dumps(values) + "\n"


class RunLogAggregatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "log.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_attempts_from_complete_events(self):
        aggregator = RunLogAggregator(frozenset({"review"}))
        self.path.write_text(
            _event(event="step_started", step_id="review")
            + _event(event="step_completed", step_id="review", status="completed"),
            encoding="utf-8",
        )
        timings = aggregator.update(self.path)
        self.assertEqual(timings["review"].attempts, 1)
        self.assertEqual(timings["review"].status, "completed")

    def test_incomplete_trailing_record_is_retained(self):
        aggregator = RunLogAggregator(frozenset({"review"}))
        self.path.write_text('{"event":"step_started","step_id":"review"', encoding="utf-8")
        self.assertEqual(aggregator.update(self.path), {})
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("}\n")
        timings = aggregator.update(self.path)
        self.assertEqual(timings["review"].attempts, 1)

    def test_repeated_updates_do_not_double_count(self):
        aggregator = RunLogAggregator(frozenset({"review"}))
        self.path.write_text(_event(event="step_started", step_id="review"), encoding="utf-8")
        for _ in range(3):
            aggregator.update(self.path)
        self.assertEqual(aggregator.update(self.path)["review"].attempts, 1)

    def test_malformed_complete_event_is_diagnostic_only(self):
        aggregator = RunLogAggregator(frozenset({"review"}))
        self.path.write_text(
            _event(event="step_started", step_id="review") + "not json\n", encoding="utf-8"
        )
        timings = aggregator.update(self.path)
        self.assertEqual(timings["review"].attempts, 1)
        self.assertIn("malformed", aggregator.diagnostic)

    def test_bounded_reads_resume_without_losing_records(self):
        aggregator = RunLogAggregator(frozenset({"review"}), max_read_bytes=16)
        self.path.write_text(
            _event(event="step_started", step_id="review")
            + _event(event="step_started", step_id="review"),
            encoding="utf-8",
        )
        for _ in range(6):
            timings = aggregator.update(self.path)
        self.assertEqual(timings["review"].attempts, 2)

    def test_replaced_file_resets_aggregates(self):
        aggregator = RunLogAggregator(frozenset({"review"}))
        self.path.write_text(
            _event(event="step_started", step_id="review")
            + _event(event="step_started", step_id="review"),
            encoding="utf-8",
        )
        self.assertEqual(aggregator.update(self.path)["review"].attempts, 2)
        self.path.unlink()
        self.path.write_text(_event(event="step_started", step_id="review"), encoding="utf-8")
        self.assertEqual(aggregator.update(self.path)["review"].attempts, 1)


if __name__ == "__main__":
    unittest.main()
