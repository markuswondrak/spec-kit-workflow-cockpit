import unittest
from types import SimpleNamespace

from textual.app import App
from textual.css.query import NoMatches
from textual.widgets import Button, Input, OptionList

from tests.support import FakeSession
from workflow_cockpit.services.definition import DefinitionError
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

    async def test_unresolvable_workflow_never_silently_no_ops(self):
        session = FakeSession()

        def fail(_workflow_id):
            raise DefinitionError(
                "Workflow definition not found: /p/.specify/workflows/demo/workflow.yml"
            )

        session.select = fail
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            empty = screen.query_one("#workflow-empty")
            self.assertTrue(empty.display)
            self.assertIn("WORKFLOWS UNAVAILABLE", str(empty.render()))
            self.assertIn("Workflow definition not found", str(empty.render()))
            self.assertIn("specify workflow add", str(empty.render()))
            self.assertFalse(screen.query_one("#workflow-picker").display)
            self.assertFalse(screen.query_one("#launch-detail").display)
            await pilot.press("enter")
            await pilot.pause()
            self.assertFalse(screen.query_one("#launch-detail").display)

    async def test_broken_entry_is_disabled_and_labeled(self):
        session = FakeSession()
        good = SimpleNamespace(id="demo", name="Demo Workflow", description="A demo workflow")
        broken = SimpleNamespace(id="broken", name="Broken Workflow", description="Missing files")
        session.list_workflows = lambda: (good, broken)

        def select(workflow_id):
            if workflow_id == "broken":
                raise DefinitionError("Workflow definition not found: broken/workflow.yml")
            return session.definition

        session.select = select
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            listing = screen.query_one("#workflows", OptionList)
            self.assertFalse(listing.get_option_at_index(0).disabled)
            self.assertTrue(listing.get_option_at_index(1).disabled)
            self.assertIn("Unavailable", str(listing.get_option_at_index(1).prompt))
            self.assertIn("1 of 2", str(screen.query_one("#catalog-note").render()))
            await screen.configure()
            self.assertTrue(screen.query_one("#launch-detail").display)

    async def test_unavailable_selection_keeps_start_visible_and_disabled(self):
        session = FakeSession()
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()

            def fail(_workflow_id):
                raise DefinitionError("Workflow definition not found: demo/workflow.yml")

            session.select = fail
            await screen.update_selection()
            await pilot.pause()
            start = screen.query_one("#start", Button)
            self.assertTrue(start.display)
            self.assertTrue(start.disabled)
            self.assertIn(
                "Workflow definition not found", str(screen.query_one("#validation").render())
            )

    async def test_start_visible_after_unavailable_then_startable_selection(self):
        session = FakeSession()
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            definition = session.definition

            def fail(_workflow_id):
                raise DefinitionError("Workflow definition not found: demo/workflow.yml")

            session.select = fail
            await screen.update_selection()
            await pilot.pause()
            session.select = lambda _workflow_id: definition
            await screen.update_selection()
            await pilot.pause()
            start = screen.query_one("#start", Button)
            self.assertTrue(start.display)
            self.assertFalse(start.disabled)
            self.assertEqual("", str(screen.query_one("#validation").render()))

    async def test_incompatible_workflow_disables_start_with_reason(self):
        session = FakeSession()
        session.compatibility_error = "Workflow uses an unsupported feature: loops"
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            start = screen.query_one("#start", Button)
            self.assertTrue(start.display)
            self.assertTrue(start.disabled)
            self.assertIn("unsupported feature", str(screen.query_one("#validation").render()))
            await screen.configure()
            screen.query_one("#input-spec", Input).value = "search"
            screen.start()
            await pilot.pause()
            self.assertFalse(session.started)

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
            self.assertNotIn("review_verdict", session.started_values)
            self.assertIsInstance(self.app.screen, CockpitScreen)

    async def test_verdict_input_not_shown_in_vars_form(self):
        session = FakeSession()
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            await screen.configure()
            with self.assertRaises(NoMatches):
                screen.query_one("#input-review_verdict")

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
