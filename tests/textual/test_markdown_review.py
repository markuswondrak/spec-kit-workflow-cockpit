import asyncio
import tempfile
import unittest
from pathlib import Path

from tests.support import FakeSession, StyledApp
from workflow_cockpit.services.review import FeatureFile, ReviewDocument, ReviewSnapshot
from workflow_cockpit.services.snapshot import GateSnapshot, GateState
from workflow_cockpit.ui.screens.cockpit import CockpitScreen


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


async def settle(pilot, rounds: int = 6) -> None:
    for _ in range(rounds):
        await pilot.pause()
        await asyncio.sleep(0.02)


class MarkdownReviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = StyledApp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def _session(self, paths: tuple[str, ...] = ("specs/demo/spec.md",)) -> FakeSession:
        session = FakeSession(status="paused")
        session.gate = ready_gate()
        session.review = ReviewSnapshot(
            feature_dir="specs/demo",
            files=tuple(FeatureFile(path=path) for path in paths),
        )
        session.project_root = self.root
        return session

    def _screen(self, session: FakeSession) -> CockpitScreen:
        return CockpitScreen(session, editor_env=lambda: None)

    async def test_markdown_file_renders_formatted_blocks(self):
        session = self._session()
        body = "# Heading\n\n- one\n- two\n\n```python\nprint('hi')\n```\n"
        session.review_document = lambda path, *, full=False: ReviewDocument(
            path=path, text=body, markdown=True
        )
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(self._screen(session))
            await settle(pilot)
            screen = self.app.screen
            markdown = screen.query_one("#review-markdown")
            plain = screen.query_one("#review-document")
            self.assertTrue(markdown.display)
            self.assertFalse(plain.display)
            self.assertTrue(markdown.query("MarkdownH1"))
            self.assertTrue(markdown.query("MarkdownBulletList"))
            self.assertTrue(markdown.query("MarkdownFence"))

    async def test_non_markdown_text_stays_plain(self):
        session = self._session(("specs/demo/spec.txt",))
        session.review_document = lambda path, *, full=False: ReviewDocument(
            path=path, text="plain content\n", markdown=False
        )
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(self._screen(session))
            await settle(pilot)
            screen = self.app.screen
            self.assertTrue(screen.query_one("#review-document").display)
            self.assertFalse(screen.query_one("#review-markdown").display)
            self.assertIn("plain content", str(screen.query_one("#review-document").render()))

    async def test_large_markdown_preview_then_full_load(self):
        session = self._session()
        calls: list[bool] = []
        body = "# Heading\n\n" + ("line\n" * 200)

        def document(path, *, full=False):
            calls.append(full)
            if full:
                return ReviewDocument(path=path, text=body, markdown=True)
            return ReviewDocument(
                path=path,
                text=body,
                markdown=True,
                truncated=True,
                limit_bytes=200_000,
                total_bytes=1_000_000,
            )

        session.review_document = document
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(self._screen(session))
            await settle(pilot)
            screen = self.app.screen
            self.assertIn("Preview truncated", screen.query_one("#review-markdown").source)
            await pilot.press("f")
            await settle(pilot, rounds=25)
            self.assertIn(True, calls)
            self.assertNotIn("Preview truncated", screen.query_one("#review-markdown").source)

    async def test_refresh_keeps_full_load(self):
        session = self._session()
        body = "# Heading\n\n" + ("line\n" * 200)

        def document(path, *, full=False):
            return ReviewDocument(
                path=path,
                text=body,
                markdown=True,
                truncated=not full,
                limit_bytes=200_000,
            )

        session.review_document = document
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(self._screen(session))
            await settle(pilot)
            screen = self.app.screen
            await pilot.press("f")
            await settle(pilot, rounds=25)
            self.assertNotIn("Preview truncated", screen.query_one("#review-markdown").source)
            # A completed refresh re-lists files but must not snap back to preview.
            screen._render_review_files(screen._snapshot_now())
            await settle(pilot)
            self.assertTrue(screen._full_file)
            self.assertNotIn("Preview truncated", screen.query_one("#review-markdown").source)

    async def test_malformed_markdown_renders_without_error(self):
        session = self._session()
        body = "# Heading\n\n[unclosed link](\n\n| broken | table\n| ---\n\n> quote\n\n```\n"
        session.review_document = lambda path, *, full=False: ReviewDocument(
            path=path, text=body, markdown=True
        )
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(self._screen(session))
            await settle(pilot)
            screen = self.app.screen
            markdown = screen.query_one("#review-markdown")
            self.assertTrue(markdown.display)
            self.assertIn("unclosed link", markdown.source)

    async def test_scroll_preserved_on_same_path_refresh(self):
        session = self._session()
        body = "# Heading\n\n" + ("line\n" * 400)
        document = ReviewDocument(path="specs/demo/spec.md", text=body, markdown=True)
        session.review_document = lambda path, *, full=False: document
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(self._screen(session))
            await settle(pilot)
            screen = self.app.screen
            scroll = screen.query_one("#review-scroll")
            scroll.scroll_to(y=6, animate=False)
            await pilot.pause()
            screen._show_document(document)
            await settle(pilot)
            self.assertEqual(scroll.scroll_y, 6)

    async def test_switching_path_resets_scroll(self):
        session = self._session(("specs/demo/a.md", "specs/demo/b.md"))
        body = "# Heading\n\n" + ("line\n" * 400)

        def document(path, *, full=False):
            return ReviewDocument(path=path, text=body, markdown=True)

        session.review_document = document
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(self._screen(session))
            await settle(pilot)
            screen = self.app.screen
            scroll = screen.query_one("#review-scroll")
            scroll.scroll_to(y=6, animate=False)
            await pilot.pause()
            screen._show_document(document("specs/demo/b.md"))
            await settle(pilot)
            self.assertEqual(scroll.scroll_y, 0)

    async def test_editor_opens_raw_markdown_source(self):
        launched: list[list[str]] = []
        session = self._session()
        (self.root / "specs" / "demo").mkdir(parents=True)
        (self.root / "specs" / "demo" / "spec.md").write_text("# Heading\n", encoding="utf-8")
        session.review_document = lambda path, *, full=False: ReviewDocument(
            path=path, text="# Heading\n", markdown=True
        )
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(
                CockpitScreen(
                    session,
                    editor_launcher=lambda argv, cwd: launched.append(list(argv)) or 0,
                    editor_env=lambda: "/bin/true",
                )
            )
            await settle(pilot)
            await pilot.press("o")
            await settle(pilot)
            self.assertEqual(len(launched), 1)
            self.assertTrue(launched[0][-1].endswith("spec.md"))


if __name__ == "__main__":
    unittest.main()
