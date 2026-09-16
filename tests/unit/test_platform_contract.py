import unittest
from pathlib import Path

from workflow_cockpit.ui.screens.help import RESILIENCE_GUIDANCE

README = Path(__file__).resolve().parents[2] / "README.md"


class PlatformContractDocsTests(unittest.TestCase):
    def test_readme_documents_supported_platforms(self):
        text = README.read_text(encoding="utf-8")
        for phrase in ("Linux, macOS, and WSL", "Native Windows is explicitly unsupported"):
            self.assertIn(phrase, text)

    def test_readme_documents_no_cleanup_guarantee(self):
        text = README.read_text(encoding="utf-8")
        self.assertIn("no cleanup guarantee", text)
        self.assertIn("SIGKILL", text)

    def test_help_lists_platforms_and_no_guarantee_boundary(self):
        self.assertIn("Linux, macOS, and WSL", RESILIENCE_GUIDANCE)
        self.assertIn("SIGKILL", RESILIENCE_GUIDANCE)
        self.assertIn("STALE", RESILIENCE_GUIDANCE)


if __name__ == "__main__":
    unittest.main()
