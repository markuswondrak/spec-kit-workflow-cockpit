import tempfile
import unittest
from pathlib import Path

import yaml

from tests.support import write_workflow
from workflow_cockpit.services.definition import (
    DefinitionError,
    WorkflowDefinitionResolver,
    definition_signature,
    inputs_to_argv,
    normalized_signature,
    validate_inputs,
)

NESTED_WORKFLOW = {
    "schema_version": "1.0",
    "workflow": {"id": "nested", "name": "Nested", "version": "1.0.0", "description": "nested steps"},
    "inputs": {"spec": {"type": "string", "required": False, "default": ""}},
    "steps": [
        {"id": "resolve", "type": "shell", "run": "echo hi"},
        {
            "id": "maybe",
            "type": "if",
            "condition": "{{ inputs.spec }}",
            "then": [{"id": "branch", "type": "shell", "run": "echo b"}],
        },
        {"id": "finish", "type": "shell", "run": "echo done"},
    ],
}


class DefinitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_workflow(self.root)
        self.resolver = WorkflowDefinitionResolver(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_resolves_base(self):
        definition = self.resolver.resolve("demo")
        self.assertEqual(definition.name, "Demo Workflow")
        self.assertEqual([step.id for step in definition.steps], ["prepare", "review", "finish"])
        self.assertTrue(definition.steps[1].gate)
        self.assertEqual(definition.steps[1].options, ("approve", "reject"))

    def test_signature_ignores_nested_steps(self):
        write_workflow(self.root, NESTED_WORKFLOW, workflow_id="nested")
        definition = self.resolver.resolve("nested")
        self.assertEqual([step.id for step in definition.steps], ["resolve", "maybe", "finish"])
        self.assertEqual(normalized_signature(NESTED_WORKFLOW), definition_signature(definition))

    def test_parses_inputs(self):
        definition = self.resolver.resolve("demo")
        names = [spec.name for spec in definition.inputs]
        self.assertEqual(names, ["spec", "profile", "publish"])
        self.assertTrue(definition.inputs[0].required)
        self.assertEqual(definition.inputs[1].enum, ("standard", "extended"))

    def test_overlay_insert_after(self):
        overlay_dir = self.root / ".specify" / "workflows" / "overlays" / "demo"
        overlay_dir.mkdir(parents=True)
        (overlay_dir / "01-extra.yml").write_text(
            yaml.safe_dump(
                {
                    "id": "extra",
                    "extends": "demo",
                    "priority": 10,
                    "edits": [
                        {"insert_after": "prepare", "step": {"id": "lint", "command": "demo.lint"}}
                    ],
                }
            ),
            encoding="utf-8",
        )
        definition = self.resolver.resolve("demo")
        self.assertEqual([step.id for step in definition.steps], ["prepare", "lint", "review", "finish"])

    def test_overlay_replace(self):
        overlay_dir = self.root / ".specify" / "workflows" / "overlays" / "demo"
        overlay_dir.mkdir(parents=True)
        (overlay_dir / "01-replace.yml").write_text(
            yaml.safe_dump(
                {
                    "id": "replace",
                    "extends": "demo",
                    "edits": [
                        {"replace": "finish", "step": {"id": "finish", "command": "demo.done"}}
                    ],
                }
            ),
            encoding="utf-8",
        )
        definition = self.resolver.resolve("demo")
        self.assertEqual([step.id for step in definition.steps], ["prepare", "review", "finish"])

    def test_overlay_bad_anchor_fails(self):
        overlay_dir = self.root / ".specify" / "workflows" / "overlays" / "demo"
        overlay_dir.mkdir(parents=True)
        (overlay_dir / "01-bad.yml").write_text(
            yaml.safe_dump(
                {
                    "id": "bad",
                    "extends": "demo",
                    "edits": [{"remove": "missing"}],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(DefinitionError):
            self.resolver.resolve("demo")

    def test_disabled_overlay_skipped(self):
        overlay_dir = self.root / ".specify" / "workflows" / "overlays" / "demo"
        overlay_dir.mkdir(parents=True)
        (overlay_dir / "01-disabled.yml").write_text(
            yaml.safe_dump(
                {
                    "id": "disabled",
                    "extends": "demo",
                    "enabled": False,
                    "edits": [{"remove": "finish"}],
                }
            ),
            encoding="utf-8",
        )
        definition = self.resolver.resolve("demo")
        self.assertEqual([step.id for step in definition.steps], ["prepare", "review", "finish"])


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_workflow(self.root)
        self.definition = WorkflowDefinitionResolver(self.root).resolve("demo")

    def tearDown(self):
        self.tmp.cleanup()

    def test_required_missing(self):
        resolved, errors = validate_inputs(self.definition, {"spec": "  "})
        self.assertIn("spec", errors)
        self.assertNotIn("spec", resolved)

    def test_defaults_and_boolean(self):
        resolved, errors = validate_inputs(self.definition, {"spec": "search", "publish": "false"})
        self.assertEqual(errors, {})
        self.assertEqual(resolved["profile"], "standard")
        self.assertIs(resolved["publish"], False)

    def test_enum_rejected(self):
        _resolved, errors = validate_inputs(
            self.definition, {"spec": "search", "profile": "nope"}
        )
        self.assertIn("profile", errors)

    def test_inputs_to_argv(self):
        argv = inputs_to_argv({"spec": "a b", "publish": True})
        self.assertEqual(argv, ["-i", "spec=a b", "-i", "publish=true"])


if __name__ == "__main__":
    unittest.main()
