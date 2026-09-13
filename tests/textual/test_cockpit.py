import unittest

from textual.app import App

from tests.support import FakeSession, StyledApp
from workflow_cockpit.ui.screens.cockpit import CockpitScreen


class CockpitScreenTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = App()
        self.app.CSS_PATH = "workflow_cockpit/ui/styles.tcss"

    async def test_running_state_and_output_render(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            self.assertIn("RUNNING", str(screen.query_one("#run-status").render()))
            log = screen.query_one("#engine")
            self.assertGreater(len(log.lines), 0)

    async def test_abort_requires_confirmation(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            self.assertFalse(session.aborted)
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(session.aborted)
            self.assertEqual(session.status, "aborted")

    async def test_outcome_acknowledged_with_enter(self):
        session = FakeSession(status="success")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            self.assertIn("RUN COMPLETE", str(screen.query_one("#view-label").render()))
            await pilot.press("enter")
            await pilot.pause()
            self.assertFalse(self.app.is_running)

    async def test_paused_surface_is_read_only_with_abort(self):
        session = FakeSession(status="paused")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            self.assertIn("PAUSED", str(screen.query_one("#view-label").render()))
            commands = screen.query_one("#commands").render()
            self.assertIn("abort", str(commands).lower())

    async def test_help_overlay(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            from workflow_cockpit.ui.screens.help import HelpScreen

            self.assertIsInstance(self.app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, CockpitScreen)

    async def test_header_does_not_consume_half_the_screen(self):
        app = StyledApp()
        session = FakeSession(status="failed")
        async with app.run_test(size=(120, 52)) as pilot:
            app.push_screen(CockpitScreen(session))
            await pilot.pause()
            header = app.screen.query_one("#header")
            workspace = app.screen.query_one("#workspace")
            self.assertEqual(header.region.height, 4)
            self.assertEqual(workspace.region.y, header.region.height)

    async def test_resize_guard_blocks_and_recovers(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(80, 30)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            self.assertTrue(screen.query_one("#resize-guard").display)
            self.assertFalse(screen.query_one("#shell").display)
            await pilot.resize_terminal(120, 40)
            await pilot.pause()
            self.assertFalse(screen.query_one("#resize-guard").display)
            self.assertTrue(screen.query_one("#shell").display)


if __name__ == "__main__":
    unittest.main()
