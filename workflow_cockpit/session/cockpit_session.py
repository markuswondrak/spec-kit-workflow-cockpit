"""CockpitSession facade: the only API the presentation layer calls."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from ..bootstrap.compatibility import CompatibilityResult
from ..engine.supervisor import EngineSupervisor, StdinPolicy, build_run_argv
from ..services.definition import (
    WorkflowDefinition,
    WorkflowDefinitionResolver,
    definition_signature,
    inputs_to_argv,
    normalized_signature,
    validate_inputs,
)
from ..services.feature_review import FeatureReviewService
from ..services.git import GitService
from ..services.graph import ControlFlowGraph, WorkflowDefinitionParser, resolve_declared_id
from ..services.log_aggregator import RunLogAggregator
from ..services.projection import GraphProjector
from ..services.registry import WorkflowEntry, WorkflowRegistry
from ..services.review import ReviewDocument, ReviewSnapshot
from ..services.run_state import RunStateReader
from ..services.snapshot import GateSnapshot, Outcome, OutcomeKind, RunSnapshot
from .gate_decision import GateDecisionCoordinator, GateDecisionError, validate_shape

#: Bounded post-write verification watch (about 40 ticks at the 250 ms cadence).
SUBMISSION_WATCH_SECONDS = 10.0


class SessionError(Exception):
    """Raised for invalid session lifecycle calls."""


def generate_run_id(runs_dir: Path) -> str:
    """Return a collision-resistant run ID whose directory does not exist."""
    for _ in range(100):
        candidate = f"cockpit-{secrets.token_hex(6)}"
        if not (runs_dir / candidate).exists():
            return candidate
    raise SessionError("Could not allocate a unique run ID.")


class CockpitSession:
    """Compose services for one project and, at most, one run."""

    def __init__(
        self,
        project_root: Path,
        compatibility: CompatibilityResult,
        *,
        registry: WorkflowRegistry | None = None,
        resolver: WorkflowDefinitionResolver | None = None,
        git: GitService | None = None,
        review_source: FeatureReviewService | None = None,
        supervisor: EngineSupervisor | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.project_root = Path(project_root)
        self.compatibility = compatibility
        self.registry = registry or WorkflowRegistry(self.project_root)
        self.resolver = resolver or WorkflowDefinitionResolver(self.project_root)
        self.git = git or GitService(self.project_root)
        self.review_source = review_source or FeatureReviewService(self.project_root)
        self._clock = clock
        self._supervisor = supervisor or EngineSupervisor(compatibility.executable, self.project_root)
        self._definition: WorkflowDefinition | None = None
        self._reader: RunStateReader | None = None
        self._started = False
        self._ended_at: float | None = None
        self._branch: str | None = None
        self._contract_error: str | None = None
        self._graph: ControlFlowGraph | None = None
        self._projector = GraphProjector()
        self._log_aggregator: RunLogAggregator | None = None
        self._review: ReviewSnapshot | None = None
        self._review_lock = threading.Lock()
        self._reviewing = False
        self._diagnostic = ""
        self._watch_seconds = SUBMISSION_WATCH_SECONDS
        self._coordinator: GateDecisionCoordinator | None = None
        self._stdin_policy = StdinPolicy.DEVNULL
        self._shape_error = ""

    @property
    def run_id(self) -> str | None:
        return self._supervisor.run_id

    @property
    def definition(self) -> WorkflowDefinition | None:
        return self._definition

    @property
    def compatibility_error(self) -> str:
        """Actionable reason the selected workflow cannot be started, if any."""
        return self._shape_error

    @property
    def runs_dir(self) -> Path:
        return self.project_root / ".specify" / "workflows" / "runs"

    def list_workflows(self) -> tuple[WorkflowEntry, ...]:
        return self.registry.list_runnable()

    def select(self, workflow_id: str) -> WorkflowDefinition:
        definition = self.resolver.resolve(workflow_id)
        self._definition = definition
        self._graph = WorkflowDefinitionParser().parse(definition.effective_steps)
        self._log_aggregator = RunLogAggregator(self._graph.declared_ids)
        support = validate_shape(self._graph, self.compatibility.version)
        self._shape_error = "" if support.ok else support.error
        self._stdin_policy = support.stdin
        self._coordinator = GateDecisionCoordinator(
            graph=self._graph,
            supervisor=self._supervisor,
            executable=self.compatibility.executable,
            version=self.compatibility.version,
            clock=self._clock,
            watch_seconds=self._watch_seconds,
        )
        return definition

    def validate(self, values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        if self._definition is None:
            raise SessionError("No workflow selected.")
        return validate_inputs(self._definition, values)

    def start(self, values: dict[str, Any]) -> RunSnapshot:
        if self._definition is None:
            raise SessionError("No workflow selected.")
        if self._started:
            raise SessionError("This session has already started a run.")
        if self._shape_error:
            raise SessionError(self._shape_error)
        resolved, errors = validate_inputs(self._definition, values)
        if errors:
            raise SessionError("Inputs are not valid: " + "; ".join(errors.values()))

        self._branch = self.git.branch()
        run_id = generate_run_id(self.runs_dir)
        argv = build_run_argv(
            self.compatibility.executable,
            self._definition.id,
            inputs_to_argv(resolved),
        )
        self._supervisor.start(run_id, argv, stdin=self._stdin_policy)
        self._reader = RunStateReader(self.project_root, run_id)
        self._started = True
        return self.snapshot()

    def abort(self) -> RunSnapshot:
        if not self._started:
            raise SessionError("No active run to abort.")
        self._supervisor.abort()
        return self.snapshot()

    def _gate_attempt(self, state) -> int:
        """Authoritative execution count of the current declared step.

        The engine appends one ``step_started`` log event per execution, so this
        increments exactly when a gate is re-executed (a retry) and never when
        an unrelated state write only changes ``updated_at``.
        """
        if self._graph is None or state is None or self._log_aggregator is None or not self.run_id:
            return 0
        declared_id = resolve_declared_id(state.current_step_id, self._graph.declared_ids)
        if declared_id is None:
            return 0
        timings = self._log_aggregator.update(self.runs_dir / self.run_id / "log.jsonl")
        timing = timings.get(declared_id)
        return timing.attempts if timing is not None else 0

    def current_gate(self) -> GateSnapshot | None:
        """The unified gate snapshot for the latest persisted state, if any."""
        if not self._started or self._reader is None or self._coordinator is None:
            return None
        state = self._reader.read()
        return self._coordinator.project(
            state=state,
            run_id=self.run_id,
            condition=self._supervisor.condition(),
            gate_attempt=self._gate_attempt(state),
        )

    def submit_decision(self, choice: str, token: str | None) -> RunSnapshot:
        """Submit one confirmed declared gate choice through the coordinator.

        The UI passes the opaque token it received on the gate snapshot; the
        coordinator selects the transport, enforces write-once, and rejects a
        stale token before any lifecycle write.
        """
        if not self._started or self._reader is None or self._coordinator is None:
            raise SessionError("No active run to decide.")
        if self._supervisor.abort_requested:
            raise SessionError("This run was aborted and cannot resume in this session.")
        state = self._reader.read()
        condition = self._supervisor.condition()
        try:
            self._coordinator.submit(
                choice=choice,
                token=token,
                state=state,
                run_id=self.run_id,
                condition=condition,
                gate_attempt=self._gate_attempt(state),
            )
        except GateDecisionError as exc:
            raise SessionError(str(exc)) from exc
        self._diagnostic = ""
        self._ended_at = None
        return self.snapshot()

    def refresh_review(self) -> ReviewSnapshot:
        """Reload Feature Files; keep the last usable set on failure."""
        self._reviewing = True
        try:
            snapshot = self.review_source.refresh()
        except Exception as exc:  # noqa: BLE001 - any read failure is surfaced, not fatal
            snapshot = ReviewSnapshot(status="error", error=str(exc))
        finally:
            self._reviewing = False
        with self._review_lock:
            previous = self._review
            if snapshot.status == "error" and previous is not None:
                snapshot = replace(previous, status="error", error=snapshot.error)
            elif previous is not None:
                snapshot = replace(snapshot, revision=previous.revision + 1)
            self._review = snapshot
        return snapshot

    @property
    def review(self) -> ReviewSnapshot | None:
        return self._review

    def resolve_path(self, path: str | None) -> Path | None:
        """Resolve a project-relative path that stays inside the project."""
        if not path:
            return None
        return self.review_source.resolve_path(path)

    def review_document(self, path: str, *, full: bool = False) -> ReviewDocument:
        return self.review_source.document(path, full=full)

    def status(self) -> str:
        if not self._started:
            return "idle"
        condition = self._supervisor.condition()
        state = self._reader.read() if self._reader else None
        persisted = state.status if state else "initializing"
        if self._supervisor.abort_requested:
            return "aborting" if not condition.reaped else "aborted"
        return persisted

    def _check_contract(self) -> None:
        """Compare the persisted workflow.yml with the launch model once complete."""
        if self._contract_error is not None or self._definition is None:
            return
        run_id = self._supervisor.run_id
        if not run_id:
            return
        path = self.runs_dir / run_id / "workflow.yml"
        if not path.is_file():
            return
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            return
        if not isinstance(data, dict):
            return
        if normalized_signature(data) != definition_signature(self._definition):
            self._contract_error = "The persisted workflow definition does not match the launch model."
            self._supervisor.abort()

    def _outcome(self, condition_reaped: bool) -> Outcome | None:
        if self._contract_error is not None and condition_reaped:
            return Outcome(
                kind=OutcomeKind.FAILURE,
                detail=self._contract_error,
                engine_status="contract-error",
            )
        if self._supervisor.abort_requested and condition_reaped:
            return Outcome(
                kind=OutcomeKind.ABORT,
                detail="Aborted by you. The engine is no longer running.",
                engine_status="aborted",
            )
        if not condition_reaped:
            return None
        state = self._reader.read() if self._reader else None
        persisted = state.status if state else "initializing"
        if persisted == "completed":
            return Outcome(kind=OutcomeKind.SUCCESS, engine_status=persisted)
        if persisted in ("failed", "aborted"):
            return Outcome(
                kind=OutcomeKind.FAILURE,
                detail=(state.error if state and state.error else f"Engine status: {persisted}"),
                step_id=state.current_step_id if state else None,
                engine_status=persisted,
            )
        if persisted == "paused":
            return None
        return Outcome(
            kind=OutcomeKind.FAILURE,
            detail="The engine process exited without a terminal run state.",
            step_id=state.current_step_id if state else None,
            engine_status=persisted,
        )

    def snapshot(self) -> RunSnapshot:
        if self._started:
            self._check_contract()
        condition = self._supervisor.condition()
        if condition.reaped and self._ended_at is None:
            self._ended_at = self._clock()
        run_id = self._supervisor.run_id or ""
        if not self._started:
            return RunSnapshot(run_id=run_id)

        self._branch = self.git.branch()

        state = self._reader.read() if self._reader else None
        persisted = state.status if state else "initializing"
        if self._supervisor.abort_requested:
            status = "aborting" if not condition.reaped else "aborted"
        elif condition.live and persisted == "paused":
            # A resume has started but the engine has not replaced the previous
            # paused state file yet.
            status = "running"
        else:
            status = persisted
        outcome = self._outcome(condition.reaped)
        if outcome is not None:
            status = outcome.kind.value

        if (
            condition.reaped
            and self._supervisor.last_reaped_command == "resume"
            and condition.exit_code not in (None, 0)
            and persisted == "paused"
        ):
            self._diagnostic = (
                f"Structured resume exited with code {condition.exit_code}; the persisted gate remains paused."
            )
        elif persisted != "paused":
            self._diagnostic = ""

        elapsed = 0.0
        if self._supervisor.started_at is not None:
            end = self._ended_at if self._ended_at is not None else self._clock()
            elapsed = max(0.0, end - self._supervisor.started_at)

        workflow_name = self._definition.name if self._definition else ""
        inputs_tuple = tuple(state.inputs.items()) if state else ()
        timings = {}
        if self._log_aggregator is not None and self.run_id:
            timings = self._log_aggregator.update(self.runs_dir / self.run_id / "log.jsonl")
        gate = None
        if self._coordinator is not None:
            declared_id = None
            if self._graph is not None and state is not None:
                declared_id = resolve_declared_id(state.current_step_id, self._graph.declared_ids)
            gate_attempt = 0
            if declared_id is not None:
                timing = timings.get(declared_id)
                gate_attempt = timing.attempts if timing is not None else 0
            gate = self._coordinator.project(
                state=state,
                run_id=run_id,
                condition=condition,
                gate_attempt=gate_attempt,
            )
        lifecycle_status = "paused" if gate is not None and outcome is None else status
        projection = (
            self._projector.project(
                self._graph, state, timings, lifecycle_status=lifecycle_status
            )
            if self._graph
            else None
        )
        return RunSnapshot(
            run_id=run_id,
            workflow_id=self._definition.id if self._definition else "",
            workflow_name=workflow_name,
            status=status,
            current_step_id=state.current_step_id if state else None,
            branch=self._branch,
            elapsed_seconds=elapsed,
            output_tail=tuple(self._supervisor.output_lines),
            partial_line=self._supervisor.partial_line,
            output_emitted=self._supervisor.output_emitted,
            process_live=condition.live,
            engine_status=persisted,
            engine_error=state.error if state else None,
            outcome=outcome,
            inputs=inputs_tuple,
            graph_projection=projection,
            gate=gate,
            review=self._review,
            reviewing=self._reviewing,
            diagnostic=self._diagnostic,
        )

    def close(self) -> None:
        self._supervisor.close()
