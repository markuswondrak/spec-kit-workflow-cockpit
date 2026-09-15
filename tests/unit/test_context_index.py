import json
import tempfile
import unittest
from pathlib import Path

from tests.support import write_workflow
from workflow_cockpit.services.context_index import (
    CONTEXT_INDEX_RELATIVE,
    ContextIndexError,
    ContextIndexWriter,
)
from workflow_cockpit.services.definition import WorkflowDefinitionResolver

SKILL_PATH = (
    Path(__file__).resolve().parents[2]
    / "workflow_cockpit"
    / "skills"
    / "cockpit-run-context"
    / "SKILL.md"
)


class ContextIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_workflow(self.root)
        self.definition = WorkflowDefinitionResolver(self.root).resolve("demo")
        (self.root / "specs" / "demo").mkdir(parents=True, exist_ok=True)
        (self.root / ".specify" / "feature.json").write_text(
            json.dumps({"feature_directory": "specs/demo"}), encoding="utf-8"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_stable_path(self):
        writer = ContextIndexWriter(self.root)
        result = writer.write(run_id="cockpit-abc123", definition=self.definition, branch="main")
        index = self.root / CONTEXT_INDEX_RELATIVE
        self.assertEqual(result.path, index)
        self.assertTrue(index.is_file())
        self.assertEqual(result.relative, ".specify/workflows/runs/current_run")

    def test_index_points_to_authoritative_sources(self):
        writer = ContextIndexWriter(self.root)
        content = writer.render(run_id="cockpit-abc123", definition=self.definition, branch="main")
        run_dir = self.root / ".specify" / "workflows" / "runs" / "cockpit-abc123"
        for needle in (
            "state.json",
            "inputs.json",
            "log.jsonl",
            str(run_dir / "workflow.yml"),
            str(self.root / ".specify" / "workflows" / "demo" / "workflow.yml"),
            "git -C",
            "branch --show-current",
            ".specify/feature.json",
            "specs/demo",
        ):
            self.assertIn(needle, content)
        self.assertIn("cockpit-abc123", content)

    def test_missing_feature_directory_is_reported(self):
        (self.root / ".specify" / "feature.json").unlink()
        writer = ContextIndexWriter(self.root)
        content = writer.render(run_id="cockpit-abc123", definition=self.definition)
        self.assertIn("not declared", content)

    def test_escaping_feature_directory_not_referenced(self):
        outside = self.root.parent / "outside-feature"
        outside.mkdir(exist_ok=True)
        (self.root / ".specify" / "feature.json").write_text(
            json.dumps({"feature_directory": "../outside-feature"}), encoding="utf-8"
        )
        writer = ContextIndexWriter(self.root)
        content = writer.render(run_id="cockpit-abc123", definition=self.definition)
        self.assertIn("not declared", content)
        self.assertNotIn(str(outside), content)

    def test_run_id_with_separator_rejected(self):
        writer = ContextIndexWriter(self.root)
        for run_id in ("", "   ", "../evil", "a/b", "..", "\\evil"):
            with self.subTest(run_id=run_id):
                with self.assertRaises(ContextIndexError):
                    writer.write(run_id=run_id, definition=self.definition)

    def test_missing_run_files_tolerated(self):
        writer = ContextIndexWriter(self.root)
        result = writer.write(run_id="cockpit-abc123", definition=self.definition)
        self.assertTrue(result.path.is_file())
        self.assertFalse((self.root / ".specify" / "workflows" / "runs" / "cockpit-abc123").exists())

    def test_no_temp_files_remain(self):
        writer = ContextIndexWriter(self.root)
        result = writer.write(run_id="cockpit-abc123", definition=self.definition)
        leftovers = [path for path in result.path.parent.iterdir() if path.name.startswith(".current_run-")]
        self.assertEqual(leftovers, [])

    def test_lifecycle_safety_rules_in_index(self):
        writer = ContextIndexWriter(self.root)
        content = writer.render(run_id="cockpit-abc123", definition=self.definition)
        for rule in (
            "Workflow Cockpit alone starts, resumes, decides, and aborts",
            "`specify workflow run`",
            "`specify workflow resume`",
            "Gate check before editing",
            '"paused"',
        ):
            self.assertIn(rule, content)


class CockpitSkillTests(unittest.TestCase):
    def test_skill_is_shipped(self):
        self.assertTrue(SKILL_PATH.is_file())

    def test_skill_states_lifecycle_and_editing_rules(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        for rule in (
            "cockpit-run-context",
            ".specify/workflows/runs/current_run",
            "Workflow Cockpit alone starts, resumes, decides, and aborts",
            "`specify workflow run`",
            "`specify workflow resume`",
            "paused",
        ):
            self.assertIn(rule, content)


if __name__ == "__main__":
    unittest.main()
