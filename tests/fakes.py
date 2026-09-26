"""Shared test doubles, split from ``tests/support.py`` to stay under 500 lines.

These fakes never spawn a process and never touch the network. Fixture builders and
platform gates remain in :mod:`tests.support`; this module holds only the doubles.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from workflow_cockpit.engine.pty_session import WriteOutcome
from workflow_cockpit.engine.supervisor import ProcessCondition, StdinPolicy, SupervisorError
from workflow_cockpit.services.definition import InputSpec, StepSpec, WorkflowDefinition
from workflow_cockpit.services.graph import WorkflowDefinitionParser
from workflow_cockpit.services.projection import GraphProjector
from workflow_cockpit.services.run_state import RunStateData
from workflow_cockpit.services.snapshot import GateState, RunSnapshot


@dataclass
class FakeGit:
    head_value: str | None = "a" * 40
    branch_value: str | None = "main"
    dirty_value: bool = False
    branch_error: str = ""

    def head(self):
        return self.head_value

    def branch(self):
        return self.branch_value

    def branch_result(self):
        from workflow_cockpit.services.git import BranchRead

        if self.branch_error:
            return BranchRead(value=None, ok=False, error=self.branch_error)
        return BranchRead(value=self.branch_value)

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
        self.resume_stdin: list[StdinPolicy] = []
        self.writes: list[bytes] = []
        self.write_result = WriteOutcome.WRITTEN
        self.stdin_policy = StdinPolicy.DEVNULL
        self.resume_error = ""
        self._active_command: str | None = None
        self._live = live

    @property
    def interactive(self) -> bool:
        return self.stdin_policy is StdinPolicy.PTY

    def start(self, run_id: str, argv, *, stdin=None, env=None) -> None:
        self.run_id = run_id
        self.started_argv = list(argv)
        self.started_at = 0.0
        self._live = True
        if stdin is not None:
            self.stdin_policy = StdinPolicy(stdin)
        self._active_command = "run"

    def bind_existing(self, run_id: str) -> None:
        if self.run_id is not None or self.started_argv is not None:
            raise RuntimeError("This supervisor has already owned a run.")
        self.run_id = run_id
        self._live = False
        self.last_reaped_command = None
        self._active_command = None

    def resume(self, run_id: str, argv, *, stdin=None, env=None) -> None:
        if self.resume_error:
            raise SupervisorError(self.resume_error)
        if self.run_id is None:
            raise RuntimeError("No run has been started to resume.")
        self.resume_calls.append((run_id, list(argv)))
        self.resume_stdin.append(StdinPolicy(stdin) if stdin is not None else self.stdin_policy)
        self.started_argv = list(argv)
        if self.started_at is None:
            self.started_at = 0.0
        self._live = True
        self.last_reaped_command = None
        self._active_command = "resume"

    def condition(self) -> ProcessCondition:
        return ProcessCondition(
            live=self._live,
            exit_code=self.exit_code,
            reaped=not self._live,
            aborting=self.abort_requested and not self._live,
            stdin_pty=self.stdin_policy is StdinPolicy.PTY,
        )

    def verify_live(self) -> bool:
        return self._live

    def is_live(self) -> bool:
        return self._live

    def write_input(self, data: bytes) -> WriteOutcome:
        if self.abort_requested or not self._live:
            return WriteOutcome.NOT_WRITTEN
        if self.write_result is not WriteOutcome.WRITTEN and self.write_result is not WriteOutcome.UNCERTAIN:
            return WriteOutcome.NOT_WRITTEN
        self.writes.append(bytes(data))
        return self.write_result

    def abort(self):
        from workflow_cockpit.engine.supervisor import AbortResult

        was_live = self._live
        self.abort_calls += 1
        self.abort_requested = True
        self._live = False
        return AbortResult(
            signalled=was_live,
            reaped=True,
            escalation="SIGINT" if was_live else None,
        )

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
                InputSpec(name="review_verdict", type="string"),
            ),
            steps=(
                StepSpec(id="prepare", label="prepare"),
                StepSpec(
                    id="review",
                    label="review",
                    gate=True,
                    options=("approve", "reject"),
                    verdict_input="review_verdict",
                ),
                StepSpec(id="finish", label="finish"),
            ),
        )
        self.status = status
        self.started = False
        self.aborted = False
        self.abort_delay = 0.0
        self.run_id = "cockpit-abcdef123456"
        self.last_abort_result = None
        self.branch = "main"
        self.stale = False
        self.branch_refreshes = 0
        self.started_values: dict[str, Any] | None = None
        self.output_lines: list[str] = ["starting demo", "preparing"]
        self.output_emitted: int | None = None
        self.gate = None
        self.review = None
        self.reviewing = False
        self.process_live_override: bool | None = None
        self.diagnostic = ""
        self.outcome_detail = "test outcome"
        self.outcome_label = ""
        self.decisions: list[str] = []
        self.refreshed = 0
        self.editor_launches: list[str] = []
        self.editor = "/usr/bin/true"
        self.context_path = ".specify/workflows/runs/current_run"
        self.context_error = ""
        self.current_step_id = "prepare"
        self.existing_runs: tuple = ()
        self.adopted_run: str | None = None
        self.inspected_run: str | None = None
        self.read_only: bool = False
        self.deleted_runs: list[str] = []
        self.delete_error: str = ""
        self.resumed_tokens: list[str] = []
        self.resume_error: str = ""
        self._resume_token: str | None = None
        self._resume_used = False
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

    def list_existing_runs(self):
        return tuple(self.existing_runs)

    @property
    def adopted(self) -> bool:
        return self.adopted_run is not None

    def adopt(self, run_id):
        self.adopted_run = run_id
        self.run_id = run_id
        self.started = True
        self.status = "paused"
        return self.snapshot()

    def inspect(self, run_id):
        self.inspected_run = run_id
        self.run_id = run_id
        self.started = True
        self.read_only = True
        return self.snapshot()

    def delete_existing_run(self, run_id):
        if self.delete_error:
            raise RuntimeError(self.delete_error)
        self.deleted_runs.append(run_id)
        self.existing_runs = tuple(
            descriptor for descriptor in self.existing_runs if descriptor.run_id != run_id
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

    def submit_decision(self, choice, token):
        if self.gate is None or self.gate.state is not GateState.READY:
            raise RuntimeError("This gate cannot be decided.")
        if not token or token != self.gate.token:
            raise RuntimeError("The gate changed; this submission is stale.")
        self.decisions.append(choice)
        self.gate = replace(
            self.gate,
            state=GateState.SUBMITTED,
            token=None,
            acknowledged="Choice submitted once.",
        )
        return self.snapshot()

    def resume_decision(self):
        from workflow_cockpit.session.resume import ResumeDecision

        if not self.adopted or self.read_only or self.status != "failed":
            return ResumeDecision(False, reason="not resumable")
        if self._resume_token is None:
            self._resume_token = "resume-token"
        return ResumeDecision(
            available=True,
            step_id="review",
            step_label="review",
            token=None if self._resume_used else self._resume_token,
        )

    def resume_run(self, token):
        if self.resume_error:
            raise RuntimeError(self.resume_error)
        if not self.adopted or self.read_only or self.status != "failed":
            raise RuntimeError("This run cannot be resumed.")
        if self._resume_used or not token or token != self._resume_token:
            raise RuntimeError("The resume request changed; this confirmation is stale.")
        self._resume_used = True
        self.resumed_tokens.append(token)
        self.status = "running"
        return self.snapshot()

    def refresh_branch(self):
        self.branch_refreshes += 1
        return self.branch

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
            "failed": OutcomeKind.FAILURE,
            "abort": OutcomeKind.ABORT,
        }
        outcome = None
        if self.status in kind_map:
            outcome = Outcome(
                kind=kind_map[self.status],
                detail=self.outcome_detail,
                engine_status=self.status,
                detail_label=self.outcome_label,
            )
        return RunSnapshot(
            run_id="cockpit-abcdef123456",
            workflow_id="demo",
            workflow_name="Demo Workflow",
            status=self.status,
            current_step_id=self.current_step_id,
            branch=self.branch,
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
            adopted=self.adopted,
            read_only=self.read_only,
            stale=self.stale,
            diagnostic=self.diagnostic,
            context_path=self.context_path,
            context_error=self.context_error,
            graph_projection=GraphProjector().project(
                self._graph,
                RunStateData(
                    status="completed" if self.status == "success" else self.status,
                    current_step_id=self.current_step_id,
                    step_results={"prepare": {"status": "completed"}} if self.status != "running" else {},
                ),
            ),
        )
