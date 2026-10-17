"""The gate card renders a child gate with its scope path and Abort-only states."""

import asyncio
import unittest

from tests.composition_support import composed_snapshot, coordinator, state_data, tree_graph
from tests.fakes import FakeSession
from tests.fixtures import composition as fx
from tests.support import StyledApp
from workflow_cockpit.engine.supervisor import ProcessCondition
from workflow_cockpit.services.execution_tree import parse as parse_execution
from workflow_cockpit.ui.screens.cockpit import CockpitScreen
from workflow_cockpit.ui.widgets import GateDecisionBar


class SnapshotSession(FakeSession):
    """A session double that returns one prepared composed snapshot."""

    def __init__(self, snapshot):
        super().__init__(status=snapshot.status)
        self._prepared = snapshot

    def snapshot(self):
        return self._prepared


async def settle(pilot, rounds: int = 6) -> None:
    for _ in range(rounds):
        await pilot.pause()
        await asyncio.sleep(0.02)


def visible_options(screen) -> list[str]:
    bar = screen.query_one("#gate-decision", GateDecisionBar)
    return [button.label.plain for button in bar.query("Button") if button.display]


def blocked_snapshot(scenario: str, state):
    """A snapshot whose gate is the blocked projection of ``state``."""
    snapshot = composed_snapshot(scenario)
    _tree, graph = tree_graph(scenario)
    gate, _ = coordinator(graph)
    blocked = gate.project(
        state=state,
        run_id="run-1",
        condition=ProcessCondition(
            live=False, exit_code=0, reaped=True, aborting=False, stdin_pty=False
        ),
        gate_attempt=1,
    )
    return snapshot.__class__(**{**snapshot.__dict__, "gate": blocked})


class ComposedGateCardTests(unittest.IsolatedAsyncioTestCase):
    async def _render(self, snapshot, check):
        app = StyledApp()
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(CockpitScreen(SnapshotSession(snapshot)))
            await settle(pilot)
            check(app.screen)

    async def test_child_gate_shows_message_options_and_scope_line(self):
        def check(screen):
            overview = str(screen.query_one("#overview-content").render())
            self.assertIn("Approve the release notes?", overview)
            self.assertIn("scope review-release > review", overview)
            self.assertEqual(visible_options(screen), ["approve", "reject"])

        await self._render(composed_snapshot("reference"), check)

    async def test_colliding_root_gate_is_never_shown(self):
        def check(screen):
            overview = str(screen.query_one("#overview-content").render())
            self.assertIn("Approve the release notes?", overview)
            self.assertNotIn("Approve the root release?", overview)
            self.assertIn("review-release > review", overview)

        await self._render(composed_snapshot("collision"), check)

    async def test_two_calls_deep_renders_the_full_scope_path(self):
        def check(screen):
            overview = str(screen.query_one("#overview-content").render())
            self.assertIn("middle-call > inner-call > deep-review", overview)

        await self._render(composed_snapshot("depth2"), check)

    async def test_unresolved_position_offers_abort_only(self):
        raw = fx.with_current_step_id(fx.load_state("reference"), "publish")
        snapshot = blocked_snapshot("reference", state_data("reference", execution=parse_execution(raw)))

        def check(screen):
            overview = str(screen.query_one("#overview-content").render())
            self.assertIn("unresolved", overview.lower())
            self.assertEqual(visible_options(screen), [])

        await self._render(snapshot, check)

    async def test_undecidable_gate_names_the_scope_and_reason(self):
        def check(screen):
            overview = str(screen.query_one("#overview-content").render())
            self.assertIn("fan > 0 > notes > review", overview)
            self.assertIn("Undecidable", overview)
            self.assertEqual(visible_options(screen), [])

        await self._render(composed_snapshot("fanout"), check)

    async def test_unsupported_version_gate_is_abort_only(self):
        raw = fx.with_version(fx.load_state("reference"), 3)
        snapshot = blocked_snapshot("reference", state_data("reference", execution=parse_execution(raw)))

        def check(screen):
            overview = str(screen.query_one("#overview-content").render())
            self.assertIn("not supported", overview)
            self.assertEqual(visible_options(screen), [])

        await self._render(snapshot, check)


if __name__ == "__main__":
    unittest.main()
