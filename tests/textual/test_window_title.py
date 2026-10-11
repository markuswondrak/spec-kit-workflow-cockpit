"""The app sets a friendly OSC 0 terminal title instead of the launcher path."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from textual.drivers.headless_driver import HeadlessDriver

from workflow_cockpit.ui.app import CockpitApp, _window_title_sequence


@dataclass
class _FakeReport:
    project: object
    ok: bool = False
    checks: tuple = ()
    compatibility: object = None


class _FakePreflight:
    def __init__(self, root: Path) -> None:
        self._root = root

    def run(self) -> _FakeReport:
        return _FakeReport(project=type("P", (), {"root": self._root})())


class WindowTitleSequenceTests(unittest.TestCase):
    def test_sequence_is_osc0_wrapped_in_bel(self):
        self.assertEqual(_window_title_sequence("Workflow Cockpit"), "\x1b]0;Workflow Cockpit\x07")

    def test_clear_sequence_has_empty_title(self):
        self.assertEqual(_window_title_sequence(""), "\x1b]0;\x07")


class WindowTitleLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_mount_emits_title_and_exit_clears_it(self):
        writes: list[str] = []

        def capture(self, data: str) -> None:
            writes.append(data)

        with patch.object(HeadlessDriver, "write", capture):
            app = CockpitApp(
                preflight=_FakePreflight(Path("/tmp/demo")),
                session_factory=lambda result: None,
            )
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                self.assertIn("\x1b]0;Workflow Cockpit\x07", writes)

        self.assertEqual(writes[-1], "\x1b]0;\x07")
