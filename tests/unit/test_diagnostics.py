import contextlib
import io
import logging
import tempfile
import unittest
from pathlib import Path

from workflow_cockpit import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "debug.log"

    def tearDown(self):
        diagnostics.reset()
        self.tmp.cleanup()

    def _env(self) -> dict[str, str]:
        return {diagnostics.ENV_VAR: str(self.path)}

    def test_disabled_without_environment_variable(self):
        self.assertIsNone(diagnostics.configure({}))
        self.assertFalse(diagnostics.enabled())

    def test_blank_path_is_disabled(self):
        self.assertIsNone(diagnostics.configure({diagnostics.ENV_VAR: "   "}))
        self.assertFalse(diagnostics.enabled())

    def test_unwritable_path_disables_quietly(self):
        bad = Path(self.tmp.name) / "missing" / "debug.log"
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertIsNone(diagnostics.configure({diagnostics.ENV_VAR: str(bad)}))
        self.assertFalse(diagnostics.enabled())
        self.assertEqual(err.getvalue(), "")

    def test_writes_to_file_and_never_to_stderr(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(diagnostics.configure(self._env()), str(self.path))
            logging.getLogger("workflow_cockpit.test").info("marker line")
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("diagnostics enabled", text)
        self.assertIn("marker line", text)
        self.assertEqual(err.getvalue(), "")

    def test_configure_is_idempotent(self):
        diagnostics.configure(self._env())
        diagnostics.configure(self._env())
        logging.getLogger("workflow_cockpit.test").info("once")
        text = self.path.read_text(encoding="utf-8")
        self.assertEqual(text.count("diagnostics enabled"), 1)
        self.assertEqual(text.count("once"), 1)

    def test_reset_restores_process_hooks(self):
        import sys
        import threading

        before = (sys.excepthook, threading.excepthook)
        diagnostics.configure(self._env())
        self.assertNotEqual(sys.excepthook, before[0])
        diagnostics.reset()
        self.assertEqual((sys.excepthook, threading.excepthook), before)
        self.assertFalse(diagnostics.enabled())

    def test_timed_logs_only_blocks_at_or_above_threshold(self):
        diagnostics.configure(self._env())
        with diagnostics.timed("quick work", warn_ms=10_000):
            pass
        with diagnostics.timed("slow work", warn_ms=0):
            pass
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn("quick work", text)
        self.assertIn("slow slow work", text)

    def test_input_monitor_reports_stalls_and_counts_input(self):
        diagnostics.configure(self._env())
        now = [0.0]
        monitor = diagnostics.InputMonitor(clock=lambda: now[0])

        now[0] = 0.25
        monitor.note_input("Key")
        monitor.note_input("Key")
        monitor.note_input("MouseDown")
        monitor.tick()
        self.assertNotIn("ui stall", self.path.read_text(encoding="utf-8"))

        now[0] = 3.0  # the loop did not tick for 2.75 s
        monitor.tick()
        self.assertIn("ui stall: event loop did not run for 2.75 s", self.path.read_text(encoding="utf-8"))

        now[0] = diagnostics.SUMMARY_SECONDS + 3.0
        monitor.tick()
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("input in last 33 s: Key=2, MouseDown=1", text)

        now[0] += diagnostics.SUMMARY_SECONDS
        monitor.tick()
        self.assertIn("input in last 30 s: none", self.path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
