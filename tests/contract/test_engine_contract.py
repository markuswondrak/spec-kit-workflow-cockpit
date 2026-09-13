import json
import os
import stat
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from tests.support import FakeGit, compatibility_result, write_registry, write_workflow
from workflow_cockpit.bootstrap.compatibility import Compatibility
from workflow_cockpit.engine.supervisor import EngineSupervisor
from workflow_cockpit.services.definition import WorkflowDefinitionResolver
from workflow_cockpit.services.registry import WorkflowRegistry
from workflow_cockpit.session.cockpit_session import CockpitSession

FAKE_SPECIFY = Path(__file__).resolve().parents[1] / "fixtures" / "fake_specify.py"


def wait_for(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


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
            session = CockpitSession(
                self.root,
                result,
                registry=WorkflowRegistry(self.root),
                resolver=WorkflowDefinitionResolver(self.root),
                git=FakeGit(),
                supervisor=supervisor,
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


if __name__ == "__main__":
    unittest.main()
