"""Timings and attempts are keyed per scope occurrence, never merged."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.fixtures import composition as fx
from workflow_cockpit.services.log_aggregator import ROOT_TIMING_PREFIX, RunLogAggregator


def timings_for(scenario: str):
    aggregator = RunLogAggregator(None)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "log.jsonl"
        path.write_bytes((fx.scenario_dir(scenario) / "log.jsonl").read_bytes())
        return aggregator.update(path)


class ScopeKeyTests(unittest.TestCase):
    def test_root_and_child_steps_with_the_same_id_stay_separate(self):
        timings = timings_for("collision")
        root_review = timings[("", (), "review")]
        child_review = timings[("release-notes", (2, "workflow", 1), "review")]
        self.assertEqual(root_review.attempts, 2)
        self.assertEqual(child_review.attempts, 1)
        self.assertEqual(child_review.status, "paused")
        self.assertNotEqual(root_review.started_at, child_review.started_at)

    def test_repeated_calls_get_their_own_scope_instance(self):
        timings = timings_for("loop-twice")
        first = timings[("release-notes", (0, 0, 0, "workflow", 1), "review")]
        second = timings[("release-notes", (0, 1, 0, "workflow", 1), "review")]
        self.assertEqual(first.attempts, 2)
        self.assertEqual(second.attempts, 1)
        self.assertIsNotNone(second.started_at)

    def test_a_retry_increments_only_its_own_scope_instance(self):
        timings = timings_for("loop-twice")
        # Iteration 0 paused and was resumed, so its gate ran twice; iteration 1
        # ran once. Neither counted the other.
        self.assertEqual(timings[("release-notes", (0, 0, 0, "workflow", 1), "review")].attempts, 2)
        self.assertEqual(timings[("release-notes", (0, 1, 0, "workflow", 1), "review")].attempts, 1)

    def test_loop_calls_are_distinguished_by_qualified_id(self):
        timings = timings_for("loop-twice")
        self.assertIn(("", (), "notes-call"), timings)
        self.assertIn(("", (), "notes-loop:notes-call:1"), timings)
        self.assertEqual(timings[("", (), "notes-call")].attempts, 2)


class LegacyLogTests(unittest.TestCase):
    def test_events_without_scope_fields_belong_to_the_root_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            path.write_text(
                '{"event":"step_started","step_id":"prepare","timestamp":"2026-09-13T12:00:00+00:00"}\n'
                '{"event":"step_completed","step_id":"prepare","status":"completed",'
                '"timestamp":"2026-09-13T12:00:04+00:00"}\n',
                encoding="utf-8",
            )
            aggregator = RunLogAggregator(None)
            timings = aggregator.update(path)
        key = (*ROOT_TIMING_PREFIX, "prepare")
        self.assertEqual(timings[key].attempts, 1)
        self.assertEqual(timings[key].status, "completed")
        self.assertEqual(timings[key].finished_at, datetime(2026, 9, 13, 12, 0, 4, tzinfo=timezone.utc))

    def test_declared_id_mode_matches_the_previous_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            path.write_text(
                '{"event":"step_started","step_id":"retry:verify:1"}\n'
                '{"event":"step_started","step_id":"retry:verify:2"}\n',
                encoding="utf-8",
            )
            aggregator = RunLogAggregator(frozenset({"verify"}))
            timings = aggregator.update(path)
        # Legacy callers still read the declared id, and iterations still add up.
        self.assertEqual(timings["verify"].attempts, 2)

    def test_declared_id_mode_drops_unknown_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            path.write_text('{"event":"step_started","step_id":"ghost"}\n', encoding="utf-8")
            aggregator = RunLogAggregator(frozenset({"verify"}))
            self.assertEqual(aggregator.update(path), {})


if __name__ == "__main__":
    unittest.main()
