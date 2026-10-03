"""Feature Files labels shorten to the feature directory while ids stay full."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from tests.support import FakeSession, StyledApp
from workflow_cockpit.services.review import FeatureFile, ReviewDocument, ReviewSnapshot
from workflow_cockpit.services.snapshot import GateSnapshot, GateState
from workflow_cockpit.ui.screens.cockpit import CockpitScreen
from workflow_cockpit.ui.widgets import FeatureFileSelect

FEATURE_DIR = "specs/demo"


async def settle(pilot, rounds: int = 5) -> None:
    for _ in range(rounds):
        await pilot.pause()
        await asyncio.sleep(0.02)


def ready_gate() -> GateSnapshot:
    return GateSnapshot(
        runtime_step_id="review",
        step_id="review",
        message="Approve the plan?",
        options=("approve", "reject"),
        on_reject="retry",
        state=GateState.READY,
        token="token-1",
    )


class ReviewDisplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = StyledApp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def _screen(self, session: FakeSession) -> CockpitScreen:
        return CockpitScreen(session, editor_env=lambda: None)

    def _review_session(self) -> FakeSession:
        session = FakeSession(status="paused")
        session.gate = ready_gate()
        session.review = ReviewSnapshot(
            feature_dir=FEATURE_DIR,
            files=(
                FeatureFile(path="specs/demo/spec.md", display="spec.md"),
                FeatureFile(path="specs/demo/nested/plan.md", display="nested/plan.md"),
            ),
        )

        def document(path, *, full=False):
            text = "full body" if full else "preview body"
            return ReviewDocument(path=path, display=path.removeprefix("specs/demo/"), text=text)

        session.review_document = document
        return session

    async def _open_changes(self, pilot, session: FakeSession) -> CockpitScreen:
        screen = self._screen(session)
        self.app.push_screen(screen)
        await settle(pilot)
        await pilot.press("c")
        await settle(pilot)
        return screen

    async def test_medium_collapses_index_into_combobox(self):
        session = self._review_session()
        async with self.app.run_test(size=(130, 40)) as pilot:
            screen = await self._open_changes(pilot, session)
            self.assertTrue(screen.has_class("medium"))
            self.assertFalse(screen.query_one("#review-index").display)
            select = screen.query_one("#review-file-select", FeatureFileSelect)
            self.assertTrue(select.display)
            self.assertEqual(select.value, "specs/demo/spec.md")

    async def test_medium_combobox_selection_loads_document_and_survives_refresh(self):
        session = self._review_session()
        async with self.app.run_test(size=(130, 40)) as pilot:
            screen = await self._open_changes(pilot, session)
            select = screen.query_one("#review-file-select", FeatureFileSelect)
            select.value = "specs/demo/nested/plan.md"
            await settle(pilot)
            self.assertEqual(screen._selected_review_path, "specs/demo/nested/plan.md")
            self.assertIn("plan.md", str(screen.query_one("#review-document").render()))
            screen._refresh()
            await settle(pilot)
            self.assertEqual(screen._selected_review_path, "specs/demo/nested/plan.md")
            self.assertEqual(select.value, "specs/demo/nested/plan.md")

    async def test_medium_combobox_is_keyboard_operable(self):
        session = self._review_session()
        async with self.app.run_test(size=(130, 40)) as pilot:
            screen = await self._open_changes(pilot, session)
            select = screen.query_one("#review-file-select", FeatureFileSelect)
            select.focus()
            await settle(pilot)
            await pilot.press("enter")
            await settle(pilot)
            await pilot.press("down")
            await settle(pilot)
            await pilot.press("enter")
            await settle(pilot)
            self.assertEqual(screen._selected_review_path, "specs/demo/nested/plan.md")
            self.assertEqual(select.value, "specs/demo/nested/plan.md")
            self.assertIn("plan.md", str(screen.query_one("#review-document").render()))

    async def test_medium_filter_still_narrows_files(self):
        session = self._review_session()
        async with self.app.run_test(size=(130, 40)) as pilot:
            screen = await self._open_changes(pilot, session)
            await pilot.press("slash")
            await pilot.press("p", "l", "a", "n")
            await settle(pilot)
            self.assertEqual(screen.query_one("#feature-files").option_count, 1)
            self.assertEqual(screen._selected_review_path, "specs/demo/nested/plan.md")

    async def test_medium_full_file_action_still_loads(self):
        session = self._review_session()
        async with self.app.run_test(size=(130, 40)) as pilot:
            screen = await self._open_changes(pilot, session)
            screen.query_one("#feature-files").focus()
            await pilot.press("j")
            await settle(pilot)
            await pilot.press("f")
            await settle(pilot)
            self.assertTrue(screen._full_file)
            self.assertIn("full body", str(screen.query_one("#review-document").render()))

    async def test_wide_keeps_index_and_hides_combobox(self):
        session = self._review_session()
        async with self.app.run_test(size=(160, 40)) as pilot:
            screen = await self._open_changes(pilot, session)
            self.assertFalse(screen.has_class("medium"))
            self.assertTrue(screen.query_one("#review-index").display)
            self.assertFalse(screen.query_one("#review-file-select", FeatureFileSelect).display)

    async def test_medium_class_flips_at_140(self):
        session = self._review_session()
        async with self.app.run_test(size=(140, 40)) as pilot:
            screen = await self._open_changes(pilot, session)
            self.assertFalse(screen.has_class("medium"))
            await pilot.resize_terminal(139, 40)
            await settle(pilot)
            self.assertTrue(screen.has_class("medium"))
            self.assertFalse(screen.query_one("#review-index").display)
            self.assertTrue(screen.query_one("#review-file-select", FeatureFileSelect).display)

    async def test_rows_and_header_show_shortened_paths_with_full_identity(self):
        session = FakeSession(status="paused")
        session.gate = ready_gate()
        session.review = ReviewSnapshot(
            feature_dir=FEATURE_DIR,
            files=(
                FeatureFile(path="specs/demo/spec.md", display="spec.md"),
                FeatureFile(path="specs/demo/nested/plan.md", display="nested/plan.md"),
            ),
        )

        def document(path, *, full=False):
            return ReviewDocument(path=path, display=path.removeprefix("specs/demo/"), text="body")

        session.review_document = document
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(self._screen(session))
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            screen = self.app.screen
            listing = screen.query_one("#feature-files")
            prompts = [str(option.prompt) for option in listing.options]
            ids = [str(option.id) for option in listing.options]
            self.assertEqual(ids, ["specs/demo/spec.md", "specs/demo/nested/plan.md"])
            self.assertIn("spec.md", prompts)
            self.assertIn("nested/plan.md", prompts)
            self.assertNotIn("specs/demo/", " ".join(prompts))
            # Selection identity and resolution stay project-relative.
            self.assertEqual(screen._selected_review_path, "specs/demo/spec.md")
            rendered = str(screen.query_one("#review-document").render())
            self.assertIn("spec.md", rendered)
            self.assertNotIn("specs/demo/", rendered)


if __name__ == "__main__":
    unittest.main()
