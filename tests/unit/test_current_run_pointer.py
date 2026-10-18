"""The pointer pair: JSON first, Markdown as commit marker, disagreement reported."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from workflow_cockpit.services import current_run_pointer as pointer
from workflow_cockpit.services.current_run_pointer import (
    CURRENT_RUN_JSON_RELATIVE,
    CURRENT_RUN_RELATIVE,
    POINTER_SCHEMA_VERSION,
    CurrentRunPointerReader,
    CurrentRunPointerWriter,
    PointerState,
)


class PointerWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_json_is_written_before_the_markdown_commit_marker(self):
        calls: list[str] = []
        original = pointer._atomic_write

        def recorder(path, content, *, prefix):
            calls.append(path.name)
            return original(path, content, prefix=prefix)

        pointer._atomic_write = recorder
        try:
            CurrentRunPointerWriter(self.root).write(run_id="cockpit-abc", workflow_id="demo")
        finally:
            pointer._atomic_write = original
        self.assertEqual(calls, ["current_run.json", "current_run"])

    def test_both_files_carry_the_same_run_identity(self):
        CurrentRunPointerWriter(self.root).write(
            run_id="cockpit-abc", markdown=None, workflow_id="demo"
        )
        read = CurrentRunPointerReader(self.root).read()
        self.assertEqual(read.state, PointerState.OK)
        self.assertEqual(read.run_id, "cockpit-abc")
        self.assertEqual(read.markdown_run_id, read.json_run_id)

    def test_json_carries_only_the_pointer_fields(self):
        CurrentRunPointerWriter(self.root).write(run_id="cockpit-abc", workflow_id="demo")
        payload = json.loads((self.root / CURRENT_RUN_JSON_RELATIVE).read_text(encoding="utf-8"))
        self.assertEqual(
            set(payload), {"schema_version", "run_id", "run_dir", "workflow_id"}
        )
        self.assertEqual(payload["schema_version"], POINTER_SCHEMA_VERSION)
        self.assertEqual(payload["run_dir"], ".specify/workflows/runs/cockpit-abc")
        self.assertEqual(payload["workflow_id"], "demo")

    def test_no_temp_files_remain(self):
        CurrentRunPointerWriter(self.root).write(run_id="cockpit-abc")
        runs = (self.root / CURRENT_RUN_RELATIVE).parent
        leftovers = [path.name for path in runs.iterdir() if path.suffix == ".tmp"]
        self.assertEqual(leftovers, [])

    def test_clear_removes_both_when_they_name_the_run(self):
        writer = CurrentRunPointerWriter(self.root)
        writer.write(run_id="cockpit-abc")
        self.assertTrue(writer.clear_if_current("cockpit-abc"))
        self.assertFalse((self.root / CURRENT_RUN_RELATIVE).exists())
        self.assertFalse((self.root / CURRENT_RUN_JSON_RELATIVE).exists())

    def test_clear_leaves_another_run_alone(self):
        writer = CurrentRunPointerWriter(self.root)
        writer.write(run_id="cockpit-abc")
        self.assertFalse(writer.clear_if_current("cockpit-other"))
        self.assertTrue((self.root / CURRENT_RUN_JSON_RELATIVE).exists())


class PointerReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_markdown(self, run_id: str) -> None:
        path = self.root / CURRENT_RUN_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Cockpit run context\n\n- Run ID: `{run_id}`\n", encoding="utf-8")

    def _write_json(self, run_id: str) -> None:
        path = self.root / CURRENT_RUN_JSON_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "run_id": run_id}), encoding="utf-8")

    def test_empty_when_neither_pointer_exists(self):
        read = CurrentRunPointerReader(self.root).read()
        self.assertEqual(read.state, PointerState.EMPTY)
        self.assertIsNone(read.run_id)

    def test_disagreement_when_the_two_name_different_runs(self):
        self._write_markdown("cockpit-a")
        self._write_json("cockpit-b")
        read = CurrentRunPointerReader(self.root).read()
        self.assertEqual(read.state, PointerState.DISAGREEMENT)
        self.assertIsNone(read.run_id)
        self.assertIn("cockpit-a", read.detail)
        self.assertIn("cockpit-b", read.detail)

    def test_disagreement_when_only_the_markdown_exists(self):
        self._write_markdown("cockpit-a")
        read = CurrentRunPointerReader(self.root).read()
        self.assertEqual(read.state, PointerState.DISAGREEMENT)
        self.assertEqual(read.markdown_run_id, "cockpit-a")

    def test_disagreement_when_only_the_json_exists(self):
        self._write_json("cockpit-a")
        read = CurrentRunPointerReader(self.root).read()
        self.assertEqual(read.state, PointerState.DISAGREEMENT)
        self.assertEqual(read.json_run_id, "cockpit-a")

    def test_unreadable_when_both_exist_but_neither_names_a_run(self):
        path = self.root / CURRENT_RUN_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Cockpit run context\n\nno run id line here\n", encoding="utf-8")
        json_path = self.root / CURRENT_RUN_JSON_RELATIVE
        json_path.write_text("not an object", encoding="utf-8")
        read = CurrentRunPointerReader(self.root).read()
        self.assertEqual(read.state, PointerState.UNREADABLE)
        self.assertFalse(read.usable)


if __name__ == "__main__":
    unittest.main()
