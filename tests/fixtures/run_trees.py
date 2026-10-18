"""Prepared run trees for the read-command, installer, and host tests.

Every variant is built from the existing fixture helpers, so the tests exercise
the same shapes the engine and Cockpit produce: a flat live run, a composed run
recorded from a pinned engine (ADR-0015), a paused run at a declared gate, a run
whose ``state.json`` went stale or is missing, and a worktree with no run at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.fixtures import composition as composed
from tests.support import LINEAR_WORKFLOW, write_registry, write_run, write_workflow
from workflow_cockpit.services.current_run_pointer import CurrentRunPointerWriter

#: The default fixture run identity.
RUN_ID = "cockpit-fixture"

#: The declared gate evidence a paused flat run carries in ``step_results``.
PAUSED_GATE_RESULT = {
    "type": "gate",
    "status": "paused",
    "output": {"message": "Review it", "options": ["approve", "reject"], "choice": None},
}


def write_pointer(root: Path, run_id: str = RUN_ID, *, workflow_id: str = "demo") -> None:
    """Write the pointer pair the way a run start does (JSON first)."""
    CurrentRunPointerWriter(root).write(run_id=run_id, workflow_id=workflow_id)


def write_launch_copy(run_dir: Path, workflow: dict) -> Path:
    """Write the launch-copy ``workflow.yml`` the engine persists with a run."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "workflow.yml"
    path.write_text(yaml.safe_dump(workflow, sort_keys=False), encoding="utf-8")
    return path


def live_flat(
    root: Path,
    *,
    run_id: str = RUN_ID,
    status: str = "running",
    current_step_id: str | None = "prepare",
    pointer: bool = True,
) -> Path:
    """A flat run with a readable ``state.json`` and no execution tree."""
    write_workflow(root)
    write_registry(root)
    run_dir = write_run(root, run_id, status=status, current_step_id=current_step_id)
    write_launch_copy(run_dir, LINEAR_WORKFLOW)
    if pointer:
        write_pointer(root, run_id)
    return run_dir


def paused_gate(root: Path, *, run_id: str = RUN_ID, pointer: bool = True) -> Path:
    """A flat run paused at its declared verdict gate with an open gate."""
    write_workflow(root, LINEAR_WORKFLOW)
    write_registry(root)
    run_dir = write_run(
        root,
        run_id,
        status="paused",
        current_step_id="review",
        step_results={"review": PAUSED_GATE_RESULT},
    )
    write_launch_copy(run_dir, LINEAR_WORKFLOW)
    if pointer:
        write_pointer(root, run_id)
    return run_dir


def live_composed(
    root: Path,
    *,
    scenario: str = "reference",
    run_id: str = RUN_ID,
    pointer: bool = True,
) -> Path:
    """A composed run recorded from a pinned engine, plus its installed children."""
    from tests.composition_support import write_project

    write_project(root, scenario)
    run_dir = composed.write_run(root, scenario, run_id=run_id)
    if pointer:
        write_pointer(root, run_id, workflow_id=composed.load_state(scenario)["workflow_id"])
    return run_dir


def missing_state(root: Path, *, run_id: str = RUN_ID, pointer: bool = True) -> Path:
    """A run directory that exists but has no ``state.json``."""
    write_workflow(root)
    write_registry(root)
    run_dir = root / ".specify" / "workflows" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_launch_copy(run_dir, LINEAR_WORKFLOW)
    if pointer:
        write_pointer(root, run_id)
    return run_dir


def unreadable_state(root: Path, *, run_id: str = RUN_ID, pointer: bool = True) -> Path:
    """A run whose ``state.json`` exists but is not valid JSON."""
    write_workflow(root)
    write_registry(root)
    run_dir = root / ".specify" / "workflows" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "state.json").write_text("{not json", encoding="utf-8")
    write_launch_copy(run_dir, LINEAR_WORKFLOW)
    if pointer:
        write_pointer(root, run_id)
    return run_dir


def no_run(root: Path) -> Path:
    """An initialized worktree with a workflow but no run and no pointer."""
    write_workflow(root)
    write_registry(root)
    return root / ".specify" / "workflows" / "runs"


def write_feature_directory(root: Path, *, files: dict[str, str] | None = None) -> Path:
    """Declare a feature directory and populate it with Markdown files."""
    feature = root / "specs" / "demo"
    feature.mkdir(parents=True, exist_ok=True)
    for name, content in (files or {"spec.md": "# Spec\n", "plan.md": "# Plan\n"}).items():
        path = feature / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (root / ".specify").mkdir(parents=True, exist_ok=True)
    (root / ".specify" / "feature.json").write_text(
        json.dumps({"feature_directory": "specs/demo"}), encoding="utf-8"
    )
    return feature


def run_tree_hash(root: Path) -> dict[str, tuple[int, int]]:
    """A ``path -> (size, mtime_ns)`` fingerprint of every run-tree file."""
    runs = root / ".specify" / "workflows" / "runs"
    fingerprint: dict[str, tuple[int, int]] = {}
    for path in sorted(runs.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        fingerprint[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return fingerprint
