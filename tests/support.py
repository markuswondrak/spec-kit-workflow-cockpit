"""Shared test fixtures, fakes, and platform gates.

The test doubles themselves live in :mod:`tests.fakes`; they are re-exported here
so existing imports keep working.
"""

from __future__ import annotations

import json
import os
import signal
import unittest
from pathlib import Path
from typing import Any

from packaging.version import Version
from textual.app import App

from tests.fakes import (  # noqa: F401 - re-exported test doubles
    FakeGit,
    FakeReviewService,
    FakeSession,
    FakeSupervisor,
)
from workflow_cockpit.bootstrap.compatibility import CompatibilityResult
from workflow_cockpit.styling.resolver import ResolvedStyle
from workflow_cockpit.styling.tokens import default_template
from workflow_cockpit.ui.theme import install_style

STYLES = Path(__file__).resolve().parents[1] / "workflow_cockpit" / "ui" / "styles.tcss"

#: POSIX hosts expose process groups, catchable signals, and the ``pty`` module.
POSIX = os.name == "posix"
PTY = POSIX and hasattr(os, "openpty")
CATCHABLE_SIGNALS = (signal.SIGINT, signal.SIGHUP, signal.SIGTERM) if POSIX else ()

#: The one pinned real-``specify`` executable considered by contract tests.
REAL_SPECIFY = next(
    (
        Path(path)
        for path in (
            os.environ.get("WORKFLOW_COCKPIT_REAL_SPECIFY"),
            "/home/markus/workspace/spec-kit/.venv/bin/specify",
        )
        if path and Path(path).exists()
    ),
    None,
)


def requires_posix(test):
    """Skip a test unless POSIX process/signal semantics are available."""
    return unittest.skipUnless(POSIX, "requires a POSIX host")(test)


def requires_pty(test):
    """Skip a test unless an output PTY can be allocated."""
    return unittest.skipUnless(PTY, "requires a PTY-capable host")(test)


def requires_real_specify(test):
    """Skip a test unless the pinned real ``specify`` executable is present."""
    return unittest.skipUnless(REAL_SPECIFY is not None, "real specify executable is unavailable")(test)


class StyledApp(App):
    """App that loads the real cockpit stylesheet.

    ``CSS_PATH`` must be a class attribute to be picked up; assigning it to an
    instance after construction is silently ignored. The neutral style is
    installed so the theme-supplied tokens resolve.
    """

    CSS_PATH = str(STYLES)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        install_style(self, ResolvedStyle(template=default_template(), source="default"))


LINEAR_WORKFLOW = {
    "schema_version": "1.0",
    "workflow": {
        "id": "demo",
        "name": "Demo Workflow",
        "version": "1.0.0",
        "description": "A demo workflow",
    },
    "inputs": {
        "spec": {"type": "string", "required": True, "prompt": "Describe"},
        "profile": {
            "type": "string",
            "default": "standard",
            "enum": ["standard", "extended"],
        },
        "publish": {"type": "boolean", "default": True},
        "review_verdict": {"type": "string"},
    },
    "steps": [
        {"id": "prepare", "command": "demo.prepare"},
        {
            "id": "review",
            "type": "gate",
            "message": "Review it",
            "options": ["approve", "reject"],
            "verdict_input": "review_verdict",
            "on_reject": "retry",
        },
        {"id": "finish", "command": "demo.finish"},
    ],
}


def write_workflow(root: Path, workflow: dict[str, Any] | None = None, workflow_id: str = "demo") -> Path:
    import yaml

    workflows_dir = root / ".specify" / "workflows"
    (workflows_dir / workflow_id).mkdir(parents=True, exist_ok=True)
    path = workflows_dir / workflow_id / "workflow.yml"
    path.write_text(yaml.safe_dump(workflow or LINEAR_WORKFLOW, sort_keys=False), encoding="utf-8")
    return path


def write_registry(root: Path, entries: dict[str, Any] | None = None) -> Path:
    workflows_dir = root / ".specify" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    if entries is None:
        entries = {
            "demo": {
                "name": "Demo Workflow",
                "version": "1.0.0",
                "description": "A demo workflow",
                "enabled": True,
            }
        }
    data = {"schema_version": "1.0", "workflows": entries}
    path = workflows_dir / "workflow-registry.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def write_run(
    root: Path,
    run_id: str = "cockpit-testrun",
    *,
    status: str = "running",
    current_step_id: str | None = "prepare",
    error: str | None = None,
    inputs: dict[str, Any] | None = None,
    log_lines: list[dict[str, Any]] | None = None,
    step_results: dict[str, Any] | None = None,
) -> Path:
    run_dir = root / ".specify" / "workflows" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "run_id": run_id,
        "workflow_id": "demo",
        "status": status,
        "current_step_index": 0,
        "current_step_id": current_step_id,
        "step_results": step_results or {},
        "error": error,
        "updated_at": "2026-09-13T00:00:00+00:00",
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (run_dir / "inputs.json").write_text(json.dumps({"inputs": inputs or {"spec": "search"}}), encoding="utf-8")
    if log_lines:
        (run_dir / "log.jsonl").write_text("".join(json.dumps(entry) + "\n" for entry in log_lines), encoding="utf-8")
    return run_dir


def compatibility_result(version: str = "1.0.0") -> CompatibilityResult:
    parsed = Version(version)
    return CompatibilityResult(
        executable=Path("/usr/bin/specify"),
        version=parsed,
        raw=f"specify {version}",
        prerelease=parsed.is_prerelease,
        tested_range=">=1.0,<2.0",
    )
