import tempfile
import unittest
from pathlib import Path

from tests.support import FakeGit, compatibility_result
from workflow_cockpit.bootstrap.discovery import ProjectInfo
from workflow_cockpit.bootstrap.preflight import Preflight, _is_supported_platform


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


class PlatformLabelTests(unittest.TestCase):
    def test_linux_is_supported(self):
        supported, label = _is_supported_platform("linux", "6.8.0-generic")
        self.assertTrue(supported)
        self.assertEqual(label, "Linux")

    def test_wsl_is_supported(self):
        supported, label = _is_supported_platform(
            "linux", "5.15.90.1-microsoft-standard-WSL2"
        )
        self.assertTrue(supported)
        self.assertEqual(label, "WSL")

    def test_macos_is_supported(self):
        supported, label = _is_supported_platform("darwin", "23.5.0")
        self.assertTrue(supported)
        self.assertEqual(label, "macOS")

    def test_native_windows_is_refused_with_guidance(self):
        supported, label = _is_supported_platform("win32", "10")
        self.assertFalse(supported)
        self.assertIn("use Linux, macOS, or WSL", label)


if __name__ == "__main__":
    unittest.main()
