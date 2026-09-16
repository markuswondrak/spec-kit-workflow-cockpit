import json
import tempfile
import unittest
from pathlib import Path

from workflow_cockpit.services.skill_install import (
    FAILED,
    INSTALLED,
    SKIPPED,
    SkillInstaller,
)

SKILL_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "workflow_cockpit"
    / "skills"
    / "cockpit-run-context"
    / "SKILL.md"
)


class SkillInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.specify = self.root / ".specify"
        self.specify.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def declare(self, integration: str | None):
        if integration is None:
            return
        (self.specify / "integration.json").write_text(
            json.dumps({"default_integration": integration}), encoding="utf-8"
        )

    def installed_path(self, relative: str) -> Path:
        return self.root / relative / "cockpit-run-context" / "SKILL.md"

    def test_installs_into_matching_integration_directory(self):
        cases = {
            "claude": ".claude/skills",
            "claude code": ".claude/skills",
            "github-copilot": ".github/skills",
            "copilot": ".github/skills",
            "opencode": ".opencode/skills",
        }
        for integration, relative in cases.items():
            with self.subTest(integration=integration), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                specify = root / ".specify"
                specify.mkdir()
                (specify / "integration.json").write_text(
                    json.dumps({"default_integration": integration}), encoding="utf-8"
                )
                result = SkillInstaller(root).install()
                self.assertEqual(result.action, INSTALLED)
                self.assertEqual(result.integration, integration)
                self.assertEqual(result.relative, f"{relative}/cockpit-run-context")
                self.assertTrue((root / relative / "cockpit-run-context" / "SKILL.md").is_file())

    def test_unknown_or_absent_integration_uses_open_standard(self):
        for integration in (None, "gemini"):
            with self.subTest(integration=integration), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                specify = root / ".specify"
                specify.mkdir()
                if integration is not None:
                    (specify / "integration.json").write_text(
                        json.dumps({"default_integration": integration}), encoding="utf-8"
                    )
                result = SkillInstaller(root).install()
                self.assertEqual(result.action, INSTALLED)
                self.assertTrue((root / ".agents" / "skills" / "cockpit-run-context" / "SKILL.md").is_file())

    def test_malformed_integration_file_falls_back_non_fatally(self):
        (self.specify / "integration.json").write_text("}{", encoding="utf-8")
        result = SkillInstaller(self.root).install()
        self.assertEqual(result.action, INSTALLED)
        self.assertTrue(self.installed_path(".agents/skills").is_file())

    def test_installed_content_matches_shipped_skill(self):
        self.declare("claude")
        SkillInstaller(self.root).install()
        self.assertEqual(
            self.installed_path(".claude/skills").read_text(encoding="utf-8"),
            SKILL_SOURCE.read_text(encoding="utf-8"),
        )

    def test_existing_skill_directory_is_left_untouched(self):
        self.declare("claude")
        target = self.installed_path(".claude/skills")
        target.parent.mkdir(parents=True)
        target.write_text("user edit", encoding="utf-8")
        result = SkillInstaller(self.root).install()
        self.assertEqual(result.action, SKIPPED)
        self.assertEqual(target.read_text(encoding="utf-8"), "user edit")

    def test_uninitialized_project_is_skipped(self):
        project = Path(tempfile.mkdtemp())
        result = SkillInstaller(project).install()
        self.assertEqual(result.action, SKIPPED)
        self.assertFalse((project / ".agents").exists())

    def test_write_failure_is_reported_not_raised(self):
        self.declare("claude")
        (self.root / ".claude").write_text("blocks the directory", encoding="utf-8")
        result = SkillInstaller(self.root).install()
        self.assertEqual(result.action, FAILED)
        self.assertFalse(result.ok)

    def test_no_temp_files_remain(self):
        self.declare("opencode")
        SkillInstaller(self.root).install()
        base = self.root / ".opencode" / "skills" / "cockpit-run-context"
        leftovers = [path for path in base.iterdir() if path.name.startswith(".SKILL-")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
