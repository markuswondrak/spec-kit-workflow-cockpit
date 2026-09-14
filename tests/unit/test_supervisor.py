import sys
import tempfile
import time
import unittest
from pathlib import Path

from workflow_cockpit.engine.pty_session import WriteOutcome
from workflow_cockpit.engine.supervisor import (
    EngineSupervisor,
    StdinPolicy,
    SupervisorError,
    build_resume_argv,
)


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify" / "workflows" / "runs").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rejects_existing_run_directory(self):
        (self.root / ".specify" / "workflows" / "runs" / "taken").mkdir()
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        with self.assertRaises(SupervisorError):
            supervisor.start("taken", [sys.executable, "-c", "print('x')"])

    def test_runs_child_and_captures_output(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        supervisor.start("run-1", [sys.executable, "-c", "print('hello from child')"])
        self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
        self.assertIn("hello from child", supervisor.output_lines)
        self.assertEqual(supervisor.condition().exit_code, 0)
        self.assertFalse(supervisor.verify_live())

    def test_second_start_rejected_while_live(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        supervisor.start("run-1", [sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            with self.assertRaises(SupervisorError):
                supervisor.start("run-2", [sys.executable, "-c", "print('x')"])
        finally:
            supervisor.abort()
            supervisor.close()

    def test_abort_without_process_sends_no_signal(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        supervisor.abort()
        self.assertTrue(supervisor.abort_requested)
        self.assertFalse(supervisor.verify_live())

    def test_abort_interrupts_live_group(self):
        supervisor = EngineSupervisor(
            Path(sys.executable), self.root, grace_interrupt=2.0, grace_term=2.0
        )
        supervisor.start("run-1", [sys.executable, "-c", "import time; print('up'); time.sleep(30)"])
        self.assertTrue(wait_for(lambda: supervisor.verify_live()))
        supervisor.abort()
        self.assertTrue(wait_for(lambda: supervisor.condition().reaped, timeout=6))
        self.assertFalse(supervisor.verify_live())


    def test_resume_requires_owned_run(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        with self.assertRaises(SupervisorError):
            supervisor.resume("run-1", [sys.executable, "-c", "print('x')"])

    def test_resume_after_reap_preserves_output_history(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        supervisor.start("run-1", [sys.executable, "-c", "print('first')"])
        self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
        supervisor.resume("run-1", [sys.executable, "-c", "print('second')"])
        self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
        self.assertIn("first", supervisor.output_lines)
        self.assertIn("second", supervisor.output_lines)

    def test_resume_rejected_while_live(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        supervisor.start("run-1", [sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            with self.assertRaises(SupervisorError):
                supervisor.resume("run-1", [sys.executable, "-c", "print('x')"])
        finally:
            supervisor.abort()
            supervisor.close()

    def test_resume_rejected_after_abort(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        supervisor.start("run-1", [sys.executable, "-c", "print('first')"])
        self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
        supervisor.abort()
        with self.assertRaisesRegex(SupervisorError, "aborted"):
            supervisor.resume("run-1", [sys.executable, "-c", "print('second')"])

    def test_resume_rejects_foreign_run_id(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        supervisor.start("run-1", [sys.executable, "-c", "print('first')"])
        self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
        with self.assertRaises(SupervisorError):
            supervisor.resume("other-run", [sys.executable, "-c", "print('x')"])

    def test_build_resume_argv(self):
        argv = build_resume_argv(Path("/usr/bin/specify"), "run-1", "decision", "approve")
        self.assertEqual(
            argv,
            [
                "/usr/bin/specify",
                "workflow",
                "resume",
                "run-1",
                "-i",
                "decision=approve",
                "--json",
            ],
        )

    def test_default_stdin_is_not_a_tty(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        supervisor.start("run-1", [sys.executable, "-c", "import sys; print(sys.stdin.isatty())"])
        self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
        self.assertIn("False", supervisor.output_lines)

    def test_stdin_policy_is_recorded_on_the_condition(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        supervisor.start(
            "run-1",
            [sys.executable, "-c", "import sys; print(sys.stdin.isatty())"],
            stdin=StdinPolicy.PTY,
        )
        self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
        self.assertIn("True", supervisor.output_lines)
        self.assertTrue(supervisor.condition().stdin_pty)

    def test_default_stdin_is_devnull(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        supervisor.start("run-1", [sys.executable, "-c", "print('x')"])
        self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
        self.assertFalse(supervisor.condition().stdin_pty)

    def test_write_input_writes_to_live_process(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        script = (
            "import sys; print('ready'); sys.stdout.flush();"
            "line = sys.stdin.readline(); print('got:' + line.strip())"
        )
        supervisor.start("run-1", [sys.executable, "-c", script], stdin=StdinPolicy.PTY)
        self.assertTrue(wait_for(lambda: "ready" in supervisor.output_lines))
        self.assertIs(supervisor.write_input(b"approve\n"), WriteOutcome.WRITTEN)
        self.assertTrue(wait_for(lambda: any("got:approve" in line for line in supervisor.output_lines)))
        supervisor.close()

    def test_write_input_refuses_when_reaped(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        supervisor.start("run-1", [sys.executable, "-c", "print('done')"], stdin=StdinPolicy.PTY)
        self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
        self.assertIs(supervisor.write_input(b"approve\n"), WriteOutcome.NOT_WRITTEN)

    def test_write_input_refuses_without_process(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        self.assertIs(supervisor.write_input(b"approve\n"), WriteOutcome.NOT_WRITTEN)

    def test_write_input_refuses_without_pty_stdin(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        script = "import time; print('up'); time.sleep(5)"
        supervisor.start("run-1", [sys.executable, "-c", script])
        try:
            self.assertTrue(wait_for(lambda: supervisor.verify_live()))
            self.assertIs(supervisor.write_input(b"approve\n"), WriteOutcome.NOT_WRITTEN)
        finally:
            supervisor.abort()
            supervisor.close()

    def test_write_input_refuses_after_abort_claimed(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        script = "import sys, time; print('ready'); sys.stdout.flush(); time.sleep(5)"
        supervisor.start("run-1", [sys.executable, "-c", script], stdin=StdinPolicy.PTY)
        try:
            self.assertTrue(wait_for(lambda: "ready" in supervisor.output_lines))
            with supervisor._lock:
                supervisor._abort_requested = True
            self.assertIs(supervisor.write_input(b"approve\n"), WriteOutcome.NOT_WRITTEN)
        finally:
            supervisor.abort()
            supervisor.close()


if __name__ == "__main__":
    unittest.main()
