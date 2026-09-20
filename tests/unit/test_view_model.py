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


LONG_WORKFLOW = (
    {"id": "bug-assess", "command": "demo.assess"},
    {
        "id": "assessment-gate",
        "type": "gate",
        "message": "Assess",
        "options": ["approve", "reject"],
    },
    {"id": "bug-verification", "command": "demo.verify"},
)

NARROW_WIDTH = 33


def long_projection(status="running", current="bug-assess"):
    return GraphProjector().project(
        WorkflowDefinitionParser().parse(LONG_WORKFLOW),
        RunStateData(status=status, current_step_id=current, step_results={}),
    )


class NarrowRunwayTests(unittest.TestCase):
    """Long declared names stay recoverable in the narrow cockpit sidebar."""

    def setUp(self):
        self.rows = {row.id: row for row in render_runway(long_projection(), width=NARROW_WIDTH)}

    def test_full_label_is_kept_as_data_when_visible_text_is_clipped(self):
        self.assertEqual(self.rows["assessment-gate"].full_label, "assessment-gate")
        self.assertEqual(self.rows["bug-verification"].full_label, "bug-verification")

    def test_gate_row_does_not_reserve_the_unused_duration_column(self):
        # A gate renders a tail but never a duration; reclaiming the duration
        # column is what keeps "assessment-gate" whole at sidebar width.
        self.assertIn("assessment-gate", self.rows["assessment-gate"].text)
        self.assertNotIn("00:0", self.rows["assessment-gate"].text)

    def test_flow_only_row_reclaims_tail_and_duration_columns(self):
        self.assertIn("bug-verification", self.rows["bug-verification"].text)

    def test_visible_text_preserves_the_leading_identifier(self):
        graph = WorkflowDefinitionParser().parse(
            ({"id": "assessment-gate-with-a-very-long-name", "command": "demo.assess"},)
        )
        projection = GraphProjector().project(
            graph,
            RunStateData(status="running", current_step_id=None, step_results={}),
        )
        (row,) = render_runway(projection, width=NARROW_WIDTH)
        self.assertTrue(row.text.startswith("[ ] assessment-gate"))
        self.assertIn("...", row.text)
        self.assertNotIn("long-name", row.text)

    def test_label_budget_matches_the_columns_actually_rendered(self):
        graph = WorkflowDefinitionParser().parse(
            (
                {"id": "with-tail", "name": "x" * 40, "command": "demo.a"},
                {"id": "without-tail", "name": "x" * 40, "command": "demo.b"},
            )
        )
        projection = GraphProjector().project(
            graph,
            RunStateData(status="running", current_step_id="without-tail", step_results={}),
            {"with-tail": StepTiming(3, NOW, NOW, "completed")},
            now=NOW,
        )
        rows = {row.id: row for row in render_runway(projection, width=NARROW_WIDTH)}
        self.assertIn("#3", rows["with-tail"].text)
        self.assertEqual(len(rows["with-tail"].text), len(rows["without-tail"].text))
        self.assertEqual(
            len(rows["with-tail"].text) - DURATION_COLUMN,
            len(rows["without-tail"].text) - DURATION_COLUMN,
        )


class SnapshotDefaultsTests(unittest.TestCase):
    def test_adopted_defaults_to_false(self):
        self.assertFalse(RunSnapshot(run_id="cockpit-1").adopted)

    def test_read_only_defaults_to_false(self):
        self.assertFalse(RunSnapshot(run_id="cockpit-1").read_only)


if __name__ == "__main__":
    unittest.main()
