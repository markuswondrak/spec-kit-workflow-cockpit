"""Shared test fixtures and fakes."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.version import Version
from textual.app import App

from workflow_cockpit.bootstrap.compatibility import CompatibilityResult
from workflow_cockpit.engine.supervisor import ProcessCondition
from workflow_cockpit.services.definition import (
    InputSpec,
    StepSpec,
    WorkflowDefinition,
)
from workflow_cockpit.services.graph import WorkflowDefinitionParser
from workflow_cockpit.services.projection import GraphProjector
from workflow_cockpit.services.run_state import RunStateData
from workflow_cockpit.services.snapshot import RunSnapshot

STYLES = Path(__file__).resolve().parents[1] / "workflow_cockpit" / "ui" / "styles.tcss"


class StyledApp(App):
    """App that loads the real cockpit stylesheet.

    ``CSS_PATH`` must be a class attribute to be picked up; assigning it to an
    instance after construction is silently ignored.
    """

    CSS_PATH = str(STYLES)


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
    },
    "steps": [
        {"id": "prepare", "command": "demo.prepare"},
        {
            "id": "review",
            "type": "gate",
            "message": "Review it",
            "options": ["approve", "reject"],
            "verdict_input": "spec",
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


@dataclass
class FakeGit:
    head_value: str | None = "a" * 40
    branch_value: str | None = "main"
    dirty_value: bool = False

    def head(self):
        return self.head_value

    def branch(self):
        return self.branch_value

    def is_dirty(self):
        return self.dirty_value

    def is_worktree(self):
        return True


class FakeReviewService:
    """Feature Files double that never touches disk."""

    def refresh(self):
        from workflow_cockpit.services.review import ReviewSnapshot

        return ReviewSnapshot(feature_dir="specs/demo", status="ready")

    def document(self, path, *, full=False):
        from workflow_cockpit.services.review import ReviewDocument

        return ReviewDocument(path=path, text="file content")

    def resolve_path(self, path):
        if not path:
            return None
        return Path("/tmp/demo-project") / path


class FakeSupervisor:
    """Supervisor double that never spawns a real process."""

    def __init__(self, *, live: bool = True, exit_code: int | None = None) -> None:
        self.run_id: str | None = None
        self.started_at: float | None = None
        self.output_lines: list[str] = ["starting demo"]
        self.partial_line = ""
        self.output_emitted = len(self.output_lines)
        self.exit_code = exit_code
        self.last_reaped_command: str | None = None
        self.abort_requested = False
        self.abort_calls = 0
        self.started_argv: list[str] | None = None
        self.resume_calls: list[tuple[str, list[str]]] = []
        self._active_command: str | None = None
        self._live = live

    def start(self, run_id: str, argv, *, env=None) -> None:
        self.run_id = run_id
        self.started_argv = list(argv)
        self.started_at = 0.0
        self._live = True
        self._active_command = "run"

    def resume(self, run_id: str, argv, *, env=None) -> None:
        if self.run_id is None:
            raise RuntimeError("No run has been started to resume.")
        self.resume_calls.append((run_id, list(argv)))
        self.started_argv = list(argv)
        self._live = True
        self.last_reaped_command = None
        self._active_command = "resume"

    def condition(self) -> ProcessCondition:
        return ProcessCondition(
            live=self._live,
            exit_code=self.exit_code,
            reaped=not self._live,
            aborting=self.abort_requested and not self._live,
        )

    def verify_live(self) -> bool:
        return self._live

    def is_live(self) -> bool:
        return self._live

    def abort(self) -> None:
        self.abort_calls += 1
        self.abort_requested = True
        self._live = False

    def finish(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        self._live = False
        self.last_reaped_command = self._active_command

    def close(self) -> None:
        pass


class FakeSession:
    """Minimal presentation double."""

    project_root = Path("/tmp/demo-project")

    def __init__(self, *, dirty: bool = False, status: str = "running") -> None:
        self.git = FakeGit(dirty_value=dirty)
        self.definition = WorkflowDefinition(
            id="demo",
            name="Demo Workflow",
            version="1.0.0",
            description="A demo workflow",
            inputs=(
                InputSpec(name="spec", type="string", required=True, prompt="Describe"),
                InputSpec(
                    name="profile",
                    type="string",
                    has_default=True,
                    default="standard",
                    enum=("standard", "extended"),
                ),
                InputSpec(name="publish", type="boolean", has_default=True, default=True),
            ),
            steps=(
                StepSpec(id="prepare", label="prepare"),
                StepSpec(id="review", label="review", gate=True, options=("approve", "reject")),
                StepSpec(id="finish", label="finish"),
            ),
        )
        self.status = status
        self.started = False
        self.aborted = False
        self.abort_delay = 0.0
        self.started_values: dict[str, Any] | None = None
        self.output_lines: list[str] = ["starting demo", "preparing"]
        self.output_emitted: int | None = None
        self.gate = None
        self.review = None
        self.reviewing = False
        self.process_live_override: bool | None = None
        self.diagnostic = ""
        self.decisions: list[str] = []
        self.refreshed = 0
        self.editor_launches: list[str] = []
        self.editor = "/usr/bin/true"
        self._graph = WorkflowDefinitionParser().parse(
            (
                {"id": "prepare", "command": "demo.prepare"},
                {
                    "id": "review",
                    "type": "gate",
                    "message": "Review it",
                    "options": ["approve", "reject"],
                },
                {"id": "finish", "command": "demo.finish"},
            )
        )

    def list_workflows(self):
        @dataclass
        class Entry:
            id: str = "demo"
            name: str = "Demo Workflow"
            version: str = "1.0.0"
            description: str = "A demo workflow"
            source: str = ""
            enabled: bool = True
            raw: dict = None

        return (Entry(),)

    def select(self, workflow_id: str):
        return self.definition

    def validate(self, values):
        if not str(values.get("spec", "")).strip():
            return {}, {"spec": "Required."}
        return values, {}

    def start(self, values):
        self.started = True
        self.started_values = dict(values)
        return self.snapshot()

    def abort(self):
        self.aborted = True
        self.status = "aborted"
        if self.abort_delay:
            time.sleep(self.abort_delay)
        return self.snapshot()

    def decide(self, choice):
        self.decisions.append(choice)
        if self.gate is not None and not self.gate.malformed:
            self.status = "running"
            self.gate = None
        return self.snapshot()

    def refresh_review(self):
        self.refreshed += 1
        return self.review

    def review_document(self, path, *, full=False):
        from workflow_cockpit.services.review import ReviewDocument

        return ReviewDocument(path=path, text="file content")

    def resolve_path(self, path):
        if not path:
            return None
        return Path(self.project_root) / path

    def snapshot(self) -> RunSnapshot:
        from workflow_cockpit.services.snapshot import Outcome, OutcomeKind

        kind_map = {
            "success": OutcomeKind.SUCCESS,
            "failure": OutcomeKind.FAILURE,
            "abort": OutcomeKind.ABORT,
        }
        outcome = None
        if self.status in kind_map:
            outcome = Outcome(kind=kind_map[self.status], detail="test outcome", engine_status=self.status)
        return RunSnapshot(
            run_id="cockpit-abcdef123456",
            workflow_id="demo",
            workflow_name="Demo Workflow",
            status=self.status,
            current_step_id="prepare",
            branch="main",
            elapsed_seconds=12,
            output_tail=tuple(self.output_lines),
            output_emitted=(
                self.output_emitted if self.output_emitted is not None else len(self.output_lines)
            ),
            process_live=(
                self.process_live_override
                if self.process_live_override is not None
                else self.status == "running"
            ),
            engine_status=self.status,
            outcome=outcome,
            gate=self.gate,
            review=self.review,
            reviewing=self.reviewing,
            diagnostic=self.diagnostic,
            graph_projection=GraphProjector().project(
                self._graph,
                RunStateData(
                    status="completed" if self.status == "success" else self.status,
                    current_step_id="prepare",
                    step_results={"prepare": {"status": "completed"}} if self.status != "running" else {},
                ),
            ),
        )
