import sys
import tempfile
import time
import unittest
from pathlib import Path

from workflow_cockpit.engine.pty_session import PtySession
from workflow_cockpit.engine.supervisor import EngineSupervisor


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class PtyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify" / "workflows" / "runs").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_output_is_normalized_through_pty(self):
        supervisor = EngineSupervisor(Path(sys.executable), self.root)
        script = (
            "import sys;"
            "sys.stdout.write('\\x1b[31mred\\x1b[0m\\r\\nsecond\\n');"
            "sys.stdout.flush()"
        )
        supervisor.start("run-pty", [sys.executable, "-c", script])
        self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
        self.assertIn("red", supervisor.output_lines)
        self.assertIn("second", supervisor.output_lines)

    def test_abort_reaps_child_and_descendants(self):
        supervisor = EngineSupervisor(
            Path(sys.executable), self.root, grace_interrupt=2.0, grace_term=2.0
        )
        script = "import time; print('up'); time.sleep(30)"
        supervisor.start("run-abort", [sys.executable, "-c", script])
        self.assertTrue(wait_for(lambda: supervisor.verify_live()))
        supervisor.abort()
        self.assertTrue(wait_for(lambda: supervisor.condition().reaped, timeout=6))
        self.assertFalse(supervisor.verify_live())

    def test_no_user_writepath_exists(self):
        self.assertFalse(hasattr(PtySession, "write"))
        self.assertFalse(hasattr(EngineSupervisor, "write_input"))


if __name__ == "__main__":
    unittest.main()
