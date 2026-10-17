"""A composed run flows through the session: graph, gate, timings, attempts."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.composition_support import write_project
from tests.fixtures import composition as fx
from tests.support import FakeGit, FakeReviewService, FakeSupervisor, compatibility_result
from workflow_cockpit.services.snapshot import GateState
from workflow_cockpit.session.cockpit_session import CockpitSession
from workflow_cockpit.session.dependencies import (
    CockpitEnvironment,
    CockpitServices,
    EngineRuntime,
)


class ComposedSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make_session(self) -> CockpitSession:
        environment = CockpitEnvironment(self.root, compatibility_result("1.1.3"))
        services = replace(
            CockpitServices.for_environment(environment),
            git=FakeGit(),
            review_source=FakeReviewService(),
        )
        engine = replace(
            EngineRuntime.for_environment(environment, clock=lambda: 10.0),
            supervisor=FakeSupervisor(),
        )
        return CockpitSession(environment, services=services, engine=engine)

    def snapshot(self, scenario: str, *, adopt: bool = False):
        write_project(self.root, scenario)
        fx.write_run(self.root, scenario, run_id="run-1")
        session = self.make_session()
        return session, (session.adopt("run-1") if adopt else session.inspect("run-1"))

    def test_adopted_collision_run_shows_the_child_gate_with_its_scope(self):
        _session, snapshot = self.snapshot("collision", adopt=True)
        gate = snapshot.gate
        self.assertEqual(gate.state, GateState.READY)
        self.assertEqual(gate.display_scope_path, "review-release > review")
        self.assertEqual(gate.root_input, "approval")

    def test_gate_attempt_counts_the_active_scope_only(self):
        # The root ``review`` ran twice; the active child ``review`` once.
        session, _snapshot = self.snapshot("collision", adopt=True)
        state = session._reader.read()
        self.assertEqual(session._composition.gate_attempt(state, "run-1"), 1)

    def test_loop_iteration_gate_attempt_is_scoped_to_its_occurrence(self):
        session, snapshot = self.snapshot("loop-paused", adopt=True)
        self.assertEqual(snapshot.gate.state, GateState.READY)
        state = session._reader.read()
        self.assertEqual(session._composition.gate_attempt(state, "run-1"), 1)

    def test_scoped_timings_reach_the_projected_nodes(self):
        _session, snapshot = self.snapshot("collision")
        projection = snapshot.graph_projection
        self.assertEqual(projection.by_key[("review",)].attempts, 2)
        self.assertEqual(projection.by_key[("review-release", "review")].attempts, 1)

    def test_composed_graph_comes_from_the_frozen_tree(self):
        _session, snapshot = self.snapshot("reference")
        keys = {node.key for node in snapshot.graph_projection.graph.nodes}
        self.assertIn(("review-release", "review"), keys)
        self.assertEqual(snapshot.graph_projection.next_node.key, ("review-release", "publish-notes"))


if __name__ == "__main__":
    unittest.main()
