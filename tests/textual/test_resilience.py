import asyncio
import time
import unittest

from tests.support import FakeSession, StyledApp
from workflow_cockpit.session.signals import SignalHandler
from workflow_cockpit.ui.screens.cockpit import CockpitScreen
from workflow_cockpit.ui.widgets import ErrorStrip


class ResilienceScreenTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = StyledApp()

    async def test_stale_marker_appears_and_clears(self):
        session = FakeSession(status="running")
        session.stale = True
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            self.assertIn("STALE", str(self.app.screen.query_one("#run-status").render()))
            session.stale = False
            self.app.screen._refresh()
            await pilot.pause()
            self.assertNotIn("STALE", str(self.app.screen.query_one("#run-status").render()))

    async def test_error_strip_shows_state_and_next_action_then_clears(self):
        session = FakeSession(status="paused")
        session.diagnostic = "state.json could not be read; showing the last good value."
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            strip = self.app.screen.query_one(ErrorStrip)
            self.assertTrue(strip.display)
            rendered = str(strip.render())
            self.assertIn("state.json", rendered)
            self.assertIn("state: paused", rendered)
            self.assertIn("next:", rendered)
            session.diagnostic = ""
            self.app.screen._refresh()
            await pilot.pause()
            self.assertFalse(strip.display)

    async def test_context_error_routes_to_strip(self):
        session = FakeSession(status="running")
        session.context_path = ""
        session.context_error = "Context index unavailable: disk full"
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            strip = self.app.screen.query_one(ErrorStrip)
            self.assertTrue(strip.display)
            self.assertIn("disk full", str(strip.render()))

    async def test_editor_failure_routes_to_actionable_strip(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = CockpitScreen(session, editor_env=lambda: "")
            self.app.push_screen(screen)
            await pilot.pause()
            screen.action_open_editor()
            await pilot.pause()
            strip = screen.query_one(ErrorStrip)
            self.assertTrue(strip.display)
            self.assertIn("$EDITOR", str(strip.render()))

    async def test_review_refresh_error_routes_to_strip(self):
        session = FakeSession(status="paused")
        from workflow_cockpit.services.review import ReviewSnapshot

        session.review = ReviewSnapshot(status="error", error="Feature directory unavailable.")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            strip = self.app.screen.query_one(ErrorStrip)
            self.assertTrue(strip.display)
            self.assertIn("Feature directory unavailable.", str(strip.render()))

    async def test_slow_git_probe_does_not_block_interaction(self):
        session = FakeSession(status="running")

        def slow_refresh():
            time.sleep(0.5)
            return session.branch

        session.refresh_branch = slow_refresh
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            self.app.screen._request_branch()
            await pilot.press("s")
            await pilot.pause(0.05)
            self.assertEqual(self.app.screen._focus_mode, "state")

    async def test_simulated_signal_aborts_active_run_without_confirmation(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            handler = SignalHandler(lambda: session, self.app).register()
            try:
                handler._on_signal()
                for _ in range(300):
                    if not self.app.is_running:
                        break
                    await asyncio.sleep(0.01)
            finally:
                handler.close()
            self.assertTrue(session.aborted)
            self.assertFalse(self.app.is_running)

    async def test_poll_worker_publishes_a_snapshot(self):
        session = FakeSession(status="running")
        session.snapshot_calls = 0
        original = session.snapshot

        def counting():
            session.snapshot_calls += 1
            return original()

        session.snapshot = counting
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            before = session.snapshot_calls
            self.app.screen._loop._last_tick = None
            self.app.screen._request_poll()
            for _ in range(50):
                if session.snapshot_calls > before:
                    break
                await asyncio.sleep(0.02)
            self.assertGreater(session.snapshot_calls, before)


if __name__ == "__main__":
    unittest.main()
