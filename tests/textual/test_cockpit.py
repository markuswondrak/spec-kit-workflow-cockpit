import asyncio
import unittest
from types import SimpleNamespace

from tests.support import FakeSession, StyledApp
from workflow_cockpit.services.graph import WorkflowDefinitionParser
from workflow_cockpit.services.snapshot import GateSnapshot, GateState
from workflow_cockpit.ui.screens.aborting import AbortingScreen
from workflow_cockpit.ui.screens.cockpit import CockpitScreen
from workflow_cockpit.ui.screens.confirm import ConfirmScreen
from workflow_cockpit.ui.widgets import TRUNCATION_MARKER, BounceIndicator, EngineOutput


def paused_gate(**kwargs) -> GateSnapshot:
    defaults = {
        "runtime_step_id": "review",
        "step_id": "review",
        "message": "Review it",
        "options": ("approve", "reject"),
        "state": GateState.BLOCKED,
        "reason": "No live engine process is waiting at this gate; only Abort is available.",
    }
    defaults.update(kwargs)
    return GateSnapshot(**defaults)


class CockpitScreenTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = StyledApp()

    async def test_running_state_and_output_render(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            self.assertIn("RUNNING", str(screen.query_one("#run-status").render()))
            log = screen.query_one("#engine")
            self.assertGreater(len(log.lines), 0)
            self.assertTrue(screen.query_one("#overview").has_class("compact-summary"))

    async def test_state_view_shows_context_path_and_skill_guidance(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            rendered = str(self.app.screen.query_one("#overview-content").render())
            self.assertIn("context", rendered)
            self.assertIn(".specify/workflows/runs/current_run", rendered)
            self.assertIn("cockpit-run-context", rendered)

    async def test_gate_view_shows_context_path(self):
        session = FakeSession(status="paused")
        session.gate = paused_gate()
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            rendered = str(self.app.screen.query_one("#overview-content").render())
            self.assertIn(".specify/workflows/runs/current_run", rendered)

    async def test_context_error_is_reported(self):
        session = FakeSession(status="running")
        session.context_path = ""
        session.context_error = "Context index unavailable: disk full"
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            rendered = str(self.app.screen.query_one("#overview-content").render())
            self.assertIn("disk full", rendered)

    async def test_abort_requires_confirmation_then_closes(self):
        session = FakeSession(status="running")
        session.abort_delay = 0.2
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            self.assertFalse(session.aborted)
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, AbortingScreen)
            for _ in range(200):
                if not self.app.is_running:
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(session.aborted)
            self.assertFalse(self.app.is_running)

    async def test_quit_requires_abort_confirmation_while_resize_guard_is_active(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            await pilot.resize_terminal(80, 30)
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()
            self.assertFalse(session.aborted)
            self.assertIn("Abort this run?", str(self.app.screen.query_one("#confirm-heading").render()))

    async def test_activity_indicator_tracks_live_state(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            activity = self.app.screen.query_one("#activity")
            self.assertIsInstance(activity, BounceIndicator)
            self.assertTrue(activity.display)
            # A declared gate awaits a decision even though the raw status stays
            # running; output is not rolling, so the indicator hides.
            session.gate = paused_gate()
            self.app.screen._refresh()
            await pilot.pause()
            self.assertFalse(activity.display)
            session.gate = None
            session.status = "paused"
            self.app.screen._refresh()
            await pilot.pause()
            self.assertFalse(activity.display)
            session.status = "success"
            self.app.screen._refresh()
            await pilot.pause()
            self.assertFalse(activity.display)

    async def test_aborting_with_output_flowing_keeps_the_indicator(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            activity = self.app.screen.query_one("#activity")
            session.status = "aborting"
            self.app.screen._refresh()
            await pilot.pause()
            self.assertTrue(activity.display)

    async def test_active_phase_tone_is_distinct_from_every_status_tone(self):
        from workflow_cockpit.ui.palette import palette
        from workflow_cockpit.ui.widgets import active_tone, status_tone

        self.assertEqual(active_tone(), palette.cold)
        for status in ("running", "completed", "paused", "pending", "skipped", "failed", "aborted"):
            with self.subTest(status=status):
                self.assertNotEqual(active_tone(), status_tone(status))

    async def test_current_node_rendered_bold_underline(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            runway = self.app.screen.query_one("#runway-graph")
            styles = {
                str(option.id): " ".join(str(span.style) for span in option.prompt.spans)
                for option in runway.options
            }
            from workflow_cockpit.ui.palette import palette

            self.assertIn("bold", styles["prepare"])
            self.assertIn("underline", styles["prepare"])
            self.assertIn(palette.cold, styles["prepare"])
            self.assertNotIn("underline", styles["review"])

    async def test_narrow_runway_keeps_full_labels_and_exposes_tooltip(self):
        session = FakeSession(status="running")
        session._graph = WorkflowDefinitionParser().parse(
            (
                {
                    "id": "assessment-gate",
                    "type": "gate",
                    "message": "Assess",
                    "options": ["approve"],
                },
                {"id": "bug-verification", "command": "demo.verify"},
            )
        )
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            runway = self.app.screen.query_one("#runway-graph")
            prompts = {str(option.id): str(option.prompt) for option in runway.options}
            self.assertIn("assessment-gate", prompts["assessment-gate"])
            self.assertIn("bug-verification", prompts["bug-verification"])
            index = next(
                position
                for position, option in enumerate(runway.options)
                if option.id == "bug-verification"
            )
            runway._on_mouse_move(SimpleNamespace(style=SimpleNamespace(meta={"option": index})))
            self.assertEqual(runway.tooltip, "bug-verification")
            runway._on_leave(SimpleNamespace())
            self.assertIsNone(runway.tooltip)

    async def test_runway_is_display_only(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            self.assertFalse(self.app.screen.query_one("#runway-graph").can_focus)

    async def test_outcome_acknowledged_with_enter(self):
        session = FakeSession(status="success")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            self.assertIn("RUN COMPLETE", str(screen.query_one("#view-label").render()))
            await pilot.press("enter")
            await pilot.pause()
            self.assertFalse(self.app.is_running)

    async def test_paused_surface_is_read_only_with_abort(self):
        session = FakeSession(status="paused")
        session.gate = paused_gate()
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            self.assertIn("GATE / REVIEW", str(screen.query_one("#view-label").render()))
            commands = screen.query_one("#commands").render()
            self.assertIn("abort", str(commands).lower())

    async def test_focus_mode_survives_refresh(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            screen._refresh()
            await pilot.pause()
            session.status = "paused"
            session.gate = paused_gate()
            screen._refresh()
            await pilot.pause()
            self.assertIn("GATE", str(screen.query_one("#view-label").render()))
            self.assertTrue(screen.query_one("#overview").display)
            session.status = "success"
            session.gate = None
            screen._refresh()
            await pilot.pause()
            self.assertIn("RUN COMPLETE", str(screen.query_one("#view-label").render()))

    async def test_output_keeps_appending_after_tail_saturates(self):
        session = FakeSession(status="running")
        session.output_lines = ["a", "b"]
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            log = self.app.screen.query_one("#engine")
            self.assertEqual(len(log.lines), 2)
            # The bounded tail stays the same length while a new line emits.
            session.output_lines = ["b", "c"]
            session.output_emitted = 3
            self.app.screen._refresh()
            await pilot.pause()
            self.assertEqual(len(log.lines), 3)
            self.assertIn("c", str(log.lines[-1]))

    async def test_output_shows_truncation_marker_after_dropped_lines(self):
        session = FakeSession(status="running")
        session.output_lines = ["kept"]
        session.output_emitted = 5
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            rendered = "\n".join(str(line) for line in self.app.screen.query_one("#engine").lines)
            self.assertIn(TRUNCATION_MARKER, rendered)
            self.assertIn("kept", rendered)

    async def test_output_scroll_survives_refresh_when_not_at_tail(self):
        session = FakeSession(status="running")
        session.output_lines = [f"line {index}" for index in range(200)]
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            log = self.app.screen.query_one(EngineOutput).log()
            log.scroll_home(animate=False)
            await pilot.pause()
            before = log.scroll_y
            session.output_lines = [*session.output_lines, "appended"]
            self.app.screen._refresh()
            await pilot.pause()
            self.assertEqual(log.scroll_y, before)

    async def test_runway_uses_compact_strip_at_narrow_supported_width(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(100, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            runway = self.app.screen.query_one("#runway")
            self.assertEqual(runway.region.height, 4)
            self.assertGreater(self.app.screen.query_one("#runway-graph").option_count, 0)

    async def test_help_overlay(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            from workflow_cockpit.ui.screens.help import HelpScreen

            self.assertIsInstance(self.app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, CockpitScreen)

    async def test_header_does_not_consume_half_the_screen(self):
        app = StyledApp()
        session = FakeSession(status="failed")
        async with app.run_test(size=(120, 52)) as pilot:
            app.push_screen(CockpitScreen(session))
            await pilot.pause()
            header = app.screen.query_one("#header")
            workspace = app.screen.query_one("#workspace")
            self.assertEqual(header.region.height, 4)
            self.assertEqual(workspace.region.y, header.region.height)

    async def test_resume_key_confirms_and_calls_session_once(self):
        session = FakeSession(status="failed")
        session.adopted_run = "cockpit-failed"
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            commands = str(screen.query_one("#commands").render())
            self.assertIn("resume", commands.lower())
            await pilot.press("r")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, ConfirmScreen)
            heading = str(self.app.screen.query_one("#confirm-heading").render())
            self.assertIn("resume", heading.lower())
            await pilot.press("enter")
            await pilot.pause(0.1)
            self.assertEqual(len(session.resumed_tokens), 1)

    async def test_resume_cancel_submits_nothing(self):
        session = FakeSession(status="failed")
        session.adopted_run = "cockpit-failed"
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(session.resumed_tokens, [])
            self.assertIsInstance(self.app.screen, CockpitScreen)

    async def test_resume_unavailable_when_read_only(self):
        session = FakeSession(status="failed")
        session.adopted_run = "cockpit-failed"
        session.read_only = True
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            self.assertIsInstance(self.app.screen, CockpitScreen)
            self.assertEqual(session.resumed_tokens, [])

    async def test_resume_confirmation_names_nested_parent(self):
        session = FakeSession(status="failed")
        session.adopted_run = "cockpit-failed"
        session._graph = WorkflowDefinitionParser().parse(
            (
                {
                    "id": "loop",
                    "type": "while",
                    "steps": [
                        {
                            "id": "review",
                            "type": "gate",
                            "message": "Review",
                            "options": ["approve"],
                        }
                    ],
                },
            )
        )
        session.current_step_id = "review"
        async with self.app.run_test(size=(120, 40)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            screen = self.app.screen
            self.assertIsInstance(screen, ConfirmScreen)
            heading = str(screen.query_one("#confirm-heading").render())
            effect = str(screen.query_one("#confirm-effect").render())
            self.assertIn("loop", heading)
            self.assertIn("whole nested body", effect)

    async def test_resize_guard_blocks_and_recovers(self):
        session = FakeSession(status="running")
        async with self.app.run_test(size=(80, 30)) as pilot:
            self.app.push_screen(CockpitScreen(session))
            await pilot.pause()
            screen = self.app.screen
            self.assertTrue(screen.query_one("#resize-guard").display)
            self.assertFalse(screen.query_one("#shell").display)
            await pilot.resize_terminal(120, 40)
            await pilot.pause()
            self.assertFalse(screen.query_one("#resize-guard").display)
            self.assertTrue(screen.query_one("#shell").display)


if __name__ == "__main__":
    unittest.main()
