import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from textual.widgets import Button, Select

from tests.support import FakeSession, StyledApp
from workflow_cockpit.services.review import FeatureFile, ReviewDocument, ReviewSnapshot
from workflow_cockpit.services.snapshot import GateSnapshot, GateState
from workflow_cockpit.ui.screens.cockpit import CockpitScreen
from workflow_cockpit.ui.screens.confirm import ConfirmScreen
from workflow_cockpit.ui.widgets import GateDecisionBar


def ready_gate(**kwargs) -> GateSnapshot:
    defaults = {
        "runtime_step_id": "review",
        "step_id": "review",
        "message": "Approve the plan?",
        "options": ("approve", "reject"),
        "on_reject": "retry",
        "state": GateState.READY,
        "token": "token-1",
    }
    defaults.update(kwargs)
    return GateSnapshot(**defaults)


def review() -> ReviewSnapshot:
    return ReviewSnapshot(
        feature_dir="specs/demo",
        files=(FeatureFile(path="a.txt"),),
    )


async def settle(pilot, rounds: int = 5) -> None:
    for _ in range(rounds):
        await pilot.pause()
        await asyncio.sleep(0.02)


def bar(screen) -> GateDecisionBar:
    return screen.query_one("#gate-decision", GateDecisionBar)


def visible_buttons(screen) -> list[Button]:
    return [button for button in bar(screen).query(Button) if button.display]


class GateSurfaceParityTests(unittest.IsolatedAsyncioTestCase):
    """The same gate-surface assertions for structured and interactive gates."""

    def _fixture(self, kind: str) -> FakeSession:
        live = kind == "interactive"
        session = FakeSession(status="running" if live else "paused")
        session.gate = ready_gate()
        session.process_live_override = live
        if live:
            # Do not preload review data: the screen must request it.
            def refresh():
                session.refreshed += 1
                session.review = review()
                return session.review

            session.refresh_review = refresh
        else:
            session.review = review()
        return session

    async def test_ready_gate_surface_is_identical(self):
        for kind in ("structured", "interactive"):
            with self.subTest(kind=kind):
                session = self._fixture(kind)
                app = StyledApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(CockpitScreen(session))
                    await settle(pilot)
                    screen = app.screen
                    self.assertIn("GATE / REVIEW", str(screen.query_one("#view-label").render()))
                    self.assertIn("Approve the plan?", str(screen.query_one("#overview-content").render()))
                    self.assertEqual([button.label.plain for button in visible_buttons(screen)], ["approve", "reject"])
                    self.assertFalse(screen.query_one("#gate-select", Select).display)
                    self.assertTrue(screen.query_one("#review-panel").display)
                    self.assertTrue(screen.query_one("#decide-bar").display)
                    self.assertEqual(screen.query_one("#feature-files").option_count, 1)
                    self.assertGreaterEqual(session.refreshed, 1)

    async def test_digit_choice_confirms_then_submits(self):
        for kind in ("structured", "interactive"):
            with self.subTest(kind=kind):
                session = self._fixture(kind)
                app = StyledApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(CockpitScreen(session))
                    await settle(pilot)
                    await pilot.press("2")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, ConfirmScreen)
                    self.assertEqual(session.decisions, [])
                    await pilot.press("enter")
                    await settle(pilot)
                    self.assertEqual(session.decisions, ["reject"])

    async def test_cancelled_choice_submits_nothing(self):
        for kind in ("structured", "interactive"):
            with self.subTest(kind=kind):
                session = self._fixture(kind)
                app = StyledApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(CockpitScreen(session))
                    await settle(pilot)
                    await pilot.press("1")
                    await pilot.pause()
                    await pilot.press("escape")
                    await settle(pilot)
                    self.assertEqual(session.decisions, [])

    async def test_command_rail_offers_decisions_and_abort(self):
        for kind in ("structured", "interactive"):
            with self.subTest(kind=kind):
                session = self._fixture(kind)
                app = StyledApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(CockpitScreen(session))
                    await settle(pilot)
                    rail = str(app.screen.query_one("#commands").render())
                    self.assertIn("decide", rail.lower())
                    self.assertIn("abort", rail.lower())

    async def test_confirmation_copy_is_transport_neutral(self):
        for kind in ("structured", "interactive"):
            with self.subTest(kind=kind):
                session = self._fixture(kind)
                app = StyledApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(CockpitScreen(session))
                    await settle(pilot)
                    await pilot.press("1")
                    await pilot.pause()
                    rendered = str(app.screen.query_one("#confirm-sheet").render()).lower()
                    self.assertNotIn("pty", rendered)
                    self.assertNotIn("verdict_input", rendered)

    async def test_ordinary_keys_never_submit(self):
        for kind in ("structured", "interactive"):
            with self.subTest(kind=kind):
                session = self._fixture(kind)
                app = StyledApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(CockpitScreen(session))
                    await settle(pilot)
                    for key in ("y", "n", "down", "up", "right", "left"):
                        await pilot.press(key)
                        await pilot.pause()
                    self.assertEqual(session.decisions, [])

    async def test_stale_confirmation_submits_nothing(self):
        for kind in ("structured", "interactive"):
            with self.subTest(kind=kind):
                session = self._fixture(kind)
                app = StyledApp()
                async with app.run_test(size=(120, 40)) as pilot:
                    app.push_screen(CockpitScreen(session))
                    await settle(pilot)
                    await pilot.press("1")
                    await pilot.pause()
                    session.gate = replace(session.gate, token="changed")
                    await pilot.press("enter")
                    await settle(pilot)
                    self.assertEqual(session.decisions, [])


class GateStateSurfaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = StyledApp()

    def _session(self, gate: GateSnapshot, **kwargs) -> FakeSession:
        session = FakeSession(status=kwargs.pop("status", "paused"))
        session.gate = gate
        session.review = kwargs.pop("review", review())
        for key, value in kwargs.items():
            setattr(session, key, value)
        return session

    async def test_submitted_gate_shows_options_disabled(self):
        session = self._session(
            ready_gate(state=GateState.SUBMITTED, token=None, acknowledged="Choice submitted once.")
        )
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            self.assertEqual(len(visible_buttons(screen)), 2)
            self.assertTrue(all(button.disabled for button in visible_buttons(screen)))
            self.assertIn("submitted", str(screen.query_one("#overview-content").render()).lower())
            await pilot.press("1")
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(session.decisions, [])

    async def test_unverified_gate_shows_acknowledgement_and_abort_only(self):
        session = self._session(
            ready_gate(
                state=GateState.UNVERIFIED,
                token=None,
                acknowledged="CHOICE SENT, STATE NOT ADVANCED",
            )
        )
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            rendered = str(screen.query_one("#overview-content").render())
            self.assertIn("CHOICE SENT, STATE NOT ADVANCED", rendered)
            self.assertTrue(screen.query_one("#output").display)
            self.assertEqual(len(visible_buttons(screen)), 2)
            await pilot.press("1")
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(session.decisions, [])

    async def test_blocked_gate_shows_options_and_reason(self):
        session = self._session(
            ready_gate(
                state=GateState.BLOCKED,
                token=None,
                reason="No live engine process is waiting at this gate; only Abort is available.",
            ),
            status="running",
            process_live_override=False,
        )
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            self.assertEqual(len(visible_buttons(screen)), 2)
            self.assertIn("No live engine process", str(screen.query_one("#overview-content").render()))
            await pilot.press("1")
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(session.decisions, [])

    async def test_output_drawer_splits_at_gate_without_hiding_decisions(self):
        session = self._session(ready_gate())
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            output = screen.query_one("#output")
            self.assertTrue(screen.query_one("#decide-bar").display)

            screen.action_expand_output()
            await pilot.pause()
            self.assertTrue(output.has_class("expanded"))
            self.assertFalse(output.has_class("full-canvas"))
            self.assertTrue(screen.query_one("#decide-bar").display)
            self.assertTrue(screen.query_one("#review-panel").display)

            screen.action_expand_output()
            await pilot.pause()
            self.assertTrue(output.has_class("full-canvas"))

            screen.action_expand_output()
            await pilot.pause()
            self.assertFalse(output.has_class("expanded"))
            self.assertFalse(output.has_class("full-canvas"))
            self.assertTrue(screen.query_one("#decide-bar").display)

    async def test_live_gate_allows_editor(self):
        session = self._session(
            ready_gate(),
            status="running",
            process_live_override=True,
        )
        tmp = tempfile.TemporaryDirectory()
        session.project_root = Path(tmp.name)
        (Path(tmp.name) / "a.txt").write_text("content\n", encoding="utf-8")
        launches: list[list[str]] = []
        try:
            async with self.app.run_test(size=(120, 40)) as pilot:
                screen = CockpitScreen(
                    session,
                    editor_launcher=lambda argv, cwd: launches.append(list(argv)) or 0,
                    editor_env=lambda: "/bin/true",
                )
                self.app.push_screen(screen)
                await settle(pilot)
                await pilot.press("c")
                await settle(pilot)
                await pilot.press("o")
                await settle(pilot)
                self.assertEqual(len(launches), 1)
        finally:
            tmp.cleanup()


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

    def _session(self) -> FakeSession:
        session = FakeSession(status="paused")
        session.gate = ready_gate()
        session.review = review()
        session.project_root = self.root
        return session

    async def test_changes_mode_lists_files_and_shows_document(self):
        session = self._session()
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
        session = self._session()
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
        session = self._session()
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
        session = self._session()
        session.review = ReviewSnapshot(feature_dir="specs/demo", files=())
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(self._screen(session))
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            self.assertIn("No feature files", str(self.app.screen.query_one("#review-document").render()))

    async def test_editor_rejects_binary_document(self):
        session = self._session()

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
        session = self._session()
        session.review = ReviewSnapshot(
            feature_dir="specs/demo",
            files=(
                FeatureFile(path="a.txt"),
                FeatureFile(path="b.txt"),
            ),
        )
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
        session = self._session()
        session.review = ReviewSnapshot(
            feature_dir="specs/demo",
            files=(
                FeatureFile(path="a.txt"),
                FeatureFile(path="b.txt"),
            ),
        )
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


