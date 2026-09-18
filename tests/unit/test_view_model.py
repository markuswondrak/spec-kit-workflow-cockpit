import unittest
from datetime import datetime, timedelta, timezone

from workflow_cockpit.services.graph import WorkflowDefinitionParser
from workflow_cockpit.services.log_aggregator import StepTiming
from workflow_cockpit.services.projection import GraphProjector
from workflow_cockpit.services.run_state import RunStateData
from workflow_cockpit.services.snapshot import RunSnapshot
from workflow_cockpit.ui.view_model import DURATION_COLUMN, render_runway

WORKFLOW = (
    {"id": "prepare", "command": "demo.prepare"},
    {"id": "verify", "command": "demo.verify"},
    {"id": "review", "type": "gate", "message": "Review", "options": ["approve", "reject"]},
)

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
START = NOW - timedelta(seconds=7)


def projection(status="paused", current="review"):
    timings = {
        "prepare": StepTiming(1, START, START + timedelta(seconds=3), "completed"),
        "verify": StepTiming(1, START, START + timedelta(seconds=5), "completed"),
    }
    return GraphProjector().project(
        WorkflowDefinitionParser().parse(WORKFLOW),
        RunStateData(status=status, current_step_id=current, step_results={}),
        timings,
        now=NOW,
    )


class RenderRunwayTests(unittest.TestCase):
    def setUp(self):
        self.rows = {row.id: row for row in render_runway(projection())}

    def test_gate_row_carries_no_duration(self):
        self.assertIn("gate", self.rows["review"].text)
        self.assertNotIn("00:0", self.rows["review"].text)

    def test_duration_sits_in_same_column_for_every_row(self):
        text = self.rows["prepare"].text
        column = len(text) - DURATION_COLUMN
        self.assertEqual(text[column:].strip(), "00:03")
        verify = self.rows["verify"].text
        self.assertEqual(len(verify) - DURATION_COLUMN, column)
        self.assertEqual(verify[column:].strip(), "00:05")

    def test_duration_column_holds_when_tail_varies(self):
        graph = WorkflowDefinitionParser().parse(
            (
                {"id": "prepare", "command": "demo.prepare"},
                {"id": "again", "command": "demo.again"},
            )
        )
        start = NOW - timedelta(seconds=4)
        projection = GraphProjector().project(
            graph,
            RunStateData(status="running", current_step_id="again", step_results={}),
            {
                "prepare": StepTiming(3, start, start + timedelta(seconds=2), "completed"),
                "again": StepTiming(1, start, None, "running"),
            },
            now=NOW,
        )
        rows = render_runway(projection)
        columns = [len(row.text) - DURATION_COLUMN for row in rows]
        self.assertEqual(columns[0], columns[1])
        self.assertIn("#3", rows[0].text)


class SnapshotDefaultsTests(unittest.TestCase):
    def test_adopted_defaults_to_false(self):
        self.assertFalse(RunSnapshot(run_id="cockpit-1").adopted)

    def test_read_only_defaults_to_false(self):
        self.assertFalse(RunSnapshot(run_id="cockpit-1").read_only)


if __name__ == "__main__":
    unittest.main()
