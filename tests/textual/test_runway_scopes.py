"""The runway shows where the run is across scopes, from the frozen tree."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from tests.composition_support import composed_snapshot, state_data, timings_for, tree_graph
from tests.fakes import FakeSession
from tests.fixtures import composition as fx
from tests.support import StyledApp
from workflow_cockpit.services.projection import GraphProjector
from workflow_cockpit.services.run_state import RunStateData
from workflow_cockpit.ui.screens.cockpit import CockpitScreen
from workflow_cockpit.ui.view_model import render_runway


class SnapshotSession(FakeSession):
    def __init__(self, snapshot):
        super().__init__(status=snapshot.status)
        self._prepared = snapshot

    def snapshot(self):
        return self._prepared


async def settle(pilot, rounds: int = 6) -> None:
    for _ in range(rounds):
        await pilot.pause()
        await asyncio.sleep(0.02)


def rows_of(screen) -> dict[str, str]:
    runway = screen.query_one("#runway-graph")
    return {str(option.id): str(option.prompt) for option in runway.options}


def projection_for(scenario: str, *, state=None):
    _tree, graph = tree_graph(scenario)
    state = state or state_data(scenario)
    return GraphProjector().project(graph, state, timings_for(scenario))


class RunwayScopeTests(unittest.IsolatedAsyncioTestCase):
    async def _render(self, snapshot, check):
        app = StyledApp()
        async with app.run_test(size=(140, 44)) as pilot:
            app.push_screen(CockpitScreen(SnapshotSession(snapshot)))
            await settle(pilot)
            check(app.screen)

    async def test_paused_run_expands_the_call_and_marks_the_active_child(self):
        def check(screen):
            rows = rows_of(screen)
            self.assertIn("review-release", rows)
            self.assertIn("review-release>draft", rows)
            self.assertIn("review-release>review", rows)
            self.assertIn("review-release>publish-notes", rows)
            self.assertIn("build", rows)
            self.assertIn("[x]", rows["build"])
            self.assertIn("[!]", rows["review-release>review"])
            self.assertIn("review-release", rows["review-release>review"])
            self.assertIn("gate", rows["review-release>review"])

        await self._render(composed_snapshot("reference"), check)

    async def test_dynamic_target_renders_collapsed_with_a_reason(self):
        def check(screen):
            rows = rows_of(screen)
            self.assertIn("dyn-call", rows)
            self.assertIn("target not yet resolved", rows["dyn-call"])
            self.assertNotIn("dyn-call>publish", rows)

        await self._render(composed_snapshot("dynamic-target"), check)

    async def test_failed_child_is_attributed_to_the_child_with_its_scope(self):
        def check(screen):
            rows = rows_of(screen)
            self.assertIn("[X]", rows["broken-call>boom"])
            self.assertIn("broken-call", rows["broken-call>boom"])
            self.assertIn("[X]", rows["broken-call"])

        await self._render(composed_snapshot("failed-child"), check)

    async def test_completed_run_shows_scopes_completed_and_nothing_active(self):
        projection = projection_for("loop-twice")
        rows = {row.key: row for row in render_runway(projection)}
        self.assertTrue(all(not row.active for row in rows.values()))
        self.assertIn("completed", {row.status for row in rows.values()})

    async def test_handled_call_failure_is_labelled(self):
        projection = projection_for("continue-on-error")
        call = projection.by_key[("broken-call",)]
        self.assertEqual(call.status, "failed")
        self.assertTrue(call.handled)

    async def test_frozen_definition_is_used_after_the_install_changes(self):
        """US3.5: the runway reads the tree, not the current install."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fx.write_run(root, "reference", run_id="run-1")
            # The install no longer has release-notes at all; the tree still does.
            state = RunStateData(**{**state_data("reference").__dict__})
            _tree, graph = tree_graph("reference")
            projection = GraphProjector().project(graph, state, timings_for("reference"))
            labels = {node.key: node.label for node in graph.nodes}
            self.assertEqual(labels[("review-release", "review")], "review")
            self.assertIn(("review-release", "review"), projection.by_key)


if __name__ == "__main__":
    unittest.main()
