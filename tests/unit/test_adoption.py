import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.support import FakeGit, FakeReviewService, FakeSupervisor, compatibility_result, write_run
from tests.unit.test_run_catalog import write_launch_copy
from workflow_cockpit.engine.supervisor import StdinPolicy
from workflow_cockpit.services.graph import WorkflowDefinitionParser
from workflow_cockpit.services.run_claim import OwnershipClaim, RunClaimStore
from workflow_cockpit.services.snapshot import GateState
from workflow_cockpit.session.adoption import AdoptError, RunAdopter
from workflow_cockpit.session.cockpit_session import CockpitSession, SessionError
from workflow_cockpit.session.dependencies import (
    CockpitEnvironment,
    CockpitServices,
    EngineRuntime,
)

ADOPT_WORKFLOW = {
    "schema_version": "1.0",
    "workflow": {"id": "demo", "name": "Demo Workflow", "version": "1.0.0"},
    "inputs": {"spec": {"type": "string", "required": True}},
    "steps": [
        {"id": "prepare", "command": "demo.prepare"},
        {
            "id": "review",
            "type": "gate",
            "message": "Review it",
            "options": ["approve", "reject"],
            "verdict_input": "review_verdict",
        },
        {"id": "finish", "command": "demo.finish"},
    ],
}


NON_VERDICT_ADOPT_WORKFLOW = {
    "schema_version": "1.0",
    "workflow": {"id": "demo", "name": "Demo Workflow", "version": "1.0.0"},
    "inputs": {"spec": {"type": "string", "required": True}},
    "steps": [
        {"id": "prepare", "command": "demo.prepare"},
        {
            "id": "review",
            "type": "gate",
            "message": "Review it",
            "options": ["approve", "reject"],
            "on_reject": "skip",
        },
        {"id": "finish", "command": "demo.finish"},
    ],
}


class AdoptionUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify" / "workflows" / "runs").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def seed(self, run_id, status="paused"):
        write_run(self.root, run_id, status=status, current_step_id="review")
        write_launch_copy(self.root, run_id, ADOPT_WORKFLOW)
        return run_id

    def make_adopter(self):
        claims = RunClaimStore(self.root, host="test-host")
        return RunAdopter(self.root, claims=claims), claims

    def test_prepare_builds_definition_from_launch_copy(self):
        run_id = self.seed("run-1")
        adopter, _ = self.make_adopter()
        binding = adopter.prepare(run_id, "owner-1")
        self.assertEqual(binding.run_id, run_id)
        self.assertEqual(binding.definition.id, "demo")
        graph = WorkflowDefinitionParser().parse(binding.definition.effective_steps)
        review = graph.by_id["review"]
        self.assertTrue(review.gate)
        self.assertEqual(review.verdict_input, "review_verdict")
        self.assertEqual(graph.declared_ids, frozenset({"prepare", "review", "finish"}))

    def test_prepare_acquires_the_claim(self):
        run_id = self.seed("run-1")
        adopter, claims = self.make_adopter()
        binding = adopter.prepare(run_id, "owner-1")
        self.assertEqual(claims.claim_state(run_id, "owner-1").value, "owned")
        self.assertEqual(binding.claim.owner_id, "owner-1")

    def test_terminal_run_is_refused(self):
        run_id = self.seed("run-done", "completed")
        adopter, _ = self.make_adopter()
        with self.assertRaisesRegex(AdoptError, "paused"):
            adopter.prepare(run_id, "owner-1")

    def test_running_run_is_refused(self):
        run_id = self.seed("run-live", "running")
        adopter, _ = self.make_adopter()
        with self.assertRaises(AdoptError):
            adopter.prepare(run_id, "owner-1")

    def test_prepare_inspect_succeeds_without_claim(self):
        run_id = self.seed("run-live", "running")
        adopter, claims = self.make_adopter()
        descriptor, definition = adopter.prepare_inspect(run_id)
        self.assertEqual(descriptor.run_id, run_id)
        self.assertEqual(descriptor.status, "running")
        self.assertTrue(descriptor.viewable)
        self.assertFalse(descriptor.adoptable)
        self.assertEqual(definition.id, "demo")
        # Assert no claim was written to disk
        self.assertIsNone(claims.read(run_id))

    def test_stale_claim_from_a_crash_is_recovered(self):
        run_id = self.seed("run-1")
        claims = RunClaimStore(
            self.root,
            host="test-host",
            pid_alive=lambda pid: False,
            start_time=lambda pid: "100",
        )
        claims.acquire(
            run_id,
            OwnershipClaim(
                run_id=run_id,
                owner_id="crashed",
                host="test-host",
                pid=4321,
                pgid=4321,
                process_start="100",
                created_at="2026-09-18T00:00:00+00:00",
            ),
        )
        adopter = RunAdopter(self.root, claims=claims)
        binding = adopter.prepare(run_id, "owner-2")
        self.assertEqual(binding.claim.owner_id, "owner-2")
        self.assertEqual(claims.read(run_id).owner_id, "owner-2")

    def test_live_foreign_claim_is_refused(self):
        run_id = self.seed("run-1")
        claims = RunClaimStore(
            self.root,
            host="test-host",
            pid_alive=lambda pid: True,
            start_time=lambda pid: "100",
        )
        claims.acquire(
            run_id,
            OwnershipClaim(
                run_id=run_id,
                owner_id="other",
                host="test-host",
                pid=4321,
                pgid=4321,
                process_start="100",
                created_at="2026-09-18T00:00:00+00:00",
            ),
        )
        adopter = RunAdopter(self.root, claims=claims)
        with self.assertRaisesRegex(AdoptError, "live Cockpit"):
            adopter.prepare(run_id, "owner-1")


class AdoptSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify" / "workflows" / "runs").mkdir(parents=True)
        self.supervisor = FakeSupervisor()

    def tearDown(self):
        self.tmp.cleanup()

    def seed(self, run_id, status="paused", workflow=None, step_results=None):
        if step_results is None:
            step_results = {
                "review": {
                    "type": "gate",
                    "output": {
                        "message": "Review it",
                        "options": ["approve", "reject"],
                        "on_reject": "retry",
                    },
                }
            }
        write_run(
            self.root,
            run_id,
            status=status,
            current_step_id="review",
            step_results=step_results,
        )
        write_launch_copy(self.root, run_id, workflow or ADOPT_WORKFLOW)
        return run_id

    def make_session(self):
        environment = CockpitEnvironment(self.root, compatibility_result("1.0.6"))
        services = replace(
            CockpitServices.for_environment(environment),
            git=FakeGit(),
            review_source=FakeReviewService(),
        )
        engine = replace(
            EngineRuntime.for_environment(environment, clock=lambda: 10.0),
            supervisor=self.supervisor,
        )
        return CockpitSession(environment, services=services, engine=engine)

    def test_adopt_spawns_nothing_and_marks_adopted(self):
        run_id = self.seed("run-1")
        session = self.make_session()
        snapshot = session.adopt(run_id)
        self.assertTrue(session.adopted)
        self.assertTrue(snapshot.adopted)
        self.assertEqual(snapshot.run_id, run_id)
        self.assertEqual(snapshot.status, "paused")
        self.assertIsNone(self.supervisor.started_argv)
        self.assertEqual(self.supervisor.resume_calls, [])
        self.assertIsNone(self.supervisor.started_at)

    def test_adopt_refreshes_context_index(self):
        run_id = self.seed("run-1")
        session = self.make_session()
        snapshot = session.adopt(run_id)
        self.assertEqual(snapshot.context_path, ".specify/workflows/runs/current_run")
        index = self.root / ".specify" / "workflows" / "runs" / "current_run"
        self.assertIn(f"- Run ID: `{run_id}`", index.read_text(encoding="utf-8"))

    def test_adopt_then_second_run_rejected(self):
        run_id = self.seed("run-1")
        session = self.make_session()
        session.adopt(run_id)
        with self.assertRaises(SessionError):
            session.adopt(run_id)

    def test_adopt_terminal_run_is_refused_without_write(self):
        run_id = self.seed("run-done", "completed")
        session = self.make_session()
        with self.assertRaisesRegex(SessionError, "paused"):
            session.adopt(run_id)
        self.assertIsNone(self.supervisor.started_argv)
        self.assertFalse(session.adopted)

    def test_adopted_structured_gate_submits_exactly_one_resume(self):
        run_id = self.seed("run-1")
        session = self.make_session()
        session.adopt(run_id)
        gate = session.snapshot().gate
        self.assertEqual(gate.state, GateState.READY)
        session.submit_decision("approve", gate.token)
        self.assertEqual(len(self.supervisor.resume_calls), 1)
        _run_id, argv = self.supervisor.resume_calls[-1]
        self.assertEqual(argv[1:4], ["workflow", "resume", run_id])
        self.assertIn("review_verdict=approve", argv)
        self.assertIn("--json", argv)
        self.assertEqual(self.supervisor.writes, [])

    def test_adopted_interactive_gate_spawns_once_and_writes_once(self):
        run_id = self.seed("run-2", workflow=NON_VERDICT_ADOPT_WORKFLOW)
        session = self.make_session()
        session.adopt(run_id)
        gate = session.snapshot().gate
        self.assertEqual(gate.state, GateState.READY)
        self.assertEqual(self.supervisor.resume_calls, [])
        session.submit_decision("approve", gate.token)
        self.assertEqual(len(self.supervisor.resume_calls), 1)
        self.assertIs(self.supervisor.resume_stdin[-1], StdinPolicy.PTY)
        self.assertEqual(self.supervisor.writes, [b"1\n"])

    def test_adopted_terminal_state_yields_outcome_without_process(self):
        run_id = self.seed("run-3")
        session = self.make_session()
        session.adopt(run_id)
        write_run(self.root, run_id, status="completed", current_step_id="finish")
        final = session.snapshot()
        self.assertIsNotNone(final.outcome)
        self.assertEqual(final.outcome.kind.value, "success")
        self.assertFalse(final.process_live)

    def test_adopted_abort_sends_no_signal(self):
        run_id = self.seed("run-4")
        session = self.make_session()
        session.adopt(run_id)
        session.abort()
        result = session.last_abort_result
        self.assertFalse(result.signalled)
        self.assertEqual(self.supervisor.abort_calls, 1)


if __name__ == "__main__":
    unittest.main()
