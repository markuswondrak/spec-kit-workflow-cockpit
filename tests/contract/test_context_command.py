"""Contract tests for ``workflow-cockpit context --json`` over prepared run trees.

The command is invoked through its real entry point, so exit codes, stdout shape,
and read-only behavior are asserted end to end with no host and no UI.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests.fixtures import run_trees as rt
from workflow_cockpit.cli import main


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def envelope_of(text: str) -> dict:
    return json.loads(text)


class ContextCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def context(self, *extra: str) -> tuple[int, dict, str]:
        code, out, err = run_cli("--project", str(self.root), "context", "--json", *extra)
        return code, (envelope_of(out) if out.strip() else {}), err

    def test_live_run_exits_zero_with_a_versioned_envelope(self):
        rt.live_flat(self.root)
        rt.write_feature_directory(self.root)
        code, envelope, _err = self.context()
        self.assertEqual(code, 0)
        self.assertEqual(envelope["schema_version"], 1)
        self.assertEqual(envelope["run"]["run_id"], rt.RUN_ID)
        self.assertEqual(envelope["step"]["step_id"], "prepare")

    def test_composed_run_reports_the_inner_scope(self):
        rt.live_composed(self.root)
        rt.write_feature_directory(self.root)
        code, envelope, _err = self.context()
        self.assertEqual(code, 0)
        self.assertEqual(envelope["step"]["scope_path"], ["review-release"])

    def test_paused_gate_reports_the_declared_options(self):
        rt.paused_gate(self.root)
        rt.write_feature_directory(self.root)
        code, envelope, _err = self.context()
        self.assertEqual(code, 0)
        self.assertEqual(envelope["gate"]["options"], ["approve", "reject"])
        self.assertEqual(envelope["gate"]["ledger"]["state"], "open")

    def test_missing_state_exits_zero_with_a_condition(self):
        rt.missing_state(self.root)
        code, envelope, _err = self.context()
        self.assertEqual(code, 0)
        self.assertIn(
            ("state.json", "missing"),
            {(item["source"], item["kind"]) for item in envelope["conditions"]},
        )
        self.assertIsNone(envelope["run"]["status"])

    def test_no_run_exits_zero_with_an_empty_run(self):
        rt.no_run(self.root)
        code, envelope, _err = self.context()
        self.assertEqual(code, 0)
        self.assertIsNone(envelope["run"])
        self.assertEqual(envelope["pointer"]["state"], "empty")

    def test_file_variant_populates_the_bounded_file_field(self):
        rt.live_flat(self.root)
        rt.write_feature_directory(self.root)
        code, envelope, _err = self.context("--file", "specs/demo/spec.md")
        self.assertEqual(code, 0)
        self.assertEqual(envelope["file"]["path"], "specs/demo/spec.md")
        self.assertEqual(envelope["file"]["content"], "# Spec\n")

    def test_file_outside_the_index_exits_two(self):
        rt.live_flat(self.root)
        rt.write_feature_directory(self.root)
        code, _envelope, err = self.context("--file", ".specify/feature.json")
        self.assertEqual(code, 2)
        self.assertIn("Feature Files index", err)

    def test_disagreement_variant_reports_the_pointer_condition(self):
        rt.live_flat(self.root)
        json_path = self.root / ".specify" / "workflows" / "runs" / "current_run.json"
        json_path.write_text('{"schema_version": 1, "run_id": "cockpit-other"}', encoding="utf-8")
        code, envelope, _err = self.context()
        self.assertEqual(code, 0)
        self.assertEqual(envelope["pointer"]["state"], "disagreement")
        self.assertIsNone(envelope["run"])

    def test_no_project_exits_two(self):
        empty = Path(tempfile.mkdtemp())
        code, _out, err = run_cli("--project", str(empty), "context", "--json")
        self.assertEqual(code, 2)
        self.assertIn("not an initialized Spec Kit project", err)

    def test_read_command_leaves_the_run_tree_untouched(self):
        rt.live_flat(self.root)
        rt.write_feature_directory(self.root)
        before = rt.run_tree_hash(self.root)
        self.context()
        self.context("--file", "specs/demo/spec.md")
        self.assertEqual(before, rt.run_tree_hash(self.root))


if __name__ == "__main__":
    unittest.main()
