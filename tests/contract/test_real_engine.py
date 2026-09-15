"""Pinned real-``specify`` integration tests (skipped when unavailable).

These never use ambient PATH: they require an explicit executable from
``WORKFLOW_COCKPIT_REAL_SPECIFY`` or the sibling development venv. Workflows are tiny
deterministic shell workflows so no agent integration is needed.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import yaml
from packaging.version import Version

from workflow_cockpit.bootstrap.compatibility import CompatibilityResult
from workflow_cockpit.session.cockpit_session import CockpitSession
from workflow_cockpit.session.dependencies import CockpitEnvironment

_CANDIDATES = [
    os.environ.get("WORKFLOW_COCKPIT_REAL_SPECIFY"),
    "/home/markus/workspace/spec-kit/.venv/bin/specify",
]
REAL_SPECIFY = next(
    (Path(path) for path in _CANDIDATES if path and Path(path).exists()),
    None,
)


def _workflow(steps):
    return {
        "schema_version": "1.0",
        "workflow": {"id": "demo", "name": "Demo", "version": "1.0.0", "description": "demo"},
        "inputs": {"spec": {"type": "string", "required": True}},
        "steps": steps,
    }


@unittest.skipUnless(REAL_SPECIFY is not None, "real specify executable is unavailable")
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


if __name__ == "__main__":
    unittest.main()
