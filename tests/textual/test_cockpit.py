import asyncio
import unittest

from tests.support import FakeSession, StyledApp
from workflow_cockpit.ui.screens.aborting import AbortingScreen
from workflow_cockpit.ui.screens.cockpit import CockpitScreen
from workflow_cockpit.ui.widgets import TRUNCATION_MARKER, EngineOutput


class CockpitScreenTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = StyledApp()

    async def test_running_state_and_output_render(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            self.assertIn("RUNNING", str(screen.query_one("#run-status").render()))
            log = screen.query_one("#engine")
            self.assertGreater(len(log.lines), 0)
            self.assertTrue(screen.query_one("#overview").has_class("compact-summary"))

    async def test_abort_requires_confirmation_then_closes(self):
        session = FakeSession(status="running")
        session.abort_delay = 0.2
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            self.assertFalse(session.aborted)
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, AbortingScreen)
            for _ in range(200):
                if not self.app.is_running:
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(session.aborted)
            self.assertFalse(self.app.is_running)

    async def test_activity_indicator_tracks_live_state(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            activity = self.app.screen.query_one("#activity")
            self.assertTrue(activity.display)
            session.status = "paused"
            self.app.screen._refresh()
            await pilot.pause()
            self.assertFalse(activity.display)
            session.status = "success"
            self.app.screen._refresh()
            await pilot.pause()
            self.assertFalse(activity.display)

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

    async def test_runway_selection_and_focus_mode_survive_refresh(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            runway = screen.query_one("#runway-graph")
            runway.focus()
            await pilot.press("j")
            await pilot.pause()
            self.assertEqual(screen._selected_node_id, "review")
            screen._refresh()
            self.assertEqual(screen._selected_node_id, "review")
            session.status = "paused"
            screen._refresh()
            self.assertIn("GATE", str(screen.query_one("#view-label").render()))
            self.assertTrue(screen.query_one("#overview").display)
            session.status = "success"
            screen._refresh()
            self.assertIn("RUN COMPLETE", str(screen.query_one("#view-label").render()))

    async def test_output_keeps_appending_after_tail_saturates(self):
        session = FakeSession(status="running")
        session.output_lines = ["a", "b"]
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            log = self.app.screen.query_one("#engine")
            self.assertEqual(len(log.lines), 2)
            # The bounded tail stays the same length while a new line emits.
            session.output_lines = ["b", "c"]
            session.output_emitted = 3
            self.app.screen._refresh()
            await pilot.pause()
            self.assertEqual(len(log.lines), 3)
            self.assertIn("c", str(log.lines[-1]))

    async def test_output_shows_truncation_marker_after_dropped_lines(self):
        session = FakeSession(status="running")
        session.output_lines = ["kept"]
        session.output_emitted = 5
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            rendered = "\n".join(str(line) for line in self.app.screen.query_one("#engine").lines)
            self.assertIn(TRUNCATION_MARKER, rendered)
            self.assertIn("kept", rendered)

    async def test_output_scroll_survives_refresh_when_not_at_tail(self):
        session = FakeSession(status="running")
        session.output_lines = [f"line {index}" for index in range(200)]
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            log = self.app.screen.query_one(EngineOutput).log()
            log.scroll_home(animate=False)
            await pilot.pause()
            before = log.scroll_y
            session.output_lines = [*session.output_lines, "appended"]
            self.app.screen._refresh()
            await pilot.pause()
            self.assertEqual(log.scroll_y, before)

    async def test_runway_uses_compact_strip_at_narrow_supported_width(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(100, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            runway = self.app.screen.query_one("#runway")
            self.assertEqual(runway.region.height, 4)
            self.assertGreater(self.app.screen.query_one("#runway-graph").option_count, 0)

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
