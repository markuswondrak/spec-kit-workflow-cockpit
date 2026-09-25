import json
import os
import stat
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from tests.support import (
    FakeGit,
    compatibility_result,
    requires_posix,
    write_registry,
    write_run,
    write_workflow,
)
from workflow_cockpit.bootstrap.compatibility import Compatibility
from workflow_cockpit.engine.supervisor import EngineSupervisor
from workflow_cockpit.session.cockpit_session import CockpitSession, SessionError
from workflow_cockpit.session.dependencies import (
    CockpitEnvironment,
    CockpitServices,
    EngineRuntime,
)

FAKE_SPECIFY = Path(__file__).resolve().parents[1] / "fixtures" / "fake_specify.py"


def wait_for(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@requires_posix
class EngineContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_workflow(self.root)
        write_registry(self.root)
        self.fake = self.root / "fake-specify"
        self.fake.write_text(FAKE_SPECIFY.read_text(), encoding="utf-8")
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IEXEC)

    def tearDown(self):
        self.tmp.cleanup()

    def test_preflight_accepts_fake_engine(self):
        result = Compatibility().resolve_and_check(self.fake)
        self.assertEqual(str(result.version), "1.0.0")

    def test_start_uses_exact_run_id_and_environment(self):
        record = self.root / "record.json"
        supervisor = EngineSupervisor(self.fake, self.root)
        result = replace(compatibility_result(), executable=self.fake)
        env = {
            "COCKPIT_TEST_RECORD": str(record),
            "SPECIFY_INIT_DIR": "/somewhere/wrong",
            "PATH": os.environ.get("PATH", ""),
        }
        with mock.patch.dict(os.environ, env, clear=False):
            environment = CockpitEnvironment(self.root, result)
            services = replace(CockpitServices.for_environment(environment), git=FakeGit())
            session = CockpitSession(
                environment, services=services, engine=EngineRuntime(supervisor=supervisor)
            )
            session.select("demo")
            snapshot = session.start({"spec": "indexed search"})
            self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
            final = session.snapshot()

        payload = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual(payload["run_id"], snapshot.run_id)
        self.assertEqual(payload["argv"][:3], ["workflow", "run", "demo"])
        self.assertIn("spec=indexed search", payload["argv"])
        self.assertEqual(payload["init_dir"], str(self.root))
        self.assertEqual(os.path.realpath(payload["cwd"]), os.path.realpath(self.root))

        run_dir = self.root / ".specify" / "workflows" / "runs" / snapshot.run_id
        self.assertTrue((run_dir / "state.json").is_file())
        self.assertIsNotNone(final.outcome)
        self.assertEqual(final.outcome.kind.value, "success")


    def test_interactive_gate_receives_one_mapped_input(self):
        workflow = {
            "schema_version": "1.0",
            "workflow": {"id": "demo", "name": "Demo", "version": "1.0.0", "description": "demo"},
            "inputs": {"spec": {"type": "string", "required": True}},
            "steps": [
                {"id": "prepare", "command": "demo.prepare"},
                {
                    "id": "review",
                    "type": "gate",
                    "message": "Review required.",
                    "options": ["approve", "reject"],
                    "on_reject": "skip",
                },
                {"id": "finish", "command": "demo.finish"},
            ],
        }
        write_workflow(self.root, workflow)
        received = self.root / "interactive-input.json"
        supervisor = EngineSupervisor(self.fake, self.root)
        result = replace(compatibility_result("1.0.6"), executable=self.fake)
        env = {
            "COCKPIT_TEST_INTERACTIVE_GATE": "review",
            "COCKPIT_TEST_INTERACTIVE_OPTIONS": "approve,reject",
            "COCKPIT_TEST_INTERACTIVE_EXPECT": "approve",
            "COCKPIT_TEST_INTERACTIVE_INPUT": str(received),
            "PATH": os.environ.get("PATH", ""),
        }
        with mock.patch.dict(os.environ, env, clear=False):
            environment = CockpitEnvironment(self.root, result)
            services = replace(CockpitServices.for_environment(environment), git=FakeGit())
            session = CockpitSession(
                environment, services=services, engine=EngineRuntime(supervisor=supervisor)
            )
            session.select("demo")
            session.start({"spec": "indexed search"})
            self.assertTrue(
                wait_for(
                    lambda: (snapshot := session.snapshot()).gate is not None
                    and snapshot.gate.selectable
                    and snapshot.process_live
                )
            )
            gate = session.snapshot().gate
            session.submit_decision("approve", gate.token)
            # A second confirmation must not reach the PTY.
            with self.assertRaises(SessionError):
                session.submit_decision("reject", gate.token)
            self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
            final = session.snapshot()

        self.assertEqual(json.loads(received.read_text()), ["1\n"])
        self.assertEqual(final.outcome.kind.value, "success")
        self.assertEqual(final.engine_status, "completed")

    def test_adopt_paused_run_and_submit_one_structured_decision(self):
        import yaml

        from tests.support import LINEAR_WORKFLOW

        run_id = "paused-run"
        run_dir = write_run(
            self.root,
            run_id,
            status="paused",
            current_step_id="review",
            step_results={
                "review": {
                    "type": "gate",
                    "output": {
                        "message": "Review it",
                        "options": ["approve", "reject"],
                        "on_reject": "retry",
                    },
                }
            },
        )
        (run_dir / "workflow.yml").write_text(
            yaml.safe_dump(LINEAR_WORKFLOW, sort_keys=False), encoding="utf-8"
        )

        record = self.root / "adopt-resume-record.json"
        supervisor = EngineSupervisor(self.fake, self.root)
        result = replace(compatibility_result("1.0.6"), executable=self.fake)
        env = {"COCKPIT_TEST_RECORD": str(record), "PATH": os.environ.get("PATH", "")}
        with mock.patch.dict(os.environ, env, clear=False):
            environment = CockpitEnvironment(self.root, result)
            services = replace(CockpitServices.for_environment(environment), git=FakeGit())
            session = CockpitSession(
                environment,
                services=services,
                engine=EngineRuntime(supervisor=supervisor, clock=time.monotonic),
            )
            snapshot = session.adopt(run_id)
            self.assertEqual(snapshot.run_id, run_id)
            self.assertTrue(snapshot.adopted)
            self.assertIsNone(supervisor.started_at)
            gate = session.snapshot().gate
            self.assertTrue(gate.selectable)
            session.submit_decision("approve", gate.token)
            self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
            final = session.snapshot()

        payload = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual(payload["argv"][:3], ["workflow", "resume", run_id])
        self.assertIn("review_verdict=approve", payload["argv"])
        self.assertIn("--json", payload["argv"])
        self.assertEqual(final.outcome.kind.value, "success")
        self.assertEqual(final.engine_status, "completed")

    def test_adopt_failed_run_and_resume_once(self):
        import yaml

        from tests.support import LINEAR_WORKFLOW

        run_id = "failed-run"
        run_dir = write_run(self.root, run_id, status="failed", current_step_id="review")
        (run_dir / "workflow.yml").write_text(
            yaml.safe_dump(LINEAR_WORKFLOW, sort_keys=False), encoding="utf-8"
        )

        record = self.root / "failed-resume-record.json"
        supervisor = EngineSupervisor(self.fake, self.root)
        result = replace(compatibility_result("1.0.6"), executable=self.fake)
        env = {"COCKPIT_TEST_RECORD": str(record), "PATH": os.environ.get("PATH", "")}
        with mock.patch.dict(os.environ, env, clear=False):
            environment = CockpitEnvironment(self.root, result)
            services = replace(CockpitServices.for_environment(environment), git=FakeGit())
            session = CockpitSession(
                environment,
                services=services,
                engine=EngineRuntime(supervisor=supervisor, clock=time.monotonic),
            )
            snapshot = session.adopt(run_id)
            self.assertEqual(snapshot.engine_status, "failed")
            self.assertIsNone(supervisor.started_at)
            decision = session.resume_decision()
            self.assertTrue(decision.available)
            session.resume_run(decision.token)
            self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
            final = session.snapshot()

        payload = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual(payload["argv"][:3], ["workflow", "resume", run_id])
        self.assertNotIn("-i", payload["argv"])
        self.assertEqual(payload["run_id"], run_id)
        self.assertEqual(final.engine_status, "completed")

    def test_structured_resume_uses_exact_argv(self):
        record = self.root / "resume-record.json"
        supervisor = EngineSupervisor(self.fake, self.root)
        result = replace(compatibility_result(), executable=self.fake)
        env = {
            "COCKPIT_TEST_RECORD": str(record),
            "PATH": os.environ.get("PATH", ""),
        }
        with mock.patch.dict(os.environ, env, clear=False):
            environment = CockpitEnvironment(self.root, result)
            services = replace(CockpitServices.for_environment(environment), git=FakeGit())
            session = CockpitSession(
                environment, services=services, engine=EngineRuntime(supervisor=supervisor)
            )
            session.select("demo")
            started = session.start({"spec": "indexed search"})
            self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
            write_run(
                self.root,
                started.run_id,
                status="paused",
                current_step_id="review",
                step_results={
                    "review": {
                        "type": "gate",
                        "output": {
                            "message": "Review it",
                            "options": ["approve", "reject"],
                            "on_reject": "retry",
                        },
                    }
                },
            )
            gate = session.snapshot().gate
            self.assertTrue(gate.selectable)
            session.submit_decision("approve", gate.token)
            self.assertTrue(wait_for(lambda: supervisor.condition().reaped))
            final = session.snapshot()

        payload = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual(payload["argv"][:3], ["workflow", "resume", started.run_id])
        self.assertIn("review_verdict=approve", payload["argv"])
        self.assertIn("--json", payload["argv"])
        self.assertEqual(payload["run_id"], started.run_id)
        self.assertEqual(payload["init_dir"], str(self.root))
        self.assertEqual(final.engine_status, "completed")


if __name__ == "__main__":
    unittest.main()
