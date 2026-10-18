"""Core services stay free of UI toolkit imports (FR-033).

The host, the read command, the installer, and the defenses must be importable
and testable without a running app, so no module outside ``workflow_cockpit/ui/``
may import Textual.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "workflow_cockpit"
REPO_ROOT = PACKAGE.parent

#: ``styling`` resolves Textual themes, but only through the UI layer's install
#: step; it holds no widget or app imports of its own.
UI_ONLY = (PACKAGE / "ui",)
FORBIDDEN = "textual"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


class NoTextualOutsideUiTests(unittest.TestCase):
    def test_no_core_module_imports_textual(self):
        offenders: list[str] = []
        for path in sorted(PACKAGE.rglob("*.py")):
            if any(path.is_relative_to(ui_dir) for ui_dir in UI_ONLY):
                continue
            for module in _imports(path):
                if module == FORBIDDEN or module.startswith(f"{FORBIDDEN}."):
                    offenders.append(f"{path.relative_to(PACKAGE)}: {module}")
        self.assertEqual(offenders, [], "Textual imported outside workflow_cockpit/ui/")

    def test_the_host_package_is_importable_without_textual(self):
        # Import in a child process so this test cannot disturb Textual's module
        # state for the rest of the suite.
        script = (
            "import sys, workflow_cockpit.host; "
            "raise SystemExit(1 if 'textual' in sys.modules else 0)"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
