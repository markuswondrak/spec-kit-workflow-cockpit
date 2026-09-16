"""Real catchable-signal delivery to an isolated Cockpit process.

The harness builds the real ``CockpitSession`` and ``CockpitApp`` against a
temp project and a long-running fake engine, then registers the same
``SignalHandler`` the shipped app installs. Each test sends one catchable signal
to the Cockpit PID (never to its engine child) and asserts the owned engine
group is reaped before the Cockpit process exits.
"""

from __future__ import annotations

import fcntl
import json
import os
import pty
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import unittest
from pathlib import Path

import yaml

from tests.support import requires_posix, requires_pty

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parents[1] / "fixtures" / "cockpit_signal_harness.py"
SIGNAL_SPECIFY = Path(__file__).resolve().parents[1] / "fixtures" / "signal_specify.py"

WORKFLOW = {
    "schema_version": "1.0",
    "workflow": {"id": "demo", "name": "Demo", "version": "1.0.0", "description": "demo"},
    "inputs": {"spec": {"type": "string", "required": True}},
    "steps": [{"id": "main", "command": "demo.main"}],
}


def _pid_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _group_alive(pgid: int | None) -> bool:
    if pgid is None:
        return False
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@requires_posix
@requires_pty
class SignalDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        workflows = self.root / ".specify" / "workflows"
        (workflows / "runs").mkdir(parents=True)
        (workflows / "demo").mkdir(parents=True)
        (workflows / "workflow-registry.json").write_text(
            json.dumps({"schema_version": "1.0", "workflows": {"demo": {"name": "Demo", "enabled": True}}}),
            encoding="utf-8",
        )
        (workflows / "demo" / "workflow.yml").write_text(yaml.safe_dump(WORKFLOW), encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=Test", "commit", "--allow-empty", "-qm", "init"],
            cwd=self.root,
            check=True,
        )
        self.fake = self.root / "specify"
        self.fake.write_text(SIGNAL_SPECIFY.read_text(encoding="utf-8"), encoding="utf-8")
        self.fake.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def _wait_for(self, path: Path, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists():
                return True
            time.sleep(0.05)
        return False

    def _deliver(self, sig: signal.Signals) -> None:
        master, slave = pty.openpty()
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        record = self.root / "record.json"
        ready = self.root / "ready"
        env = dict(os.environ, TERM="xterm-256color", PYTHONPATH=str(REPO_ROOT))
        proc = subprocess.Popen(
            [sys.executable, str(HARNESS), str(self.root), str(self.fake), str(record), str(ready)],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            close_fds=True,
        )
        os.close(slave)
        stop = threading.Event()

        def drain() -> None:
            while not stop.is_set():
                try:
                    data = os.read(master, 4096)
                except OSError:
                    break
                if not data:
                    break

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        try:
            self.assertTrue(self._wait_for(record), "harness did not start the run")
            self.assertTrue(self._wait_for(ready), "cockpit app did not become ready")
            payload = json.loads(record.read_text(encoding="utf-8"))
            engine_pid = payload["engine_pid"]
            engine_pgid = payload["engine_pgid"]
            self.assertTrue(_group_alive(engine_pgid), "engine group was not live before the signal")

            os.kill(proc.pid, sig)
            try:
                code = proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.fail(f"cockpit did not exit after {sig.name}")
            self.assertEqual(code, 0, f"cockpit exit code {code} after {sig.name}")

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and _pid_alive(engine_pid):
                time.sleep(0.05)
            self.assertFalse(_pid_alive(engine_pid), "engine child survived signal shutdown")
            self.assertFalse(_group_alive(engine_pgid), "engine group survived signal shutdown")
        finally:
            stop.set()
            try:
                os.close(master)
            except OSError:
                pass
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)

    def test_sigint_reaps_owned_group(self):
        self._deliver(signal.SIGINT)

    def test_sighup_reaps_owned_group(self):
        self._deliver(signal.SIGHUP)

    def test_sigterm_reaps_owned_group(self):
        self._deliver(signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
