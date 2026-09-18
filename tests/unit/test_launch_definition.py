import tempfile
import unittest
from pathlib import Path

import yaml

from workflow_cockpit.services.definition import DefinitionError
from workflow_cockpit.services.launch_definition import (
    MAX_LAUNCH_WORKFLOW_BYTES,
    definition_from_launch_copy,
)

LAUNCH_COPY = {
    "schema_version": "1.0",
    "workflow": {
        "id": "demo",
        "name": "Demo Workflow",
        "version": "1.0.0",
        "description": "A demo workflow",
    },
    "inputs": {"spec": {"type": "string", "required": True}},
    "steps": [
        {"id": "prepare", "command": "demo.prepare"},
        {
            "id": "review",
            "type": "gate",
            "message": "Review it",
            "options": ["approve", "reject"],
            "verdict_input": "review_verdict",
        },
        {"id": "finish", "command": "demo.finish"},
    ],
}


class LaunchDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "workflow.yml"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, data, *, text=None):
        if text is not None:
            self.path.write_text(text, encoding="utf-8")
        else:
            self.path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return self.path

    def test_parses_workflow_block_and_effective_steps(self):
        definition = definition_from_launch_copy(self._write(LAUNCH_COPY))
        self.assertEqual(definition.id, "demo")
        self.assertEqual(definition.name, "Demo Workflow")
        self.assertEqual(definition.version, "1.0.0")
        self.assertEqual(tuple(step.id for step in definition.steps), ("prepare", "review", "finish"))
        self.assertEqual(len(definition.effective_steps), 3)
        self.assertEqual(definition.effective_steps[1]["verdict_input"], "review_verdict")
        self.assertEqual(definition.source, self.path)

    def test_missing_file_raises(self):
        with self.assertRaises(DefinitionError):
            definition_from_launch_copy(self.path)

    def test_malformed_yaml_raises(self):
        self._write(None, text="workflow: [unclosed")
        with self.assertRaises(DefinitionError):
            definition_from_launch_copy(self.path)

    def test_non_mapping_raises(self):
        self._write(None, text="- just\n- a\n- list\n")
        with self.assertRaises(DefinitionError):
            definition_from_launch_copy(self.path)

    def test_missing_steps_raises(self):
        self._write({"workflow": {"id": "demo", "name": "Demo"}})
        with self.assertRaises(DefinitionError):
            definition_from_launch_copy(self.path)

    def test_oversized_copy_raises(self):
        self.path.write_bytes(b"x" * (MAX_LAUNCH_WORKFLOW_BYTES + 1))
        with self.assertRaises(DefinitionError):
            definition_from_launch_copy(self.path)


if __name__ == "__main__":
    unittest.main()
