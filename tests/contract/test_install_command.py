"""Contract tests for ``workflow-cockpit install``."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from workflow_cockpit.cli import main


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class InstallCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def declare(self, integration: str) -> None:
        (self.root / ".specify" / "integration.json").write_text(
            json.dumps({"default_integration": integration}), encoding="utf-8"
        )

    def test_install_reports_one_line_per_artifact_and_exits_zero(self):
        self.declare("claude")
        code, out, _err = run_cli("--project", str(self.root), "install")
        self.assertEqual(code, 0)
        self.assertEqual(
            out.strip(),
            "installed .claude/skills/cockpit-run-context/SKILL.md",
        )
        self.assertTrue(
            (self.root / ".claude" / "skills" / "cockpit-run-context" / "SKILL.md").is_file()
        )

    def test_second_install_skips_the_user_editable_skill(self):
        self.declare("claude")
        run_cli("--project", str(self.root), "install")
        code, out, _err = run_cli("--project", str(self.root), "install")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("skipped_present "))

    def test_per_artifact_failure_still_exits_zero(self):
        self.declare("claude")
        (self.root / ".claude").write_text("blocks the directory", encoding="utf-8")
        code, out, _err = run_cli("--project", str(self.root), "install")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("failed "))

    def test_unknown_integration_uses_the_open_standard_fallback(self):
        self.declare("mystery")
        code, out, _err = run_cli("--project", str(self.root), "install")
        self.assertEqual(code, 0)
        self.assertIn(".agents/skills/cockpit-run-context/SKILL.md", out)

    def test_no_project_exits_two(self):
        empty = Path(tempfile.mkdtemp())
        code, _out, err = run_cli("--project", str(empty), "install")
        self.assertEqual(code, 2)
        self.assertIn("not an initialized Spec Kit project", err)


if __name__ == "__main__":
    unittest.main()
