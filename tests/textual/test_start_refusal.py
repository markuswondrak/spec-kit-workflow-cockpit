"""US4: the TUI refuses Start over a non-terminal current run."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from textual.app import App
from textual.widgets import Input

from tests.fakes import FakeSession
from tests.fixtures import run_trees as rt
from workflow_cockpit.ui.screens.cockpit import CockpitScreen
from workflow_cockpit.ui.screens.launch import LaunchScreen


class StartRefusalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = App()
        self.app.CSS_PATH = "workflow_cockpit/ui/styles.tcss"

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def session(self) -> FakeSession:
        session = FakeSession()
        session.project_root = self.root
        return session

    async def press_start(self, session: FakeSession):
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            await screen.configure()
            screen.query_one("#input-spec", Input).value = "search"
            screen.start()
            await pilot.pause()
            # A successful Start switches screens, taking #validation with it.
            if self.app.screen is screen:
                return str(screen.query_one("#validation").render()), False
            return "", isinstance(self.app.screen, CockpitScreen)

    async def test_running_current_run_refuses_start_with_guidance(self):
        rt.live_flat(self.root, status="running")
        session = self.session()
        message, switched = await self.press_start(session)
        self.assertFalse(session.started)
        self.assertFalse(switched)
        self.assertIn(rt.RUN_ID, message)
        self.assertIn("running", message)
        self.assertIn("Adopt", message)
        self.assertIn("abort", message.lower())

    async def test_paused_current_run_refuses_start_with_guidance(self):
        rt.paused_gate(self.root)
        session = self.session()
        message, switched = await self.press_start(session)
        self.assertFalse(session.started)
        self.assertFalse(switched)
        self.assertIn(rt.RUN_ID, message)
        self.assertIn("paused", message)

    async def test_terminal_current_run_starts_exactly_as_today(self):
        rt.live_flat(self.root, status="completed")
        session = self.session()
        message, switched = await self.press_start(session)
        self.assertTrue(session.started)
        self.assertEqual(message, "")
        self.assertTrue(switched)

    async def test_no_current_run_starts_exactly_as_today(self):
        rt.no_run(self.root)
        session = self.session()
        _message, switched = await self.press_start(session)
        self.assertTrue(session.started)
        self.assertTrue(switched)


if __name__ == "__main__":
    unittest.main()
