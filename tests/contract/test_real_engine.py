"""Pinned real-``specify`` integration tests (skipped when unavailable).

These never use ambient PATH: they require an explicit executable from
``WORKFLOW_COCKPIT_REAL_SPECIFY`` or the sibling development venv. Workflows are tiny
deterministic shell workflows so no agent integration is needed.
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
from workflow_cockpit.bootstrap.compatibility import CompatibilityResult
from workflow_cockpit.session.cockpit_session import CockpitSession
from workflow_cockpit.session.dependencies import CockpitEnvironment


def _workflow(steps):
    return {
        "schema_version": "1.0",
        "workflow": {"id": "demo", "name": "Demo", "version": "1.0.0", "description": "demo"},
        "inputs": {"spec": {"type": "string", "required": True}},
        "steps": steps,
    }


@requires_real_specify
class RealEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify" / "workflows" / "runs").mkdir(parents=True)
        (self.root / ".specify" / "workflows" / "workflow-registry.json").write_text(
            json.dumps(
                {"schema_version": "1.0", "workflows": {"demo": {"name": "Demo", "enabled": True}}}
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=Test", "commit", "--allow-empty", "-qm", "init"],
            cwd=self.root,
            check=True,
        )
        self.compatibility = CompatibilityResult(
            executable=REAL_SPECIFY,
            version=Version("1.0.6.dev0"),
            raw="specify 1.0.6.dev0",
            prerelease=True,
            tested_range=">=1.0,<2.0",
        )
        self.session = None

    def tearDown(self):
        if self.session is not None:
            self.session.close()
        self.tmp.cleanup()

    def _install(self, steps):
        wf_dir = self.root / ".specify" / "workflows" / "demo"
        wf_dir.mkdir(parents=True, exist_ok=True)
        (wf_dir / "workflow.yml").write_text(yaml.safe_dump(_workflow(steps)), encoding="utf-8")

    def _install_gate(self, on_reject="retry"):
        wf_dir = self.root / ".specify" / "workflows" / "demo"
        wf_dir.mkdir(parents=True, exist_ok=True)
        definition = {
            "schema_version": "1.0",
            "workflow": {"id": "demo", "name": "Demo", "version": "1.0.0", "description": "demo"},
            "inputs": {
                "spec": {"type": "string", "required": True},
                "decision": {"type": "string", "default": ""},
            },
            "steps": [
                {"id": "prep", "type": "shell", "run": "echo prep"},
                {
                    "id": "review",
                    "type": "gate",
                    "message": "Approve?",
                    "options": ["approve", "reject"],
                    "verdict_input": "decision",
                    "on_reject": on_reject,
                },
                {"id": "finish", "type": "shell", "run": "echo finish"},
            ],
        }
        (wf_dir / "workflow.yml").write_text(yaml.safe_dump(definition), encoding="utf-8")

    def _session(self):
        self.session = CockpitSession(CockpitEnvironment(self.root, self.compatibility))
        self.session.select("demo")
        return self.session

    def _until(self, session, predicate, timeout=30.0):
        deadline = time.monotonic() + timeout
        snapshot = session.snapshot()
        while time.monotonic() < deadline and not predicate(snapshot):
            time.sleep(0.1)
            snapshot = session.snapshot()
        return snapshot

    def _until_terminal(self, session, timeout=30.0):
        return self._until(session, lambda snapshot: snapshot.terminal, timeout)

    def _until_paused(self, session, timeout=30.0):
        return self._until(
            session,
            lambda snapshot: snapshot.status == "paused" and not snapshot.process_live,
            timeout,
        )

    def test_linear_shell_workflow_succeeds(self):
        self._install(
            [
                {"id": "hello", "type": "shell", "run": "echo hello {{ inputs.spec }}"},
                {"id": "bye", "type": "shell", "run": "echo done"},
            ]
        )
        session = self._session()
        started = session.start({"spec": "world"})
        final = self._until_terminal(session)
        self.assertEqual(final.outcome.kind.value, "success")
        self.assertEqual(final.engine_status, "completed")
        run_dir = self.root / ".specify" / "workflows" / "runs" / started.run_id
        self.assertTrue((run_dir / "state.json").is_file())
        self.assertTrue((run_dir / "workflow.yml").is_file())

    def test_abort_pauses_engine_and_cockpit_owns_abort(self):
        self._install([{"id": "slow", "type": "shell", "run": "echo start; sleep 30"}])
        session = self._session()
        session.start({"spec": "world"})
        time.sleep(1.0)
        self.assertTrue(session.snapshot().process_live)
        session.abort()
        final = self._until_terminal(session, timeout=15.0)
        self.assertEqual(final.outcome.kind.value, "abort")
        self.assertFalse(final.process_live)

    def test_structured_gate_retry_then_approve(self):
        self._install_gate(on_reject="retry")
        session = self._session()
        session.start({"spec": "world"})
        paused = self._until_paused(session)
        self.assertIsNotNone(paused.gate)
        self.assertTrue(paused.gate.selectable)
        self.assertEqual(paused.gate.options, ("approve", "reject"))

        session.submit_decision("reject", paused.gate.token)
        retried = self._until_paused(session)
        self.assertEqual(retried.status, "paused")
        self.assertIsNotNone(retried.gate)
        self.assertTrue(retried.gate.selectable)

        session.submit_decision("approve", retried.gate.token)
        final = self._until_terminal(session)
        self.assertEqual(final.outcome.kind.value, "success")
        self.assertEqual(final.engine_status, "completed")

    def test_structured_gate_reject_skip_completes(self):
        self._install_gate(on_reject="skip")
        session = self._session()
        session.start({"spec": "world"})
        paused = self._until_paused(session)
        session.submit_decision("reject", paused.gate.token)
        final = self._until_terminal(session)
        self.assertEqual(final.outcome.kind.value, "success")
        self.assertEqual(final.engine_status, "completed")

    def test_structured_gate_selects_non_pty_transport(self):
        self._install_gate(on_reject="retry")
        session = self._session()
        session.start({"spec": "world"})
        paused = self._until_paused(session)
        self.assertTrue(paused.gate.selectable)
        self.assertFalse(session._supervisor.condition().stdin_pty)
        session.submit_decision("approve", paused.gate.token)
        final = self._until_terminal(session)
        self.assertEqual(final.outcome.kind.value, "success")

    def test_structured_gate_reject_abort(self):
        self._install_gate(on_reject="abort")
        session = self._session()
        session.start({"spec": "world"})
        paused = self._until_paused(session)
        session.submit_decision("reject", paused.gate.token)
        final = self._until_terminal(session)
        self.assertIsNotNone(final.outcome)
        self.assertEqual(final.engine_status, "aborted")

    def test_branch_creation_is_observed(self):
        self._install(
            [
                {"id": "branch", "type": "shell", "run": "git checkout -b feature/runway"},
                {"id": "done", "type": "shell", "run": "echo done"},
            ]
        )
        session = self._session()
        session.start({"spec": "world"})
        final = self._until_terminal(session)
        self.assertEqual(final.outcome.kind.value, "success")
        session.refresh_branch()
        self.assertEqual(session.snapshot().branch, "feature/runway")

    def test_no_gate_execution_never_surfaces_a_gate(self):
        self._install(
            [
                {"id": "first", "type": "shell", "run": "echo first"},
                {"id": "second", "type": "shell", "run": "echo second"},
            ]
        )
        session = self._session()
        session.start({"spec": "world"})
        saw_gate = False
        deadline = time.monotonic() + 30.0
        snapshot = session.snapshot()
        while time.monotonic() < deadline and not snapshot.terminal:
            if snapshot.gate is not None:
                saw_gate = True
            time.sleep(0.1)
            snapshot = session.snapshot()
        self.assertFalse(saw_gate)
        self.assertEqual(snapshot.outcome.kind.value, "success")

    def test_gate_over_empty_feature_directory(self):
        (self.root / ".specify" / "feature.json").write_text(
            json.dumps({"feature_directory": "specs/empty"}), encoding="utf-8"
        )
        (self.root / "specs" / "empty").mkdir(parents=True)
        self._install_gate()
        session = self._session()
        session.start({"spec": "world"})
        paused = self._until_paused(session)
        self.assertIsNotNone(paused.gate)
        self.assertTrue(paused.gate.selectable)
        review = session.refresh_review()
        self.assertTrue(review.empty)
        self.assertEqual(review.count, 0)

    def test_no_cockpit_history_outside_engine_metadata(self):
        self._install([{"id": "only", "type": "shell", "run": "echo only"}])
        before = self._tree()
        session = self._session()
        started = session.start({"spec": "world"})
        self._until_terminal(session)
        run_prefix = f".specify/workflows/runs/{started.run_id}/"
        allowed = {".specify/workflows/runs/current_run"}
        unexpected = {
            path
            for path in self._tree() - before
            if not path.startswith(run_prefix)
            and path not in allowed
            and not path.startswith(".git/")
        }
        self.assertEqual(unexpected, set(), f"Cockpit wrote unexpected history: {unexpected}")

    def _tree(self) -> set[str]:
        return {
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file()
        }


if __name__ == "__main__":
    unittest.main()
