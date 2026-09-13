"""Interaction and layout checks for the design prototype, not the engine."""

import unittest

from textual.widgets import Input, Static

from app import CockpitApp, CockpitScreen
from components import ConfirmScreen, HelpScreen
from launch import LaunchScreen
from review import ReviewPane


class PrototypeTests(unittest.IsolatedAsyncioTestCase):
    async def test_launch_logo_layout_and_configuration(self):
        for size in ((144, 46), (120, 40), (88, 36)):
            with self.subTest(size=size):
                app = CockpitApp()
                async with app.run_test(size=size) as pilot:
                    await pilot.pause()
                    logo = app.screen.query_one("#launch-logo")
                    self.assertEqual(logo.region.height, 5)
                    self.assertTrue(app.screen.region.contains_region(logo.region))
                    await pilot.press("enter")
                    self.assertFalse(logo.display)
                    await pilot.press("escape")
                    self.assertTrue(logo.display)

    async def test_supported_layouts_and_scenes(self):
        for size in ((144, 46), (120, 40), (112, 36), (100, 40), (88, 36)):
            with self.subTest(size=size):
                app = CockpitApp("gate")
                async with app.run_test(size=size) as pilot:
                    await pilot.pause()
                    screen = app.screen
                    self.assertFalse(screen.query_one("#resize-guard").display)
                    document = screen.query_one("#document-scroll")
                    self.assertGreaterEqual(document.region.height, 5)
                    self.assertGreaterEqual(document.content_size.width, 44)
                    self.assertGreater(screen.query_one("#nodes").region.width, 20)
                    for key in ("#brief-title", "#context", "#choice-approve", "#choice-retry", "#choice-skip", "#abort"):
                        widget = screen.query_one(key)
                        self.assertTrue(screen.region.contains_region(widget.region), key)
                    for key, scene in (("f2", "running"), ("f4", "complete"), ("f5", "failed"), ("f3", "gate")):
                        await pilot.press(key)
                        self.assertEqual(screen.scene, scene)
                        self.assertEqual(screen.query_one("#decision-bar").display, scene == "gate")

    async def test_review_selection_filter_and_views(self):
        app = CockpitApp("gate")
        async with app.run_test(size=(120, 40)) as pilot:
            review = app.screen.query_one(ReviewPane)
            await pilot.press("d")
            self.assertEqual(review.content_mode, "diff")
            await pilot.press("r")
            self.assertEqual(review.content_mode, "rendered")
            await pilot.press("slash")
            field = app.screen.query_one("#file-filter", Input)
            self.assertTrue(field.has_focus)
            await pilot.press("r", "e", "a", "d", "m", "e")
            await pilot.pause()
            self.assertEqual(review.selected, 0)
            self.assertEqual(app.screen.scene, "gate")
            self.assertEqual(app.screen.query_one("#files").option_count, 1)
            field.value = "no-such-path"
            await pilot.pause()
            self.assertFalse(app.screen.query_one("#document").display)
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(app.screen.query_one("#files").option_count, 5)
            self.assertTrue(app.screen.query_one("#document").display)
            await pilot.press("end")
            await pilot.pause()
            self.assertEqual(review.selected, 4)
            self.assertIn("DELETED", str(app.screen.query_one("#document-note", Static).render()))

    async def test_decisions_cancel_confirm_and_abort(self):
        app = CockpitApp("gate")
        async with app.run_test(size=(120, 40)) as pilot:
            cockpit = app.screen
            await pilot.press("1")
            self.assertIsInstance(app.screen, ConfirmScreen)
            await pilot.press("escape")
            self.assertEqual(cockpit.scene, "gate")
            await pilot.press("2", "enter")
            self.assertEqual(cockpit.scene, "running")
            self.assertEqual(cockpit.attempt, 2)
            self.assertIn(("analyze", "running", "00:47"), cockpit.nodes)
            await pilot.press("1")
            self.assertIs(app.screen, cockpit)
            await pilot.press("f3", "1", "enter")
            self.assertIn(("plan", "running", "00:47"), cockpit.nodes)
            await pilot.press("q", "escape")
            self.assertEqual(cockpit.scene, "running")
            await pilot.press("x", "enter")
            self.assertEqual(cockpit.scene, "aborted")

    async def test_selection_does_not_change_run(self):
        app = CockpitApp("gate")
        async with app.run_test(size=(120, 40)) as pilot:
            app.screen.query_one("#nodes").focus()
            await pilot.press("home", "enter")
            self.assertEqual(app.screen.selected_node, "prepare")
            self.assertEqual(app.screen.scene, "gate")
            self.assertEqual(app.screen.mode, "state")
            await pilot.press("g", "l")
            self.assertTrue(app.screen.expanded)
            await pilot.press("e")
            self.assertFalse(app.screen.expanded)
            await pilot.press("question_mark")
            self.assertIsInstance(app.screen, HelpScreen)
            await pilot.press("escape")
            self.assertIsInstance(app.screen, CockpitScreen)

    async def test_launch_workflow_selection_and_validation(self):
        app = CockpitApp()
        async with app.run_test(size=(100, 40)) as pilot:
            self.assertIsInstance(app.screen, LaunchScreen)
            await pilot.press("j", "enter")
            self.assertEqual(app.screen.selected, 1)
            self.assertTrue(app.screen.configuring)
            field = app.screen.query_one("#description", Input)
            self.assertEqual(field.value, "v2.4.0")
            field.value = "  "
            app.screen.start()
            self.assertIsInstance(app.screen, LaunchScreen)
            self.assertIn("Enter a value", str(app.screen.query_one("#validation", Static).render()))
            field.value = "v3.0"
            app.screen.start()
            await pilot.pause()
            self.assertIsInstance(app.screen, CockpitScreen)
            self.assertEqual(app.screen.workflow["name"], "release-check")

    async def test_no_gate_workflow_and_resize_guard(self):
        app = CockpitApp()
        async with app.run_test(size=(88, 36)) as pilot:
            await pilot.press("j", "j", "enter")
            app.screen.start()
            await pilot.pause()
            self.assertEqual(app.screen.workflow["name"], "dependency-refresh")
            await pilot.press("f3")
            self.assertEqual(app.screen.scene, "running")
            await pilot.resize_terminal(80, 24)
            self.assertTrue(app.screen.query_one("#resize-guard").display)
            await pilot.press("f4", "1")
            self.assertEqual(app.screen.scene, "running")
            await pilot.resize_terminal(120, 40)
            self.assertFalse(app.screen.query_one("#resize-guard").display)


if __name__ == "__main__":
    unittest.main()
