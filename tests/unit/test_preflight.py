import tempfile
import unittest
from pathlib import Path

from tests.support import FakeGit, compatibility_result
from workflow_cockpit.bootstrap.discovery import ProjectInfo
from workflow_cockpit.bootstrap.preflight import Preflight


class FakeCompatibility:
    tested_range = ">=1.0,<2.0"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def resolve_executable(self, explicit=None):
        if self.fail:
            from workflow_cockpit.bootstrap.compatibility import CompatibilityError

            raise CompatibilityError("no specify")
        return Path("/usr/bin/specify")

    def check(self, executable):
        return compatibility_result()

    def probe(self, executable):
        return None


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify").mkdir()
        self.project = ProjectInfo(root=self.root.resolve(), specify_dir=self.root.resolve() / ".specify")

    def tearDown(self):
        self.tmp.cleanup()

    def test_passes_with_compatible_environment(self):
        report = Preflight(self.project, FakeCompatibility(), FakeGit()).run()
        self.assertTrue(report.ok)
        self.assertIsNotNone(report.compatibility)

    def test_fails_without_head(self):
        git = FakeGit(head_value=None, branch_value=None)
        report = Preflight(self.project, FakeCompatibility(), git).run()
        self.assertFalse(report.ok)
        failing = {check.key for check in report.failures}
        self.assertIn("git", failing)

    def test_fails_without_executable(self):
        report = Preflight(self.project, FakeCompatibility(fail=True), FakeGit()).run()
        self.assertFalse(report.ok)
        check = next(c for c in report.checks if c.key == "specify")
        self.assertTrue(check.repair)


if __name__ == "__main__":
    unittest.main()
