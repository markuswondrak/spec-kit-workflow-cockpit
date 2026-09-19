"""The release script computes the next version and rejects bad input."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from tests.support import requires_posix
from workflow_cockpit import __version__

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release.sh"


def next_version(kind: str) -> str:
    """Return the version the script should produce for ``kind``."""
    major, minor, patch = (int(part) for part in __version__.split("."))
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    if kind == "patch":
        return f"{major}.{minor}.{patch + 1}"
    return __version__


@requires_posix
class ReleaseScriptTests(unittest.TestCase):
    def dry_run(self, *args: str) -> str:
        result = subprocess.run(
            [str(SCRIPT), *args, "--dry-run"],
            check=True,
            text=True,
            capture_output=True,
            cwd=ROOT,
        )
        return result.stdout

    def test_default_is_a_minor_bump(self):
        self.assertIn(f"{__version__} -> {next_version('minor')}", self.dry_run())

    def test_each_bump_kind(self):
        for kind in ("major", "minor", "patch", "current"):
            self.assertIn(f"{__version__} -> {next_version(kind)}", self.dry_run(kind), kind)

    def test_unknown_argument_is_rejected(self):
        result = subprocess.run([str(SCRIPT), "bogus"], text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown argument", result.stderr)


if __name__ == "__main__":
    unittest.main()
