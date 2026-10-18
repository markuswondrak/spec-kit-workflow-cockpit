"""The shared integration installer: policies, versions, atomicity, non-fatality."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from workflow_cockpit.services import integration_installer as installer_module
from workflow_cockpit.services.integration_installer import (
    FAILED,
    INSTALLED,
    MANAGED,
    SKIPPED_CURRENT,
    SKIPPED_PRESENT,
    SKIPPED_UNREGISTERED,
    UPDATED,
    USER_EDITABLE,
    Artifact,
    FileSource,
    IntegrationInstaller,
)

SKILL_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "workflow_cockpit"
    / "skills"
    / "cockpit-run-context"
    / "SKILL.md"
)


def artifact(name: str, policy: str, source: Path, relative: str, version: str = "") -> Artifact:
    return Artifact(
        name=name,
        policy=policy,
        source=FileSource(source),
        relative_path=relative,
        version=version,
    )


class IntegrationInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify").mkdir(parents=True, exist_ok=True)
        self.source = self.root / "packaged.md"
        self.source.write_text("packaged body\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def declare(self, integration: str | None, *, key: str = "default_integration") -> None:
        if integration is None:
            return
        (self.root / ".specify" / "integration.json").write_text(
            json.dumps({key: integration}), encoding="utf-8"
        )

    def installer(self, targets, *, fallback=()) -> IntegrationInstaller:
        return IntegrationInstaller(self.root, targets=targets, fallback=fallback)

    # -- policies -------------------------------------------------------

    def test_absent_user_editable_is_installed(self):
        self.declare("demo")
        targets = {"demo": (artifact("skill", USER_EDITABLE, self.source, ".demo/skill.md"),)}
        report = self.installer(targets).install()
        self.assertEqual([o.outcome for o in report.outcomes], [INSTALLED])
        self.assertEqual((self.root / ".demo" / "skill.md").read_text(), "packaged body\n")

    def test_present_user_editable_is_never_overwritten(self):
        self.declare("demo")
        target = self.root / ".demo" / "skill.md"
        target.parent.mkdir(parents=True)
        target.write_text("user edit", encoding="utf-8")
        targets = {"demo": (artifact("skill", USER_EDITABLE, self.source, ".demo/skill.md"),)}
        report = self.installer(targets).install()
        self.assertEqual([o.outcome for o in report.outcomes], [SKIPPED_PRESENT])
        self.assertEqual(target.read_text(encoding="utf-8"), "user edit")

    def test_outdated_managed_artifact_is_updated_atomically(self):
        self.declare("demo")
        target = self.root / ".demo" / "widget.md"
        target.parent.mkdir(parents=True)
        target.write_text(
            "<!-- workflow-cockpit-artifact: widget 1 -->\nold\n", encoding="utf-8"
        )
        targets = {"demo": (artifact("widget", MANAGED, self.source, ".demo/widget.md", "2"),)}
        replaced: list[tuple[str, str]] = []
        original = installer_module.os.replace

        def recorder(src, dst):
            replaced.append((str(src), str(dst)))
            return original(src, dst)

        installer_module.os.replace = recorder
        try:
            report = self.installer(targets).install()
        finally:
            installer_module.os.replace = original
        self.assertEqual([o.outcome for o in report.outcomes], [UPDATED])
        self.assertTrue(replaced, "the managed write must move a temp file into place")
        content = target.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("<!-- workflow-cockpit-artifact: widget 2 -->"))
        self.assertIn("packaged body", content)
        leftovers = [p.name for p in target.parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_current_managed_artifact_is_skipped(self):
        self.declare("demo")
        target = self.root / ".demo" / "widget.md"
        target.parent.mkdir(parents=True)
        target.write_text(
            "<!-- workflow-cockpit-artifact: widget 2 -->\npackaged body\n", encoding="utf-8"
        )
        targets = {"demo": (artifact("widget", MANAGED, self.source, ".demo/widget.md", "2"),)}
        report = self.installer(targets).install()
        self.assertEqual([o.outcome for o in report.outcomes], [SKIPPED_CURRENT])

    def test_unregistered_integration_is_reported_not_failed(self):
        self.declare("gemini")
        targets = {"demo": (artifact("widget", MANAGED, self.source, ".demo/widget.md", "1"),)}
        report = self.installer(targets).install()
        self.assertTrue(report.ok)
        self.assertEqual([o.outcome for o in report.outcomes], [SKIPPED_UNREGISTERED])

    def test_one_failure_does_not_stop_the_other_artifacts(self):
        self.declare("demo")
        (self.root / ".demo").write_text("blocks the directory", encoding="utf-8")
        targets = {
            "demo": (
                artifact("blocked", USER_EDITABLE, self.source, ".demo/widget.md"),
                artifact("fine", USER_EDITABLE, self.source, ".other/widget.md"),
            )
        }
        report = self.installer(targets).install()
        self.assertEqual([o.outcome for o in report.outcomes], [FAILED, INSTALLED])
        self.assertTrue((self.root / ".other" / "widget.md").is_file())

    def test_install_never_raises(self):
        self.declare("demo")
        targets = {
            "demo": (
                Artifact(
                    name="broken",
                    policy=USER_EDITABLE,
                    source=FileSource(self.root / "missing-source"),
                    relative_path=".demo/x.md",
                ),
            )
        }
        report = self.installer(targets).install()
        self.assertEqual([o.outcome for o in report.outcomes], [FAILED])
        self.assertFalse(report.failures == ())

    def test_report_lines_are_outcome_path_reason(self):
        self.declare("demo")
        targets = {"demo": (artifact("skill", USER_EDITABLE, self.source, ".demo/skill.md"),)}
        lines = self.installer(targets).install().lines()
        self.assertEqual(lines, (f"{INSTALLED} .demo/skill.md",))

    # -- integration key ------------------------------------------------

    def test_bare_integration_key_is_honoured(self):
        self.declare("demo", key="integration")
        targets = {"demo": (artifact("skill", USER_EDITABLE, self.source, ".demo/skill.md"),)}
        report = self.installer(targets).install()
        self.assertEqual(report.integration, "demo")
        self.assertEqual([o.outcome for o in report.outcomes], [INSTALLED])


class SkillTargetTests(unittest.TestCase):
    """The shipped skill target keeps its previous behavior through the installer."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def declare(self, integration: str | None) -> None:
        if integration is None:
            return
        (self.root / ".specify" / "integration.json").write_text(
            json.dumps({"default_integration": integration}), encoding="utf-8"
        )

    def install(self):
        return IntegrationInstaller(self.root).install()

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
                (root / ".specify").mkdir()
                (root / ".specify" / "integration.json").write_text(
                    json.dumps({"default_integration": integration}), encoding="utf-8"
                )
                report = IntegrationInstaller(root).install()
                self.assertEqual([o.outcome for o in report.outcomes], [INSTALLED])
                self.assertEqual(
                    report.outcomes[0].relative, f"{relative}/cockpit-run-context/SKILL.md"
                )
                self.assertTrue((root / relative / "cockpit-run-context" / "SKILL.md").is_file())

    def test_unknown_or_absent_integration_uses_open_standard(self):
        for integration in (None, "gemini"):
            with self.subTest(integration=integration), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / ".specify").mkdir()
                if integration is not None:
                    (root / ".specify" / "integration.json").write_text(
                        json.dumps({"default_integration": integration}), encoding="utf-8"
                    )
                report = IntegrationInstaller(root).install()
                self.assertEqual([o.outcome for o in report.outcomes], [INSTALLED])
                self.assertTrue(
                    (root / ".agents" / "skills" / "cockpit-run-context" / "SKILL.md").is_file()
                )

    def test_malformed_integration_file_falls_back_non_fatally(self):
        (self.root / ".specify" / "integration.json").write_text("}{", encoding="utf-8")
        report = self.install()
        self.assertEqual([o.outcome for o in report.outcomes], [INSTALLED])
        self.assertTrue(
            (self.root / ".agents" / "skills" / "cockpit-run-context" / "SKILL.md").is_file()
        )

    def test_installed_content_matches_the_shipped_skill_byte_for_byte(self):
        self.declare("claude")
        self.install()
        installed = self.root / ".claude" / "skills" / "cockpit-run-context" / "SKILL.md"
        self.assertEqual(installed.read_text(encoding="utf-8"), SKILL_SOURCE.read_text(encoding="utf-8"))

    def test_existing_skill_is_left_untouched(self):
        self.declare("claude")
        target = self.root / ".claude" / "skills" / "cockpit-run-context" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("user edit", encoding="utf-8")
        report = self.install()
        self.assertEqual([o.outcome for o in report.outcomes], [SKIPPED_PRESENT])
        self.assertEqual(target.read_text(encoding="utf-8"), "user edit")

    def test_uninitialized_project_installs_nothing_non_fatally(self):
        project = Path(tempfile.mkdtemp())
        report = IntegrationInstaller(project).install()
        self.assertTrue(report.ok)
        self.assertEqual([o.outcome for o in report.outcomes], [SKIPPED_UNREGISTERED])
        self.assertFalse((project / ".agents").exists())

    def test_no_temp_files_remain(self):
        self.declare("opencode")
        self.install()
        base = self.root / ".opencode" / "skills" / "cockpit-run-context"
        leftovers = [p.name for p in base.iterdir() if p.name.startswith(".artifact-")]
        self.assertEqual(leftovers, [])

    def test_write_failure_is_reported_not_raised(self):
        self.declare("claude")
        (self.root / ".claude").write_text("blocks the directory", encoding="utf-8")
        report = self.install()
        self.assertEqual([o.outcome for o in report.outcomes], [FAILED])
        self.assertFalse(report.outcomes[0].ok)


if __name__ == "__main__":
    unittest.main()
