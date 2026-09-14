import sys
import tempfile
import time
import unittest
from pathlib import Path

from workflow_cockpit.engine.pty_session import WriteOutcome
from workflow_cockpit.engine.supervisor import EngineSupervisor, StdinPolicy


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


if __name__ == "__main__":
    unittest.main()
