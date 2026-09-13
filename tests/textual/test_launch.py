import unittest

from textual.app import App
from textual.widgets import Input, OptionList

from tests.support import FakeSession
from workflow_cockpit.ui.screens.cockpit import CockpitScreen
from workflow_cockpit.ui.screens.confirm import ConfirmScreen
from workflow_cockpit.ui.screens.launch import LaunchScreen


class LaunchScreenTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = App()
        self.app.CSS_PATH = "workflow_cockpit/ui/styles.tcss"

    async def test_lists_and_describes_first_workflow(self):
        session = FakeSession()
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            workflow = screen.query_one("#workflows", OptionList).get_option_at_index(0)
            self.assertIn("Demo Workflow", str(workflow.prompt))
            self.assertIn("A demo workflow", str(workflow.prompt))
            self.assertIn("Enter to configure", str(workflow.prompt))
            self.assertTrue(screen.query_one("#launch-logo").display)
            self.assertFalse(screen.query_one("#launch-detail").display)

    async def test_enter_opens_configuration_in_place(self):
        session = FakeSession()
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertFalse(screen.query_one("#workflow-picker").display)
            self.assertTrue(screen.query_one("#launch-detail").display)
            self.assertIn("Demo Workflow", str(screen.query_one("#detail-name").render()))

    async def test_no_workflows_has_prominent_empty_state(self):
        session = FakeSession()
        session.list_workflows = lambda: ()
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            empty = screen.query_one("#workflow-empty")
            self.assertTrue(empty.display)
            self.assertIn("NO WORKFLOWS AVAILABLE", str(empty.render()))
            self.assertIn("specify workflow add <id>", str(empty.render()))
            self.assertFalse(screen.query_one("#workflow-picker").display)
            self.assertFalse(screen.query_one("#launch-detail").display)

    async def test_required_validation_blocks_start(self):
        session = FakeSession()
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            await screen.configure()
            screen.query_one("#input-spec", Input).value = "   "
            screen.start()
            await pilot.pause()
            self.assertFalse(session.started)
            self.assertIn("Required", str(screen.query_one("#validation").render()))

    async def test_valid_input_starts_run(self):
        session = FakeSession()
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            await screen.configure()
            screen.query_one("#input-spec", Input).value = "search"
            screen.start()
            await pilot.pause()
            self.assertTrue(session.started)
            self.assertEqual(session.started_values.get("spec"), "search")
            self.assertIsInstance(self.app.screen, CockpitScreen)

    async def test_dirty_worktree_requires_one_confirmation(self):
        session = FakeSession(dirty=True)
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            await screen.configure()
            screen.query_one("#input-spec", Input).value = "search"
            screen.start()
            await pilot.pause()
            self.assertIsInstance(self.app.screen, ConfirmScreen)
            self.assertFalse(session.started)
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(session.started)

    async def test_resize_guard(self):
        session = FakeSession()
        async with self.app.run_test(size=(80, 30)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            self.assertTrue(screen.query_one("#resize-guard").display)
            await pilot.resize_terminal(120, 40)
            await pilot.pause()
            self.assertFalse(screen.query_one("#resize-guard").display)


if __name__ == "__main__":
    unittest.main()
