"""Release metadata and contributor guidance contract tests."""

import re
import unittest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from tests.docs.support import ROOT, read


class ReleaseAssetTests(unittest.TestCase):
    def test_project_metadata_is_publishable(self):
        project = tomllib.loads(read(ROOT / "pyproject.toml"))["project"]
        self.assertTrue(project["description"])
        self.assertEqual(project["readme"], "README.md")
        self.assertEqual(project["requires-python"], ">=3.10")
        self.assertEqual(project["license"], "MIT")
        self.assertEqual(project["license-files"], ["LICENSE"])
        self.assertTrue(project["authors"])
        self.assertTrue(project["keywords"])
        self.assertTrue(project["classifiers"])
        self.assertEqual(set(project["urls"]), {"Homepage", "Repository", "Issues"})

    def test_root_license_is_mit(self):
        license_text = read(ROOT / "LICENSE")
        self.assertTrue(license_text.startswith("MIT License"))
        self.assertIn("Permission is hereby granted", license_text)

    def test_readme_covers_release_onboarding(self):
        text = read(ROOT / "README.md")
        for heading in (
            "Why Cockpit?", "Prerequisites", "Installation", "Quickstart",
            "Configuration", "Documentation and Requirements", "Contributing", "License",
        ):
            self.assertIn(f"## {heading}\n", text)
        for reference in (
            "https://github.com/markuswondrak/AgentMux",
            "deterministic multi-agent",
            "docs/architecture/README.md",
            "https://github.com/markuswondrak/spec-kit-workflow-cockpit/issues",
            "git+https://github.com/markuswondrak/spec-kit-workflow-cockpit.git",
            "https://markus.wondrax.cloud/articles/documentation-agentic-coding.html",
            "[CONTRIBUTING.md](CONTRIBUTING.md)",
            "[MIT](LICENSE)",
            "workflow-cockpit --check\nworkflow-cockpit\n",
        ):
            self.assertIn(reference, text)

    def test_contributing_documents_setup_quality_and_dogfooding(self):
        text = read(ROOT / "CONTRIBUTING.md")
        for command in (
            'python -m pip install -e ".[test]"',
            "ruff check workflow_cockpit tests",
            "python -m pytest tests/unit tests/textual tests/contract tests/pty tests/docs -q",
            "python -m build",
            "python tests/release/smoke.py dist",
            "specify preset add --dev ./presets/lean-workflow --priority 1",
            "specify extension add --dev ./extensions/arc42",
            "specify workflow add --dev ./workflows/lean-flow",
        ):
            self.assertIn(command, text)


class ReleasePipelineTests(unittest.TestCase):
    def test_package_version_is_single_sourced(self):
        data = tomllib.loads(read(ROOT / "pyproject.toml"))
        project = data["project"]
        self.assertNotIn("version", project)
        self.assertIn("version", project.get("dynamic", []))
        self.assertEqual(
            data["tool"]["setuptools"]["dynamic"]["version"],
            {"attr": "workflow_cockpit.__version__"},
        )
        init = read(ROOT / "workflow_cockpit" / "__init__.py")
        match = re.search(r'^__version__ = "([^"]+)"$', init, re.MULTILINE)
        self.assertIsNotNone(match, "workflow_cockpit/__init__.py has no __version__")

    def test_test_workflow_covers_supported_pythons_and_is_reusable(self):
        text = read(ROOT / ".github" / "workflows" / "test.yml")
        self.assertIn("workflow_call", text)
        for version in ('"3.10"', '"3.11"', '"3.12"'):
            self.assertIn(version, text)

    def test_release_workflow_is_tag_driven_and_guarded(self):
        text = read(ROOT / ".github" / "workflows" / "release.yml")
        for marker in (
            'tags: ["v*"]',
            "uses: ./.github/workflows/test.yml",
            "merge-base --is-ancestor",
            "contents: write",
            "--generate-notes",
        ):
            self.assertIn(marker, text)

    def test_releasing_guide_exists_and_is_linked(self):
        self.assertTrue((ROOT / "RELEASING.md").is_file())
        for name in ("README.md", "CONTRIBUTING.md"):
            self.assertIn("[RELEASING.md](RELEASING.md)", read(ROOT / name), name)


if __name__ == "__main__":
    unittest.main()
