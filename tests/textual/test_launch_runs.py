import unittest

from textual.app import App

from tests.support import FakeSession
from workflow_cockpit.services.run_catalog import RunDescriptor
from workflow_cockpit.services.run_claim import ClaimState
from workflow_cockpit.ui.screens.confirm import ConfirmScreen
from workflow_cockpit.ui.screens.launch import LaunchScreen
from workflow_cockpit.ui.screens.launch_runs import ExistingRunsList


def descriptor(run_id, status="paused", **overrides):
    values = {
        "run_id": run_id,
        "workflow_id": "demo",
        "workflow_name": "Demo Workflow",
        "status": status,
        "current_step_id": "review",
        "updated_at": "2026-09-18T00:00:00+00:00",
        "usable": True,
        "launch_copy": True,
        "is_default": False,
    }
    values.update(overrides)
    return RunDescriptor(**values)


class LaunchRunsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = App()
        self.app.CSS_PATH = "workflow_cockpit/ui/styles.tcss"

    async def test_runs_listed_beneath_workflow_picker(self):
        session = FakeSession()
        session.existing_runs = (descriptor("cockpit-a"), descriptor("cockpit-b", "completed"))
        async with self.app.run_test(size=(120, 45)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            listing = screen.query_one("#existing-runs", ExistingRunsList)
            self.assertEqual([d.run_id for d in listing.descriptors], ["cockpit-a", "cockpit-b"])
            # The run section is mounted directly after the workflow picker.
            children = [child.id for child in screen.query_one("#launch-content").children]
            self.assertLess(
                children.index("workflow-picker"), children.index("existing-runs-section")
            )
            self.assertTrue(screen.query_one("#existing-runs-section").display)

    async def test_empty_runs_keeps_new_run_flow(self):
        session = FakeSession()
        session.existing_runs = ()
        async with self.app.run_test(size=(120, 45)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            listing = screen.query_one("#existing-runs", ExistingRunsList)
            self.assertEqual(listing.descriptors, ())
            self.assertIn("NO EXISTING RUNS", str(listing.get_option_at_index(0).prompt))
            # The workflow picker remains the primary action.
            self.assertTrue(screen.query_one("#workflow-picker").display)

    async def test_malformed_entry_shows_reason(self):
        session = FakeSession()
        session.existing_runs = (
            descriptor("cockpit-broken", "unusable", usable=False, reason="state.json is not valid JSON"),
        )
        async with self.app.run_test(size=(120, 45)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            listing = screen.query_one("#existing-runs", ExistingRunsList)
            prompt = str(listing.get_option_at_index(0).prompt)
            self.assertIn("cockpit-broken", prompt)
            self.assertIn("state.json is not valid JSON", prompt)

    async def test_missing_launch_copy_refuses_selection(self):
        session = FakeSession()
        session.existing_runs = (descriptor("cockpit-no-copy", launch_copy=False),)
        async with self.app.run_test(size=(120, 45)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            listing = screen.query_one("#existing-runs", ExistingRunsList)
            listing.focus()
            listing.highlighted = 0
            await pilot.press("enter")
            await pilot.pause()
            validation = str(screen.query_one("#validation").render())
            self.assertIn("no launch-copy workflow definition", validation)
            self.assertIsNone(session.adopted_run)
            self.assertIsNone(session.inspected_run)

    async def test_adoptable_run_is_not_refused(self):
        session = FakeSession()
        session.existing_runs = (descriptor("cockpit-paused"),)
        async with self.app.run_test(size=(120, 45)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            listing = screen.query_one("#existing-runs", ExistingRunsList)
            self.assertTrue(listing.descriptors[0].adoptable)

    async def test_live_foreign_run_inspects_without_adoption(self):
        from workflow_cockpit.ui.screens.cockpit import CockpitScreen

        session = FakeSession()
        session.existing_runs = (
            descriptor("cockpit-foreign", claim_state=ClaimState.LIVE_FOREIGN),
        )
        async with self.app.run_test(size=(120, 45)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            listing = screen.query_one("#existing-runs", ExistingRunsList)
            self.assertFalse(listing.descriptors[0].adoptable)
            self.assertTrue(listing.descriptors[0].viewable)
            listing.focus()
            listing.highlighted = 0
            await pilot.press("enter")
            await pilot.pause()
            # Inspect confirm sheet is shown. Press enter to confirm inspection.
            await pilot.press("enter")
            await pilot.pause(0.1)
            self.assertEqual(session.inspected_run, "cockpit-foreign")
            self.assertIsNone(session.adopted_run)
            self.assertTrue(session.read_only)
            self.assertIsInstance(self.app.screen, CockpitScreen)

    async def test_selecting_running_run_inspects_and_switches(self):
        from workflow_cockpit.ui.screens.cockpit import CockpitScreen

        session = FakeSession()
        session.existing_runs = (descriptor("cockpit-running", "running"),)
        async with self.app.run_test(size=(120, 45)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            listing = screen.query_one("#existing-runs", ExistingRunsList)
            self.assertFalse(listing.descriptors[0].adoptable)
            self.assertTrue(listing.descriptors[0].viewable)
            listing.focus()
            listing.highlighted = 0
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause(0.1)
            self.assertEqual(session.inspected_run, "cockpit-running")
            self.assertIsNone(session.adopted_run)
            self.assertTrue(session.read_only)
            self.assertIsInstance(self.app.screen, CockpitScreen)

    async def test_selecting_paused_run_adopts_and_switches(self):
        from workflow_cockpit.ui.screens.cockpit import CockpitScreen

        session = FakeSession()
        session.existing_runs = (descriptor("cockpit-paused"),)
        async with self.app.run_test(size=(120, 45)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            listing = screen.query_one("#existing-runs", ExistingRunsList)
            listing.focus()
            listing.highlighted = 0
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause(0.1)
            self.assertEqual(session.adopted_run, "cockpit-paused")
            self.assertIsInstance(self.app.screen, CockpitScreen)

    async def test_delete_run_confirms_and_removes(self):
        session = FakeSession()
        session.existing_runs = (descriptor("cockpit-done", "completed"),)
        async with self.app.run_test(size=(120, 45)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            listing = screen.query_one("#existing-runs", ExistingRunsList)
            listing.focus()
            listing.highlighted = 0
            await pilot.press("d")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, ConfirmScreen)
            self.assertIn(
                "Delete this run?", str(self.app.screen.query_one("#confirm-heading").render())
            )
            await pilot.press("enter")
            await pilot.pause(0.3)
            self.assertEqual(session.deleted_runs, ["cockpit-done"])
            self.assertEqual(listing.descriptors, ())

    async def test_delete_cancel_keeps_run(self):
        session = FakeSession()
        session.existing_runs = (descriptor("cockpit-done", "completed"),)
        async with self.app.run_test(size=(120, 45)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            listing = screen.query_one("#existing-runs", ExistingRunsList)
            listing.focus()
            listing.highlighted = 0
            await pilot.press("d")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause(0.2)
            self.assertEqual(session.deleted_runs, [])
            self.assertEqual(len(listing.descriptors), 1)

    async def test_delete_refusal_shows_reason(self):
        session = FakeSession()
        session.delete_error = "This run is running; its engine may still be writing."
        session.existing_runs = (descriptor("cockpit-live", "running"),)
        async with self.app.run_test(size=(120, 45)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            listing = screen.query_one("#existing-runs", ExistingRunsList)
            listing.focus()
            listing.highlighted = 0
            await pilot.press("d")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause(0.3)
            validation = str(screen.query_one("#validation").render())
            self.assertIn("running", validation)
            self.assertEqual(session.deleted_runs, [])

    async def test_delete_binding_ignored_when_workflows_focused(self):
        session = FakeSession()
        session.existing_runs = (descriptor("cockpit-done", "completed"),)
        async with self.app.run_test(size=(120, 45)) as pilot:
            screen = LaunchScreen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            # Focus starts on the workflow picker.
            await pilot.press("d")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, LaunchScreen)
            self.assertEqual(session.deleted_runs, [])


if __name__ == "__main__":
    unittest.main()
