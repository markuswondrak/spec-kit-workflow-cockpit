import tempfile
import unittest
from pathlib import Path

from tests.support import FakeSession, StyledApp
from workflow_cockpit.services.review import FeatureFile, ReviewDocument, ReviewSnapshot
from workflow_cockpit.services.snapshot import GateSnapshot
from workflow_cockpit.ui.screens.cockpit import CockpitScreen
from workflow_cockpit.ui.screens.confirm import ConfirmScreen


def gate(**kwargs) -> GateSnapshot:
    defaults = {
        "runtime_step_id": "review",
        "step_id": "review",
        "message": "Approve the plan?",
        "options": ("approve", "reject"),
        "verdict_input": "review_verdict",
        "on_reject": "retry",
    }
    defaults.update(kwargs)
    return GateSnapshot(**defaults)


def review() -> ReviewSnapshot:
    return ReviewSnapshot(
        feature_dir="specs/demo",
        files=(FeatureFile(path="a.txt"),),
    )


class GateDecisionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = StyledApp()

    async def _paused(self, **kwargs):
        session = FakeSession(status="paused")
        session.gate = gate(**kwargs)
        session.review = review()
        return session

    async def test_gate_mode_opens_automatically_with_options(self):
        session = await self._paused()
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            self.assertIn("GATE / PAUSED", str(screen.query_one("#view-label").render()))
            self.assertIn("Approve the plan?", str(screen.query_one("#overview-content").render()))
            self.assertEqual(screen.query_one("#gate-options").option_count, 2)
            self.assertTrue(screen.query_one("#review-panel").display)
            self.assertTrue(screen.query_one("#decide-bar").display)
            self.assertEqual(screen.query_one("#feature-files").option_count, 1)

    async def test_digit_choice_requires_confirmation_then_decides(self):
        session = await self._paused()
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, ConfirmScreen)
            self.assertEqual(session.decisions, [])
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(session.decisions, ["reject"])

    async def test_cancelled_choice_does_not_decide(self):
        session = await self._paused()
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            await pilot.press("1")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(session.decisions, [])
            self.assertIsInstance(self.app.screen, CockpitScreen)

    async def test_unstructured_gate_has_no_choices(self):
        session = await self._paused(verdict_input=None)
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            self.assertEqual(screen.query_one("#gate-options").option_count, 0)
            await pilot.press("1")
            await pilot.pause()
            self.assertEqual(session.decisions, [])

    async def test_malformed_gate_reports_only_abort(self):
        session = await self._paused(options=(), malformed=True)
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            rendered = str(self.app.screen.query_one("#overview-content").render())
            self.assertIn("missing options", rendered)
            self.assertEqual(self.app.screen.query_one("#gate-options").option_count, 0)

    async def test_resume_live_blocks_decisions_and_editor(self):
        session = await self._paused()
        session.process_live_override = True
        launches: list[list[str]] = []
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = CockpitScreen(
                session,
                editor_launcher=lambda argv, cwd: launches.append(list(argv)) or 0,
                editor_env=lambda: "/bin/true",
            )
            self.app.push_screen(screen)
            await pilot.pause()
            self.assertFalse(screen.query_one("#decide-bar").display)
            self.assertEqual(screen.query_one("#gate-options").option_count, 0)
            screen.action_choose("1")
            screen.action_open_editor()
            self.assertEqual(launches, [])


class ReviewSurfaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = StyledApp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "a.txt").write_text("changed\n", encoding="utf-8")
        self.launches: list[list[str]] = []

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def _screen(self, session):
        return CockpitScreen(
            session,
            editor_launcher=lambda argv, cwd: self.launches.append(list(argv)) or 0,
            editor_env=lambda: "/bin/true",
        )

    async def test_changes_mode_lists_files_and_shows_document(self):
        session = FakeSession(status="paused")
        session.gate = gate()
        session.review = review()
        session.project_root = self.root
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(self._screen(session))
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            screen = self.app.screen
            self.assertTrue(screen.query_one("#review-panel").display)
            self.assertEqual(screen.query_one("#feature-files").option_count, 1)
            self.assertIn("file content", str(screen.query_one("#review-document").render()))

    async def test_open_editor_launches_with_suspended_app(self):
        session = FakeSession(status="paused")
        session.gate = gate()
        session.review = review()
        session.project_root = self.root
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(self._screen(session))
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            self.assertEqual(len(self.launches), 1)
            self.assertTrue(self.launches[0][-1].endswith("a.txt"))

    async def test_editor_unavailable_when_unset(self):
        session = FakeSession(status="paused")
        session.gate = gate()
        session.review = review()
        session.project_root = self.root
        screen = CockpitScreen(
            session,
            editor_launcher=lambda argv, cwd: self.launches.append(list(argv)) or 0,
            editor_env=lambda: None,
        )
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(screen)
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            self.assertEqual(self.launches, [])
            self.assertIn("EDITOR is unset", screen._diagnostic)

    async def test_editor_unavailable_while_running(self):
        session = FakeSession(status="running")
        session.project_root = self.root
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = self._screen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            screen.action_open_editor()
            self.assertEqual(self.launches, [])

    async def test_empty_review_shows_empty_state(self):
        session = FakeSession(status="paused")
        session.gate = gate()
        session.review = ReviewSnapshot(feature_dir="specs/demo", files=())
        session.project_root = self.root
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(self._screen(session))
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            self.assertIn("No feature files", str(self.app.screen.query_one("#review-document").render()))

    async def test_editor_rejects_binary_document(self):
        session = FakeSession(status="paused")
        session.gate = gate()
        session.review = review()
        session.project_root = self.root

        def binary_document(path, *, full=False):
            return ReviewDocument(path=path, binary=True, note="Binary file")

        session.review_document = binary_document
        async with self.app.run_test(size=(120, 40)) as pilot:
            screen = self._screen(session)
            self.app.push_screen(screen)
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            self.assertEqual(self.launches, [])

    async def test_filter_narrows_file_list(self):
        session = FakeSession(status="paused")
        session.gate = gate()
        session.review = ReviewSnapshot(
            feature_dir="specs/demo",
            files=(
                FeatureFile(path="a.txt"),
                FeatureFile(path="b.txt"),
            ),
        )
        session.project_root = self.root
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(self._screen(session))
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("slash")
            await pilot.press("b")
            await pilot.pause()
            self.assertEqual(self.app.screen.query_one("#feature-files").option_count, 1)

    async def test_selection_survives_refresh(self):
        session = FakeSession(status="paused")
        session.gate = gate()
        session.review = ReviewSnapshot(
            feature_dir="specs/demo",
            files=(
                FeatureFile(path="a.txt"),
                FeatureFile(path="b.txt"),
            ),
        )
        session.project_root = self.root
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(self._screen(session))
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            screen = self.app.screen
            screen.query_one("#feature-files").focus()
            await pilot.press("j")
            await pilot.pause()
            # b.txt is not on disk, so the mock still renders its document.
            self.assertEqual(screen._selected_review_path, "b.txt")
            session.refresh_review()
            screen._refresh()
            await pilot.pause()
            self.assertEqual(screen._selected_review_path, "b.txt")


if __name__ == "__main__":
    unittest.main()
