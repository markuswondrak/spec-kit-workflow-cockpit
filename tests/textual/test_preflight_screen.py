import unittest
from pathlib import Path

from textual.app import App

from tests.support import FakeSession
from workflow_cockpit.bootstrap.discovery import ProjectInfo
from workflow_cockpit.bootstrap.preflight import CheckResult, PreflightReport
from workflow_cockpit.ui.screens.launch import LaunchScreen
from workflow_cockpit.ui.screens.preflight import PreflightScreen


class FakePreflight:
    def __init__(self, ok: bool) -> None:
        self.ok = ok

    def run(self) -> PreflightReport:
        project = ProjectInfo(root=Path("/tmp/demo"), specify_dir=Path("/tmp/demo/.specify"))
        checks = (
            CheckResult("platform", "Platform", True, "Linux"),
            CheckResult(
                "specify",
                "Compatible specify executable",
                self.ok,
                "specify 0.16.1 is outside range" if not self.ok else "specify 1.0.0",
                repair="Install a compatible specify." if not self.ok else "",
            ),
        )
        return PreflightReport(project=project, checks=checks, compatibility=None)


class PreflightScreenTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = App()
        self.app.CSS_PATH = "workflow_cockpit/ui/styles.tcss"

    async def test_failures_are_actionable_and_stay(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = PreflightScreen(FakePreflight(ok=False), lambda result: FakeSession())
            self.app.push_screen(screen)
            await pilot.pause()
            self.assertIn("PREREQUISITES MISSING", str(screen.query_one("#run-status").render()))
            listing = str(screen.query_one("#preflight-list").render())
            self.assertIn("repair", listing)

    async def test_success_advances_to_launch(self):
        session = FakeSession()
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = PreflightScreen(FakePreflight(ok=True), lambda result: session)
            self.app.push_screen(screen)
            await pilot.pause()
            self.assertIsInstance(self.app.screen, LaunchScreen)


if __name__ == "__main__":
    unittest.main()
