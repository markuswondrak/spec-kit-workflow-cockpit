import sys
import tempfile
import time
import unittest
from pathlib import Path

from workflow_cockpit.engine.supervisor import (
    EngineSupervisor,
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


if __name__ == "__main__":
    unittest.main()
