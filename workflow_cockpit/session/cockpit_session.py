"""CockpitSession facade: the only API the presentation layer calls."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..engine.supervisor import StdinPolicy, build_run_argv
from ..services.definition import (
    WorkflowDefinition,
    inputs_to_argv,
    validate_inputs,
)
from ..services.graph import ControlFlowGraph, WorkflowDefinitionParser, resolve_declared_id
from ..services.log_aggregator import RunLogAggregator
from ..services.projection import GraphProjector
from ..services.registry import WorkflowEntry
from ..services.review import ReviewDocument, ReviewSnapshot
from ..services.run_catalog import RunCatalog, RunDescriptor
from ..services.run_claim import ClaimOutcome, RunClaimStore, current_claim
from ..services.run_state import RunStateReader
from ..services.run_store import RunStore
from ..services.snapshot import RunSnapshot
from .adoption import AdoptError, RunAdopter
from .branch import BranchTracker
from .dependencies import CockpitEnvironment, CockpitServices, EngineRuntime
from .gate_decision import GateDecisionCoordinator, GateDecisionError, validate_shape
from .identity import generate_run_id, owner_id
from .lifecycle import check_launch_contract, classify_outcome, write_context_index
from .lifecycle import combine as _combine

#: Bounded post-write verification watch (about 40 ticks at the 250 ms cadence).
SUBMISSION_WATCH_SECONDS = 10.0


class SessionError(Exception):
    """Raised for invalid session lifecycle calls."""


class CockpitSession:
    """Compose services for one project and, at most, one run."""

    def __init__(
        self,
        environment: CockpitEnvironment,
        *,
        services: CockpitServices | None = None,
        engine: EngineRuntime | None = None,
    ) -> None:
        self.environment = environment
        self.project_root = environment.project_root
        self.compatibility = environment.compatibility
        services = services or CockpitServices.for_environment(environment)
        engine = engine or EngineRuntime.for_environment(environment)
        self.services = services
        self.engine = engine
        self.registry = services.registry
        self.resolver = services.resolver
        self.git = services.git
        self.review_source = services.review_source
        self._context_writer = services.context_writer
        self._supervisor = engine.supervisor
        self._clock = engine.clock
        self._context_path = ""
        self._context_error = ""
        self._owner_id = owner_id()
        self._claims = RunClaimStore(self.project_root)
        self._claim_settled = False
        self._claim_error = ""
        self._catalog = RunCatalog(self.project_root, owner_id=self._owner_id, claim_store=self._claims)
        self._adopter = RunAdopter(self.project_root, catalog=self._catalog, claims=self._claims)
        self._run_store = RunStore(self.project_root, owner_id=self._owner_id, claims=self._claims)
        self._adopted = False
        self._read_only = False
        self._inspect_run_id = ""
        self._definition: WorkflowDefinition | None = None
        self._reader: RunStateReader | None = None
        self._started = False
        self._ended_at: float | None = None
        self._branches = BranchTracker(self.git)
        self._last_abort_result = None
        self._lock = threading.RLock()
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
        return self._inspect_run_id if self._read_only else self._supervisor.run_id

    @property
    def read_only(self) -> bool:
        """True when this session is inspecting an existing run read-only."""
        return self._read_only

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

    @property
    def context_path(self) -> str:
        """Project-relative path of the stable context index, if written."""
        return self._context_path

    @property
    def context_error(self) -> str:
        """Reported context-index generation failure; never interrupts the run."""
        return self._context_error

    def list_workflows(self) -> tuple[WorkflowEntry, ...]:
        return self.registry.list_runnable()

    def list_existing_runs(self) -> tuple[RunDescriptor, ...]:
        """Bounded, read-only discovery of existing runs in this project."""
        return self._catalog.list_runs()

    @property
    def adopted(self) -> bool:
        """True when this session bound an existing run instead of starting one."""
        return self._adopted

    def select(self, workflow_id: str) -> WorkflowDefinition:
        definition = self.resolver.resolve(workflow_id)
        self._activate_definition(definition)
        return definition

    def _activate_definition(
        self, definition: WorkflowDefinition, *, adopted: bool = False, read_only: bool = False
    ) -> None:
        """Build the graph, gate projection, and coordinator for one definition."""
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
            adopted=adopted,
            read_only=read_only,
        )

    def adopt(self, run_id: str) -> RunSnapshot:
        """Bind an existing paused run without spawning the engine (FR-007/009)."""
        if self._started:
            raise SessionError("This session has already started a run.")
        try:
            binding = self._adopter.prepare(
                run_id, self._owner_id, branch=self._branches.value
            )
        except AdoptError as exc:
            raise SessionError(str(exc)) from exc
        self._activate_definition(binding.definition, adopted=True)
        try:
            self._supervisor.bind_existing(run_id)
        except Exception as exc:  # noqa: BLE001 - release the claim on any bind failure
            self._claims.release(run_id, self._owner_id)
            raise SessionError(str(exc)) from exc
        self._reader = RunStateReader(self.project_root, run_id)
        self._write_context_index(run_id)
        self._started = True
        self._adopted = True
        return self.snapshot()

    def inspect(self, run_id: str) -> RunSnapshot:
        """Observe an existing run read-only without ownership or engine interaction."""
        if self._started:
            raise SessionError("This session has already started a run.")
        try:
            _descriptor, definition = self._adopter.prepare_inspect(run_id)
        except AdoptError as exc:
            raise SessionError(str(exc)) from exc
        self._inspect_run_id = run_id
        self._read_only = True
        self._activate_definition(definition, read_only=True)
        self._reader = RunStateReader(self.project_root, run_id)
        self._started = True
        return self.snapshot()

    def delete_existing_run(self, run_id: str) -> None:
        """Delete one stale run directory with explicit single-owner safety."""
        protected = self.run_id if self._started else None
        result = self._run_store.delete(run_id, protected_run_id=protected)
        if not result.deleted:
            raise SessionError(result.reason)
        self._context_writer.clear_if_current(run_id)

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

        self.refresh_branch()
        run_id = generate_run_id(self.runs_dir)
        argv = build_run_argv(
            self.compatibility.executable,
            self._definition.id,
            inputs_to_argv(resolved),
        )
        self._supervisor.start(run_id, argv, stdin=self._stdin_policy)
        self._reader = RunStateReader(self.project_root, run_id)
        self._write_context_index(run_id)
        self._started = True
        return self.snapshot()

    def _write_context_index(self, run_id: str) -> None:
        """Write the stable context index; failure is reported, never fatal."""
        self._context_path, self._context_error = write_context_index(
            self._context_writer,
            run_id=run_id,
            definition=self._definition,
            branch=self._branches.value,
            executable=self.compatibility.executable,
        )

    def _ensure_started_claim(self) -> None:
        """Claim ownership of a started run once the engine has created its directory.

        ``EngineSupervisor.start`` deliberately refuses an existing run directory, and
        the engine creates it after spawn, so the claim cannot be written synchronously
        in ``start``. It is acquired on the first poll that observes the directory; a
        write failure is reported and retried, and never interrupts the run. Adoption
        acquires its claim in ``RunAdopter``; read-only inspection never claims.
        """
        if self._claim_settled or not self._started or self._adopted or self._read_only:
            return
        run_id = self._supervisor.run_id
        if run_id is None or not (self.runs_dir / run_id).is_dir():
            return
        claim = current_claim(run_id, self._owner_id, branch=self._branches.value)
        try:
            outcome = self._claims.acquire(run_id, claim)
        except Exception as exc:  # noqa: BLE001 - a claim failure must not stop the run
            self._claim_error = f"Ownership claim unavailable: {exc}"
            self._claim_settled = True
            return
        if outcome is ClaimOutcome.ACQUIRED:
            self._claim_settled = True
        elif outcome is ClaimOutcome.HELD_BY_LIVE_FOREIGN:
            self._claim_settled = True
            self._claim_error = "Another live Cockpit owns this run."
        # FAILED: keep the run going and retry on the next poll.

    @property
    def last_abort_result(self):
        """Cleanup result of the most recent Abort, if any."""
        with self._lock:
            return self._last_abort_result

    def refresh_branch(self) -> str | None:
        """Refresh the cached branch without letting a Git failure block a poll."""
        return self._branches.refresh()

    def abort(self) -> RunSnapshot:
        if not self._started:
            raise SessionError("No active run to abort.")
        if self._read_only:
            raise SessionError("Cannot abort a run viewed in read-only mode.")
        result = self._supervisor.abort()
        with self._lock:
            self._last_abort_result = result
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

    def submit_decision(self, choice: str, token: str | None) -> RunSnapshot:
        """Submit one confirmed declared gate choice through the coordinator.

        The UI passes the opaque token it received on the gate snapshot; the
        coordinator selects the transport, enforces write-once, and rejects a
        stale token before any lifecycle write.
        """
        if not self._started or self._reader is None or self._coordinator is None:
            raise SessionError("No active run to decide.")
        if self._read_only:
            raise SessionError("Cannot submit decisions in read-only mode.")
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
        with self._lock:
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

    def snapshot(self) -> RunSnapshot:
        run_id = self.run_id or ""
        self._ensure_started_claim()
        if self._started and not self._read_only and self._contract_error is None and self._definition and run_id:
            reason = check_launch_contract(self._definition, self.runs_dir / run_id, self._supervisor)
            if reason is not None:
                self._contract_error = reason
        condition = self._supervisor.condition()
        with self._lock:
            if condition.reaped and self._ended_at is None:
                self._ended_at = self._clock()
            started = self._started
        if not started:
            return RunSnapshot(run_id=run_id)

        # All blocking work happens outside the lock: file reads, the log
        # aggregate, and the supervisor probe never serialize a decision.
        state = self._reader.read() if self._reader else None
        persisted = state.status if state else "initializing"
        outcome = classify_outcome(
            contract_error=self._contract_error,
            abort_requested=self._supervisor.abort_requested,
            reaped=condition.reaped,
            state=state,
            owned_process=self._supervisor.started_at is not None,
            read_only=self._read_only,
        )
        timings: dict = {}
        aggregator_diag = ""
        if self._log_aggregator is not None and run_id:
            timings = self._log_aggregator.update(self.runs_dir / run_id / "log.jsonl")
            aggregator_diag = self._log_aggregator.diagnostic

        with self._lock:
            if self._supervisor.abort_requested:
                status = "aborting" if not condition.reaped else "aborted"
            elif condition.live and persisted == "paused":
                # A resume has started but the engine has not replaced the
                # previous paused state file yet.
                status = "running"
            else:
                status = persisted
            if outcome is not None:
                status = outcome.kind.value

            if (
                condition.reaped
                and self._supervisor.last_reaped_command == "resume"
                and condition.exit_code not in (None, 0)
                and persisted == "paused"
            ):
                self._diagnostic = (
                    f"Structured resume exited with code {condition.exit_code}; "
                    "the persisted gate remains paused."
                )
            elif persisted != "paused":
                self._diagnostic = ""

            branch_error = self._branches.error
            stale = bool(state.stale) if state else False
            if branch_error:
                stale = True
            diagnostic = _combine(
                state.diagnostic if state else "",
                aggregator_diag,
                self._diagnostic,
                branch_error,
                self._claim_error,
            )

            elapsed = 0.0
            if self._supervisor.started_at is not None:
                end = self._ended_at if self._ended_at is not None else self._clock()
                elapsed = max(0.0, end - self._supervisor.started_at)

            definition = self._definition
            graph = self._graph
            workflow_name = definition.name if definition else ""
            inputs_tuple = tuple(state.inputs.items()) if state else ()
            gate = None
            if self._coordinator is not None:
                declared_id = None
                if graph is not None and state is not None:
                    declared_id = resolve_declared_id(state.current_step_id, graph.declared_ids)
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
                    graph, state, timings, lifecycle_status=lifecycle_status
                )
                if graph
                else None
            )
            return RunSnapshot(
                run_id=run_id,
                workflow_id=definition.id if definition else "",
                workflow_name=workflow_name,
                status=status,
                current_step_id=state.current_step_id if state else None,
                branch=self._branches.value,
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
                adopted=self._adopted,
                read_only=self._read_only,
                stale=stale,
                diagnostic=diagnostic,
                context_path=self._context_path,
                context_error=self._context_error,
            )

    def close(self) -> None:
        self._supervisor.close()
        if self.run_id and not self._read_only:
            # Any run this session owns releases its claim on a clean close; a
            # crash leaves the claim for liveness-based recovery (FR-013).
            self._claims.release(self.run_id, self._owner_id)
