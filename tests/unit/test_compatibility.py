import unittest
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from workflow_cockpit.bootstrap.compatibility import (
    Compatibility,
    CompatibilityError,
    in_supported_range,
    parse_version,
)


class HelpOutput:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


class FakeRunner:
    def __init__(self, version: str = "1.0.0", run_help: str | None = None) -> None:
        self.version = version
        self.run_help = run_help if run_help is not None else "Usage: ... --input -i --json"

    def __call__(self, argv, cwd):
        if argv[-1] == "--version":
            return HelpOutput(f"specify {self.version}")
        if argv[-2:] == ["workflow", "--help"]:
            return HelpOutput("Commands: run resume status list")
        if argv[-3:] == ["workflow", "run", "--help"]:
            return HelpOutput(self.run_help)
        return HelpOutput("", returncode=1)


class ParseVersionTests(unittest.TestCase):
    def test_parses_plain(self):
        self.assertEqual(parse_version("specify 1.2.3"), Version("1.2.3"))

    def test_parses_prerelease(self):
        self.assertEqual(parse_version("specify 1.0.6.dev0"), Version("1.0.6.dev0"))

    def test_returns_none_without_version(self):
        self.assertIsNone(parse_version("no version here"))


class RangeTests(unittest.TestCase):
    def setUp(self):
        self.specifier = SpecifierSet(">=1.0,<2.0")

    def test_includes_release(self):
        self.assertTrue(in_supported_range(Version("1.5.0"), self.specifier))

    def test_accepts_in_range_prerelease(self):
        self.assertTrue(in_supported_range(Version("1.0.6.dev0"), self.specifier))

    def test_refuses_older(self):
        self.assertFalse(in_supported_range(Version("0.16.1"), self.specifier))

    def test_refuses_next_major(self):
        self.assertFalse(in_supported_range(Version("2.0.0"), self.specifier))


class ResolveTests(unittest.TestCase):
    def test_resolve_explicit_missing(self):
        comp = Compatibility(runner=FakeRunner())
        with self.assertRaises(CompatibilityError):
            comp.resolve_executable("/nonexistent/specify")

    def test_check_accepts_supported(self):
        comp = Compatibility(runner=FakeRunner("1.0.6.dev0"))
        result = comp.check(Path("/usr/bin/specify"))
        self.assertTrue(result.prerelease)
        self.assertEqual(result.version, Version("1.0.6.dev0"))

    def test_check_refuses_old(self):
        comp = Compatibility(runner=FakeRunner("0.16.1"))
        with self.assertRaises(CompatibilityError):
            comp.check(Path("/usr/bin/specify"))

    def test_probe_requires_options(self):
        comp = Compatibility(runner=FakeRunner(run_help="Usage: only --input"))
        with self.assertRaises(CompatibilityError):
            comp.probe(Path("/usr/bin/specify"))


if __name__ == "__main__":
    unittest.main()
