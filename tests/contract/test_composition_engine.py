"""Composition contract tests against a real engine (skipped below 1.1.3).

The persisted execution tree is an engine-owned structure and Cockpit only
*reads* it, so the reading is proven equal to the engine's own view rather than
assumed: this test drives live composed runs and asserts Cockpit's active node,
scope path and scopes equal ``status --json`` (``gate.step_id``,
``gate.scope_path``, ``workflow_scopes``). It is the drift alarm for ADR 0015.

Requires ``WORKFLOW_COCKPIT_REAL_SPECIFY`` (or the sibling development venv)
pointing at a ``specify >= 1.1.3``; older engines cannot create composed runs.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import yaml
from packaging.version import Version

from tests.support import REAL_SPECIFY, requires_real_specify
from workflow_cockpit.bootstrap.compatibility import (
    CompatibilityResult,
    parse_version,
)
from workflow_cockpit.services.execution_tree import ExecutionTree
from workflow_cockpit.services.graph import graph_from_execution_tree
from workflow_cockpit.services.run_state import RunStateReader
from workflow_cockpit.session.cockpit_session import CockpitSession
from workflow_cockpit.session.dependencies import CockpitEnvironment

#: Composition exists from this engine version on.
COMPOSITION_VERSION = Version("1.1.3")


def _engine_version(executable: Path) -> Version | None:
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_version(result.stdout or result.stderr or "")


def _composed_engine_available() -> bool:
    if REAL_SPECIFY is None:
        return False
    version = _engine_version(REAL_SPECIFY)
    return version is not None and version >= COMPOSITION_VERSION


requires_composition = unittest.skipUnless(
    _composed_engine_available(),
    "a specify >= 1.1.3 executable is required for composition contract tests",
)

CHILD = {
    "workflow": {"id": "notes", "name": "Notes", "version": "1.0.0", "description": "notes"},
    "inputs": {"approval": {"type": "string", "default": ""}},
    "steps": [
        {"id": "draft", "type": "shell", "run": "echo draft"},
        {
            "id": "review",
            "type": "gate",
            "message": "Approve the notes?",
            "options": ["approve", "reject"],
            "verdict_input": "approval",
        },
        {"id": "publish-notes", "type": "shell", "run": "echo publish"},
    ],
}

PARENT = {
    "workflow": {"id": "release", "name": "Release", "version": "1.0.0", "description": "release"},
    "inputs": {"approval": {"type": "string", "default": ""}},
    "steps": [
        {"id": "build", "type": "shell", "run": "echo build"},
        {
            "id": "review-release",
            "type": "workflow",
            "workflow": "notes",
            "input": {"approval": "{{ inputs.approval }}"},
        },
        {"id": "publish", "type": "shell", "run": "echo publish"},
    ],
}


@requires_real_specify
@requires_composition
class CompositionContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        workflows = self.root / ".specify" / "workflows"
        (workflows / "runs").mkdir(parents=True)
        for workflow_id, definition in (("notes", CHILD), ("release", PARENT)):
            path = workflows / workflow_id
            path.mkdir(parents=True, exist_ok=True)
            (path / "workflow.yml").write_text(yaml.safe_dump(definition), encoding="utf-8")
        (workflows / "workflow-registry.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "workflows": {
                        "notes": {"name": "Notes", "version": "1.0.0", "enabled": True},
                        "release": {"name": "Release", "version": "1.0.0", "enabled": True},
                    },
                }
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=t@example.com",
                "-c",
                "user.name=Test",
                "commit",
                "--allow-empty",
                "-qm",
                "init",
            ],
            cwd=self.root,
            check=True,
        )
        self.compatibility = CompatibilityResult(
            executable=REAL_SPECIFY,
            version=_engine_version(REAL_SPECIFY),
            raw=f"specify {_engine_version(REAL_SPECIFY)}",
            prerelease=False,
            tested_range=">=1.0,<2.0",
        )
        self.session: CockpitSession | None = None

    def tearDown(self):
        if self.session is not None:
            self.session.close()
        self.tmp.cleanup()

    def _engine_status(self, run_id: str) -> dict:
        result = subprocess.run(
            [str(REAL_SPECIFY), "workflow", "status", run_id, "--json"],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return json.loads(result.stdout)

    def _until_paused(self, session, timeout=60.0):
        deadline = time.monotonic() + timeout
        snapshot = session.snapshot()
        while time.monotonic() < deadline and not (snapshot.status == "paused" and not snapshot.process_live):
            time.sleep(0.1)
            snapshot = session.snapshot()
        return snapshot

    def test_cockpit_active_node_and_scope_match_the_engine(self):
        self.session = CockpitSession(CockpitEnvironment(self.root, self.compatibility))
        self.session.select("release")
        self.session.start({"approval": ""})
        snapshot = self._until_paused(self.session)
        self.assertEqual(snapshot.status, "paused")

        run_id = self.session.run_id
        oracle = self._engine_status(run_id)
        state = RunStateReader(self.root, run_id).read()
        self.assertIsInstance(state.execution, ExecutionTree)
        active = state.execution.active
        self.assertIsNotNone(active)

        # The engine's own view of the same tree is the oracle.
        self.assertEqual(active.step_id, oracle["gate"]["step_id"])
        self.assertEqual(
            [str(part) for part in active.scope_path],
            [str(part) for part in oracle["gate"]["scope_path"]],
        )
        self.assertEqual(active.qualified_id, oracle["current_step_id"])

        # Every scope the engine reports is a bound call in Cockpit's reading.
        graph = graph_from_execution_tree(state.execution)
        cockpit_scopes = {
            tuple(str(part) for part in node.scope_path)
            for node in graph.nodes
            if node.is_call
        }
        for scope in oracle.get("workflow_scopes", []):
            self.assertIn(tuple(str(part) for part in scope["scope_path"]), cockpit_scopes)

    def test_cockpit_gate_snapshot_matches_the_engine(self):
        self.session = CockpitSession(CockpitEnvironment(self.root, self.compatibility))
        self.session.select("release")
        self.session.start({"approval": ""})
        snapshot = self._until_paused(self.session)
        oracle = self._engine_status(self.session.run_id)
        self.assertIsNotNone(snapshot.gate)
        self.assertEqual(snapshot.gate.step_id, oracle["gate"]["step_id"])
        self.assertEqual(snapshot.gate.message, oracle["gate"]["message"])
        self.assertEqual(list(snapshot.gate.options), list(oracle["gate"]["options"]))
        self.assertEqual(snapshot.gate.root_input, "approval")
        self.assertEqual(snapshot.gate.display_scope_path, "review-release > review")

    def test_cockpit_rejects_a_composition_the_engine_would_reject(self):
        """A verdict gate under a fan-out is refused before Start."""
        fanout = {
            "workflow": {"id": "fanout", "name": "Fanout", "version": "1.0.0"},
            "inputs": {"approval": {"type": "string", "default": ""}},
            "steps": [
                {
                    "id": "fan",
                    "type": "fan-out",
                    "items": ["a"],
                    "step": {
                        "id": "notes",
                        "type": "workflow",
                        "workflow": "notes",
                        "input": {"approval": "{{ inputs.approval }}"},
                    },
                }
            ],
        }
        path = self.root / ".specify" / "workflows" / "fanout"
        path.mkdir(parents=True, exist_ok=True)
        (path / "workflow.yml").write_text(yaml.safe_dump(fanout), encoding="utf-8")
        registry_path = self.root / ".specify" / "workflows" / "workflow-registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["workflows"]["fanout"] = {"name": "Fanout", "version": "1.0.0", "enabled": True}
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

        self.session = CockpitSession(CockpitEnvironment(self.root, self.compatibility))
        self.session.select("fanout")
        self.assertIn("fan-out", self.session.compatibility_error)


if __name__ == "__main__":
    unittest.main()
