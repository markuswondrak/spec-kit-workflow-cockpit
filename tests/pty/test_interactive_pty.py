import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

from packaging.version import Version

from tests.support import requires_pty
from workflow_cockpit.engine.pty_session import WriteOutcome
from workflow_cockpit.engine.supervisor import EngineSupervisor, StdinPolicy
from workflow_cockpit.services.graph import WorkflowDefinitionParser
from workflow_cockpit.services.run_state import RunStateData
from workflow_cockpit.services.snapshot import GateState
from workflow_cockpit.session.gate_decision import GateDecisionCoordinator, GateDecisionError
from workflow_cockpit.session.resume import ResumeCoordinator, ResumeError


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


PROMPT_SCRIPT = (
    "import sys;"
    "print('prompt ready');sys.stdout.flush();"
    "line=sys.stdin.readline();"
    "print('received:' + line.strip());sys.stdout.flush()"
)


@requires_pty
class InteractivePtyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify" / "workflows" / "runs").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_mapped_write_reaches_live_prompt(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        supervisor.start("run-pty", [sys.executable, "-c", PROMPT_SCRIPT], stdin=StdinPolicy.PTY)
        self.assertTrue(wait_for(lambda: "prompt ready" in supervisor.output_lines))
        self.assertIs(supervisor.write_input(b"approve\n"), WriteOutcome.WRITTEN)
        self.assertTrue(wait_for(lambda: any("received:approve" in line for line in supervisor.output_lines)))
        supervisor.close()

    def test_ordinary_keys_are_not_a_write_path(self):
        # The only write seam is ``write_input``; there is no per-key forwarder.
        self.assertFalse(hasattr(EngineSupervisor, "send_keys"))
        self.assertFalse(hasattr(EngineSupervisor, "write_keys"))
        self.assertFalse(hasattr(EngineSupervisor, "feed"))

    def test_write_refused_after_reap(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        supervisor.start("run-pty", [sys.executable, "-c", "print('done')"], stdin=StdinPolicy.PTY)
        self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
        self.assertIs(supervisor.write_input(b"approve\n"), WriteOutcome.NOT_WRITTEN)


@requires_pty
class AdoptedInteractiveGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify" / "workflows" / "runs" / "existing").mkdir(parents=True)
        self.result = self.root / "adopted-input.txt"
        self.script = self.root / "fake-resume"
        self.script.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "print('gate prompt', flush=True)\n"
            f"open({str(self.result)!r}, 'w').write(sys.stdin.readline().strip())\n",
            encoding="utf-8",
        )
        self.script.chmod(self.script.stat().st_mode | stat.S_IEXEC)

    def tearDown(self):
        self.tmp.cleanup()

    def test_adopted_interactive_gate_spawns_once_and_writes_once(self):
        supervisor = EngineSupervisor(self.script, self.root)
        supervisor.bind_existing("existing")
        graph = WorkflowDefinitionParser().parse(
            (
                {"id": "prepare", "command": "demo.prepare"},
                {
                    "id": "review",
                    "type": "gate",
                    "message": "Review it",
                    "options": ["approve", "reject"],
                    "on_reject": "skip",
                },
                {"id": "finish", "command": "demo.finish"},
            )
        )
        state = RunStateData(status="paused", current_step_id="review")
        coordinator = GateDecisionCoordinator(
            graph=graph,
            supervisor=supervisor,
            executable=self.script,
            version=Version("1.0.6"),
            clock=time.monotonic,
            adopted=True,
        )
        condition = supervisor.condition()
        gate = coordinator.project(
            state=state, run_id="existing", condition=condition
        )
        self.assertEqual(gate.state, GateState.READY)
        coordinator.submit(
            choice="approve",
            token=gate.token,
            state=state,
            run_id="existing",
            condition=condition,
        )
        self.assertTrue(
            wait_for(lambda: self.result.exists() and self.result.read_text() == "1")
        )
        # The reserved attempt is consumed: no second resume or write.
        with self.assertRaises(GateDecisionError):
            coordinator.submit(
                choice="reject",
                token=gate.token,
                state=state,
                run_id="existing",
                condition=supervisor.condition(),
            )
        supervisor.close()


@requires_pty
class AdoptedInteractiveResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify" / "workflows" / "runs" / "existing").mkdir(parents=True)
        self.calls = self.root / "resume-calls.txt"
        self.script = self.root / "fake-resume"
        self.script.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            f"open({str(self.calls)!r}, 'a').write('resume\\n')\n"
            "sys.stdout.write('resumed\\n')\n"
            "sys.stdout.flush()\n",
            encoding="utf-8",
        )
        self.script.chmod(self.script.stat().st_mode | stat.S_IEXEC)

    def tearDown(self):
        self.tmp.cleanup()

    def test_adopted_failed_resume_spawns_once_over_pty(self):
        supervisor = EngineSupervisor(self.script, self.root)
        supervisor.bind_existing("existing")
        graph = WorkflowDefinitionParser().parse(
            (
                {"id": "prepare", "command": "demo.prepare"},
                {
                    "id": "review",
                    "type": "gate",
                    "message": "Review it",
                    "options": ["approve"],
                    "on_reject": "skip",
                },
                {"id": "finish", "command": "demo.finish"},
            )
        )
        coordinator = ResumeCoordinator(
            graph=graph,
            supervisor=supervisor,
            executable=self.script,
            adopted=True,
            clock=time.monotonic,
            stdin=StdinPolicy.PTY,
        )
        state = RunStateData(status="failed", current_step_id="review")
        decision = coordinator.project(
            state=state, run_id="existing", condition=supervisor.condition()
        )
        self.assertTrue(decision.available)
        coordinator.submit(
            token=decision.token,
            state=state,
            run_id="existing",
            condition=supervisor.condition(),
        )
        self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
        self.assertEqual(self.calls.read_text().count("resume"), 1)
        # Write-once: the same confirmation cannot spawn a second resume.
        with self.assertRaises(ResumeError):
            coordinator.submit(
                token=decision.token,
                state=state,
                run_id="existing",
                condition=supervisor.condition(),
            )
        self.assertEqual(self.calls.read_text().count("resume"), 1)
        supervisor.close()


if __name__ == "__main__":
    unittest.main()
