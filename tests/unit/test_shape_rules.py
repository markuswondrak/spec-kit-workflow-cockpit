"""Start validates the whole composition, not only the root scope."""

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.composition_support import tree_graph
from tests.fixtures import composition as fx
from workflow_cockpit.services.definition import WorkflowDefinitionResolver
from workflow_cockpit.services.execution_tree import parse as parse_execution
from workflow_cockpit.services.graph import WorkflowDefinitionParser, graph_from_execution_tree
from workflow_cockpit.services.registry import RegistryError, WorkflowRegistry
from workflow_cockpit.services.shape_rules import validate_shape

VERSION = "1.0.6"


def _install(root: Path, workflow_id: str, data: dict, *, enabled: bool = True) -> None:
    path = root / ".specify" / "workflows" / workflow_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "workflow.yml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    registry_path = root / ".specify" / "workflows" / "workflow-registry.json"
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    else:
        registry = {"schema_version": "1.0", "workflows": {}}
    registry["workflows"][workflow_id] = {
        "name": workflow_id,
        "version": "1.0.0",
        "enabled": enabled,
    }
    registry_path.write_text(json.dumps(registry), encoding="utf-8")


def _validate(root: Path, workflow_id: str):
    resolver = WorkflowDefinitionResolver(root)

    def installed(target: str) -> str | None:
        try:
            entry = WorkflowRegistry(root).get(target)
        except RegistryError as exc:
            return str(exc)
        if entry is None:
            return f"target {target!r} is not installed"
        if not entry.enabled:
            return f"target {target!r} is disabled"
        return None

    definition = resolver.resolve(workflow_id)
    graph = WorkflowDefinitionParser(
        expand_calls=True,
        resolve_definition=resolver.effective_steps_of,
        check_installed=installed,
        root_workflow_id=definition.id,
    ).parse(definition.effective_steps)
    return validate_shape(
        graph, VERSION, resolve_definition=resolver.effective_steps_of, installed=installed
    )


class ShapeMatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _root_with_call(self, child_id="child", mapping=None):
        _install(
            self.root,
            "parent",
            {
                "workflow": {"id": "parent", "name": "Parent", "version": "1.0.0"},
                "inputs": {"approval": {"type": "string", "default": ""}},
                "steps": [
                    {
                        "id": "call",
                        "type": "workflow",
                        "workflow": child_id,
                        "input": mapping or {"approval": "{{ inputs.approval }}"},
                    }
                ],
            },
        )

    def test_interactive_gate_under_a_loop_inside_a_call_is_refused(self):
        _install(
            self.root,
            "child",
            {
                "workflow": {"id": "child", "name": "Child", "version": "1.0.0"},
                "steps": [
                    {
                        "id": "loop",
                        "type": "while",
                        "condition": "false",
                        "steps": [
                            {
                                "id": "ask",
                                "type": "gate",
                                "message": "Ask?",
                                "options": ["approve", "reject"],
                            }
                        ],
                    }
                ],
            },
        )
        self._root_with_call()
        support = _validate(self.root, "parent")
        self.assertFalse(support.ok)
        self.assertIn("ask", support.error)
        self.assertIn("call", support.error)

    def test_mixing_a_root_verdict_gate_with_a_child_interactive_gate_is_refused(self):
        _install(
            self.root,
            "child",
            {
                "workflow": {"id": "child", "name": "Child", "version": "1.0.0"},
                "steps": [
                    {
                        "id": "ask",
                        "type": "gate",
                        "message": "Ask?",
                        "options": ["approve", "reject"],
                    }
                ],
            },
        )
        _install(
            self.root,
            "parent",
            {
                "workflow": {"id": "parent", "name": "Parent", "version": "1.0.0"},
                "inputs": {"approval": {"type": "string", "default": ""}},
                "steps": [
                    {
                        "id": "root-gate",
                        "type": "gate",
                        "message": "Root?",
                        "options": ["approve", "reject"],
                        "verdict_input": "approval",
                    },
                    {"id": "call", "type": "workflow", "workflow": "child"},
                ],
            },
        )
        support = _validate(self.root, "parent")
        self.assertFalse(support.ok)
        self.assertIn("mix gates", support.error)

    def test_retry_on_an_interactive_gate_in_a_call_is_refused(self):
        _install(
            self.root,
            "child",
            {
                "workflow": {"id": "child", "name": "Child", "version": "1.0.0"},
                "steps": [
                    {
                        "id": "ask",
                        "type": "gate",
                        "message": "Ask?",
                        "options": ["approve", "reject"],
                        "on_reject": "retry",
                    }
                ],
            },
        )
        self._root_with_call()
        support = _validate(self.root, "parent")
        self.assertFalse(support.ok)
        self.assertIn("retry", support.error)

    def test_dynamic_message_in_a_call_is_refused(self):
        _install(
            self.root,
            "child",
            {
                "workflow": {"id": "child", "name": "Child", "version": "1.0.0"},
                "steps": [
                    {
                        "id": "ask",
                        "type": "gate",
                        "message": "{{ inputs.question }}",
                        "options": ["approve", "reject"],
                    }
                ],
            },
        )
        self._root_with_call()
        support = _validate(self.root, "parent")
        self.assertFalse(support.ok)
        self.assertIn("dynamic", support.error)

    def test_verdict_gate_under_a_fanout_through_a_call_is_refused(self):
        _install(
            self.root,
            "child",
            {
                "workflow": {"id": "child", "name": "Child", "version": "1.0.0"},
                "inputs": {"approval": {"type": "string", "default": ""}},
                "steps": [
                    {
                        "id": "ask",
                        "type": "gate",
                        "message": "Ask?",
                        "options": ["approve", "reject"],
                        "verdict_input": "approval",
                    }
                ],
            },
        )
        _install(
            self.root,
            "parent",
            {
                "workflow": {"id": "parent", "name": "Parent", "version": "1.0.0"},
                "inputs": {"approval": {"type": "string", "default": ""}},
                "steps": [
                    {
                        "id": "fan",
                        "type": "fan-out",
                        "items": ["a"],
                        "step": {
                            "id": "notes",
                            "type": "workflow",
                            "workflow": "child",
                            "input": {"approval": "{{ inputs.approval }}"},
                        },
                    }
                ],
            },
        )
        support = _validate(self.root, "parent")
        self.assertFalse(support.ok)
        self.assertIn("fan-out", support.error)

    def test_uninstalled_literal_target_is_refused_and_names_the_step(self):
        self._root_with_call(child_id="ghost")
        support = _validate(self.root, "parent")
        self.assertFalse(support.ok)
        self.assertIn("call", support.error)
        self.assertIn("ghost", support.error)

    def test_disabled_target_is_refused(self):
        _install(
            self.root,
            "child",
            {"workflow": {"id": "child", "name": "Child", "version": "1.0.0"}, "steps": []},
            enabled=False,
        )
        self._root_with_call()
        support = _validate(self.root, "parent")
        self.assertFalse(support.ok)
        self.assertIn("disabled", support.error)

    def test_dynamic_target_does_not_block_start(self):
        _install(
            self.root,
            "parent",
            {
                "workflow": {"id": "parent", "name": "Parent", "version": "1.0.0"},
                "inputs": {"target": {"type": "string", "default": "child"}},
                "steps": [
                    {
                        "id": "call",
                        "type": "workflow",
                        "workflow": "{{ inputs.target }}",
                    }
                ],
            },
        )
        support = _validate(self.root, "parent")
        self.assertTrue(support.ok, support.error)

    def test_untraceable_child_verdict_input_is_reported(self):
        _install(
            self.root,
            "child",
            {
                "workflow": {"id": "child", "name": "Child", "version": "1.0.0"},
                "inputs": {"approval": {"type": "string", "default": ""}},
                "steps": [
                    {
                        "id": "ask",
                        "type": "gate",
                        "message": "Ask?",
                        "options": ["approve", "reject"],
                        "verdict_input": "approval",
                    }
                ],
            },
        )
        self._root_with_call(mapping={"approval": "always"})
        support = _validate(self.root, "parent")
        self.assertFalse(support.ok)
        self.assertIn("cannot be decided", support.error)
        self.assertIn("call > ask", support.error)


class BoundShapeTests(unittest.TestCase):
    """A bound run is evaluated from its frozen tree, with nothing re-resolved."""

    def test_reference_bound_tree_passes_the_gate_rules(self):
        tree = parse_execution(fx.load_state("reference"))
        support = validate_shape(graph_from_execution_tree(tree), VERSION, targets_resolved=True)
        self.assertTrue(support.ok, support.error)

    def test_bound_fanout_verdict_gate_is_refused_from_the_frozen_tree(self):
        _tree, graph = tree_graph("fanout-verdict")
        support = validate_shape(graph, VERSION, targets_resolved=True)
        self.assertFalse(support.ok)
        self.assertIn("fan-out", support.error)

    def test_bound_interactive_gate_under_fanout_is_refused_from_the_frozen_tree(self):
        _tree, graph = tree_graph("fanout")
        support = validate_shape(graph, VERSION, targets_resolved=True)
        self.assertFalse(support.ok)
        self.assertIn("loop or fan-out", support.error)

    def test_bound_graph_is_not_re_resolved(self):
        """A changed install cannot affect a bound run's evaluation."""
        _tree, graph = tree_graph("reference")
        calls = [node for node in graph.nodes if node.is_call]
        self.assertTrue(all(node.target_resolved for node in calls))
        support = validate_shape(graph, VERSION, targets_resolved=True)
        self.assertTrue(support.ok)


if __name__ == "__main__":
    unittest.main()