class GateAffordanceSurfaceTests(unittest.IsolatedAsyncioTestCase):
    """Buttons for 1-3 declared choices, a select for 4+ (contract C1-C4)."""

    async def asyncSetUp(self):
        self.app = StyledApp()

    def _session(self, options) -> FakeSession:
        session = FakeSession(status="paused")
        session.gate = ready_gate(options=tuple(options))
        session.review = review()
        return session

    async def _mount(self, pilot, options):
        session = self._session(options)
        self.app.push_screen(CockpitScreen(session))
        await settle(pilot)
        return session

    async def test_two_choice_gate_renders_buttons(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            await self._mount(pilot, ("approve", "reject"))
            screen = self.app.screen
            self.assertEqual(
                [button.label.plain for button in visible_buttons(screen)], ["approve", "reject"]
            )
            self.assertFalse(screen.query_one("#gate-select", Select).display)

    async def test_three_choice_gate_renders_three_buttons(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            await self._mount(pilot, ("a", "b", "c"))
            self.assertEqual(len(visible_buttons(self.app.screen)), 3)

    async def test_one_choice_gate_renders_one_button(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            await self._mount(pilot, ("only",))
            self.assertEqual([button.label.plain for button in visible_buttons(self.app.screen)], ["only"])

    async def test_button_labels_are_declared_choices_verbatim(self):
        options = ("Ship it", "Needs work")
        async with self.app.run_test(size=(120, 40)) as pilot:
            await self._mount(pilot, options)
            labels = [button.label.plain for button in visible_buttons(self.app.screen)]
            self.assertEqual(labels, list(options))

    async def test_mouse_press_confirms_that_exact_choice(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            session = await self._mount(pilot, ("approve", "reject"))
            await pilot.click("#gate-choice-1")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, ConfirmScreen)
            self.assertIn("reject", str(self.app.screen.query_one("#confirm-heading").render()))
            self.assertEqual(session.decisions, [])
            await pilot.press("enter")
            await settle(pilot)
            self.assertEqual(session.decisions, ["reject"])

    async def test_four_choice_gate_renders_select(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            await self._mount(pilot, ("a", "b", "c", "d"))
            screen = self.app.screen
            self.assertTrue(screen.query_one("#gate-select", Select).display)
            self.assertEqual(visible_buttons(screen), [])
            self.assertFalse(screen.query_one("#gate-choice-0", Button).display)

    async def test_digit_four_submits_the_fourth_choice(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            session = await self._mount(pilot, ("a", "b", "c", "d"))
            await pilot.press("4")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, ConfirmScreen)
            await pilot.press("enter")
            await settle(pilot)
            self.assertEqual(session.decisions, ["d"])

    async def test_choosing_a_select_entry_starts_confirmation(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            session = await self._mount(pilot, ("a", "b", "c", "d"))
            self.app.screen.query_one("#gate-select", Select).value = "c"
            await pilot.pause()
            self.assertIsInstance(self.app.screen, ConfirmScreen)
            self.assertIn("'c'", str(self.app.screen.query_one("#confirm-heading").render()))
            self.assertEqual(session.decisions, [])
            await pilot.press("enter")
            await settle(pilot)
            self.assertEqual(session.decisions, ["c"])

    async def test_forced_refresh_does_not_retrigger_confirmation(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            session = self._session(("a", "b", "c", "d"))
            cockpit = CockpitScreen(session)
            self.app.push_screen(cockpit)
            await settle(pilot)
            cockpit.query_one("#gate-select", Select).value = "d"
            await pilot.pause()
            self.assertIsInstance(self.app.screen, ConfirmScreen)
            cockpit._refresh()
            await settle(pilot)
            self.assertIsInstance(self.app.screen, ConfirmScreen)
            self.assertEqual(session.decisions, [])
            await pilot.press("enter")
            await settle(pilot)
            self.assertEqual(session.decisions, ["d"])

    async def test_left_right_moves_selection_without_submitting(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            session = await self._mount(pilot, ("approve", "reject"))
            screen = self.app.screen
            bar(screen).focus()
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(bar(screen).selected_option(), "reject")
            self.assertEqual(session.decisions, [])
            self.assertTrue(screen.query_one("#gate-choice-1", Button).has_class("selected"))

    async def test_enter_confirms_the_tracked_selection(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            session = await self._mount(pilot, ("approve", "reject"))
            bar(self.app.screen).focus()
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, ConfirmScreen)
            await pilot.press("enter")
            await settle(pilot)
            self.assertEqual(session.decisions, ["reject"])


class GateViewOnlyTests(unittest.IsolatedAsyncioTestCase):
    """View-only gates show choices but offer no submission (contract C5)."""

    async def asyncSetUp(self):
        self.app = StyledApp()

    def _session(self, options) -> FakeSession:
        session = FakeSession(status="paused")
        session.gate = ready_gate(options=tuple(options), state=GateState.SUBMITTED, token=None)
        session.review = review()
        return session

    async def test_view_only_buttons_are_disabled_and_submit_nothing(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            session = self._session(("approve", "reject"))
            self.app.push_screen(CockpitScreen(session))
            await settle(pilot)
            screen = self.app.screen
            self.assertEqual(len(visible_buttons(screen)), 2)
            self.assertTrue(all(button.disabled for button in visible_buttons(screen)))
            self.assertFalse(bar(screen).can_focus)
            await pilot.press("1")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.click("#gate-choice-0")
            await settle(pilot)
            self.assertEqual(session.decisions, [])

    async def test_view_only_select_is_disabled_and_submits_nothing(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            session = self._session(("a", "b", "c", "d", "e"))
            self.app.push_screen(CockpitScreen(session))
            await settle(pilot)
            screen = self.app.screen
            select = screen.query_one("#gate-select", Select)
            self.assertTrue(select.display)
            self.assertTrue(select.disabled)
            await pilot.press("5")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.click("#gate-select")
            await settle(pilot)
            self.assertEqual(session.decisions, [])


class GateSelectionStabilityTests(unittest.IsolatedAsyncioTestCase):
    """The tracked selection survives refresh and mode switches (contract C6)."""

    async def asyncSetUp(self):
        self.app = StyledApp()

    def _session(self, options) -> FakeSession:
        session = FakeSession(status="paused")
        session.gate = ready_gate(options=tuple(options))
        session.review = review()
        return session

    async def test_button_selection_survives_refresh(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            session = self._session(("approve", "reject"))
            self.app.push_screen(CockpitScreen(session))
            await settle(pilot)
            screen = self.app.screen
            bar(screen).select("reject")
            screen._refresh()
            await settle(pilot)
            self.assertEqual(bar(screen).selected_option(), "reject")
            self.assertTrue(screen.query_one("#gate-choice-1", Button).has_class("selected"))

    async def test_select_selection_survives_refresh(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            session = self._session(("a", "b", "c", "d"))
            self.app.push_screen(CockpitScreen(session))
            await settle(pilot)
            screen = self.app.screen
            bar(screen).select("c")
            await pilot.pause()
            screen._refresh()
            await settle(pilot)
            self.assertEqual(bar(screen).selected_option(), "c")
            self.assertEqual(screen.query_one("#gate-select", Select).value, "c")

    async def test_selection_survives_a_mode_switch(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            session = self._session(("a", "b", "c"))
            self.app.push_screen(CockpitScreen(session))
            await settle(pilot)
            screen = self.app.screen
            bar(screen).select("c")
            session.gate = ready_gate(options=("a", "b", "c", "d"))
            screen._refresh()
            await settle(pilot)
            self.assertTrue(screen.query_one("#gate-select", Select).display)
            self.assertEqual(bar(screen).selected_option(), "c")
            self.assertEqual(screen.query_one("#gate-select", Select).value, "c")

    async def test_selection_falls_back_when_choice_disappears(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            session = self._session(("a", "b", "c"))
            self.app.push_screen(CockpitScreen(session))
            await settle(pilot)
            screen = self.app.screen
            bar(screen).select("c")
            session.gate = ready_gate(options=("a", "b"))
            screen._refresh()
            await settle(pilot)
            self.assertEqual(bar(screen).selected_option(), "a")
            self.assertFalse(screen.query_one("#gate-choice-2", Button).display)

    async def test_cancelled_confirmation_restores_prior_selection(self):
        async with self.app.run_test(size=(120, 40)) as pilot:
            session = self._session(("a", "b", "c", "d"))
            self.app.push_screen(CockpitScreen(session))
            await settle(pilot)
            screen = self.app.screen
            select = screen.query_one("#gate-select", Select)
            select.value = "c"
            await pilot.pause()
            self.assertIsInstance(self.app.screen, ConfirmScreen)
            await pilot.press("escape")
            await settle(pilot)
            self.assertEqual(session.decisions, [])
            self.assertEqual(bar(screen).selected_option(), "a")
            self.assertEqual(select.value, "a")


if __name__ == "__main__":
    unittest.main()
