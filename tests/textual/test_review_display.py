"""Feature Files labels shorten to the feature directory while ids stay full."""

import tempfile
import unittest
from pathlib import Path

from tests.support import FakeSession, StyledApp
from workflow_cockpit.services.review import FeatureFile, ReviewDocument, ReviewSnapshot
from workflow_cockpit.services.snapshot import GateSnapshot, GateState
from workflow_cockpit.ui.screens.cockpit import CockpitScreen

FEATURE_DIR = "specs/demo"


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
