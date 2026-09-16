import unittest
from pathlib import Path

from tests.support import FakeSession, StyledApp
from workflow_cockpit.bootstrap.discovery import ProjectInfo
from workflow_cockpit.bootstrap.preflight import CheckResult, PreflightReport
from workflow_cockpit.services.snapshot import GateSnapshot, GateState
from workflow_cockpit.ui.screens.cockpit import CockpitScreen
from workflow_cockpit.ui.screens.help import HelpScreen
from workflow_cockpit.ui.screens.launch import LaunchScreen
from workflow_cockpit.ui.screens.preflight import PreflightScreen


def paused_gate(**kwargs) -> GateSnapshot:
    defaults = {
        "runtime_step_id": "review",
        "step_id": "review",
        "message": "Review it",
        "options": ("approve", "reject"),
        "state": GateState.BLOCKED,
        "reason": "No live engine process is waiting at this gate; only Abort is available.",
    }
    defaults.update(kwargs)
    return GateSnapshot(**defaults)


class FakePreflight:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.runs = 0

    def run(self) -> PreflightReport:
        self.runs += 1
        project = ProjectInfo(root=Path("/tmp/demo"), specify_dir=Path("/tmp/demo/.specify"))
        return PreflightReport(
            project=project,
            checks=(
                CheckResult(
                    "platform",
                    "Platform",
                    self.ok,
                    "Linux" if self.ok else "unsupported",
                    repair="" if self.ok else "Run on Linux, macOS, or WSL.",
                ),
            ),
            compatibility=None,
        )


class ScreenHelpOverlayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = StyledApp()

    async def test_preflight_help_and_recheck_are_keyboard_reachable(self):
        preflight = FakePreflight(ok=False)
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(PreflightScreen(preflight, lambda result: FakeSession()))
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            before = preflight.runs
            await pilot.press("r")
            await pilot.pause()
            self.assertGreater(preflight.runs, before)

    async def test_launch_help_overlay_from_catalog(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(LaunchScreen(FakeSession()))
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, HelpScreen)
            await pilot.press("question_mark")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, LaunchScreen)

    async def test_launch_keyboard_journey_reaches_start(self):
        session = FakeSession()
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(LaunchScreen(session))
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            for key in "search":
                await pilot.press(key)
            await pilot.pause()
            await pilot.press("tab", "tab", "tab", "enter")
            await pilot.pause()
            self.assertTrue(session.started)
            self.assertIsInstance(self.app.screen, CockpitScreen)

    async def test_confirm_help_overlay(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            self.assertFalse(session.aborted)

    async def test_cockpit_actions_are_keyboard_reachable(self):
        session = FakeSession(status="paused")
        session.gate = paused_gate()
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            for key, expected in (("s", "state"), ("c", "changes"), ("g", "gate")):
                await pilot.press(key)
                await pilot.pause()
                self.assertEqual(self.app.screen._focus_mode, expected, key)
            await pilot.press("l")
            await pilot.pause()
            await pilot.press("end")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsNotNone(self.app.screen._focus_mode)


if __name__ == "__main__":
    unittest.main()
