"""Start never offers an input that only feeds a child gate (FR-009, SC-002)."""

import tempfile
import unittest
from pathlib import Path

import yaml

from tests.composition_support import write_project
from tests.fixtures import composition as fx
from workflow_cockpit.services.definition import WorkflowDefinitionResolver

RENAMED = {
    "workflow": {"id": "release", "name": "Release", "version": "1.0.0"},
    "inputs": {
        "release_approval": {"type": "string", "default": ""},
        "ordinary": {"type": "string", "default": "x"},
    },
    "steps": [
        {"id": "build", "type": "shell", "run": "true"},
        {
            "id": "review-release",
            "type": "workflow",
            "workflow": "release-notes",
            "input": {"approval": "{{ inputs.release_approval }}"},
        },
        {"id": "publish", "type": "shell", "run": "true"},
    ],
}


class PresentedInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def resolve_reference(self):
        write_project(self.root, "reference")
        return WorkflowDefinitionResolver(self.root).resolve("release")

    def test_reference_definition_offers_no_verdict_only_input(self):
        definition = self.resolve_reference()
        self.assertEqual([spec.name for spec in definition.inputs], ["approval"])
        self.assertEqual(definition.presented_inputs, ())
        self.assertEqual(definition.cross_scope_verdict_inputs, frozenset({"approval"}))

    def test_renamed_mapping_hides_the_parent_name(self):
        write_project(self.root, "reference")
        (self.root / ".specify" / "workflows" / "release" / "workflow.yml").write_text(
            yaml.safe_dump(RENAMED, sort_keys=False), encoding="utf-8"
        )
        definition = WorkflowDefinitionResolver(self.root).resolve("release")
        names = [spec.name for spec in definition.presented_inputs]
        self.assertNotIn("release_approval", names)
        self.assertIn("ordinary", names)

    def test_ordinary_launch_inputs_are_still_offered(self):
        data = yaml.safe_load((fx.scenario_dir("reference") / "workflow.yml").read_text())
        data["inputs"]["ticket"] = {"type": "string", "default": ""}
        write_project(self.root, "reference")
        (self.root / ".specify" / "workflows" / "release" / "workflow.yml").write_text(
            yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
        )
        definition = WorkflowDefinitionResolver(self.root).resolve("release")
        self.assertEqual([spec.name for spec in definition.presented_inputs], ["ticket"])

    def test_a_literal_mapping_is_reported_untraceable(self):
        data = yaml.safe_load((fx.scenario_dir("reference") / "workflow.yml").read_text())
        for step in data["steps"]:
            if step.get("id") == "review-release":
                step["input"] = {"approval": "always"}
        write_project(self.root, "reference")
        (self.root / ".specify" / "workflows" / "release" / "workflow.yml").write_text(
            yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
        )
        definition = WorkflowDefinitionResolver(self.root).resolve("release")
        # Nothing was traced, so no root input is hidden and the composition is
        # reported as undecidable instead of silently offering the input.
        self.assertEqual(definition.cross_scope_verdict_inputs, frozenset())
        self.assertEqual([spec.name for spec in definition.presented_inputs], ["approval"])


if __name__ == "__main__":
    unittest.main()
