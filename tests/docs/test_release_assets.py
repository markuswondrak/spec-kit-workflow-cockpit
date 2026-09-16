"""Release metadata and contributor guidance contract tests."""

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
            "requirements/README.md",
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


if __name__ == "__main__":
    unittest.main()
