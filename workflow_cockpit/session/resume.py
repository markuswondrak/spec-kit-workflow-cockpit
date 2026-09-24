"""Write-once resume lifecycle for an adopted paused or failed run.

The coordinator projects the single Resume affordance for a persisted-``failed``
run and serializes the one guarded engine resume behind an opaque, write-once
token. It mirrors the gate decision ledger: the attempt is reserved under the
lock before the engine boundary, and ``WRITTEN``/``UNCERTAIN`` consume it while
``NOT_WRITTEN`` releases it. The engine stays authoritative: Cockpit issues one
bare ``specify workflow resume <run_id>`` and re-reads persisted status, never
reimplementing the engine's step or nested-resume semantics.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from ..engine.pty_session import WriteOutcome
from ..engine.supervisor import (
    EngineSupervisor,
    ProcessCondition,
    StdinPolicy,
    SupervisorError,
    build_interactive_resume_argv,
)
from ..services.graph import ControlFlowGraph, resolve_declared_id
from ..services.run_state import RunStateData

#: Statuses the engine accepts as a resume precondition.
ELIGIBLE_STATUSES = frozenset({"paused", "failed"})

#: Status the Resume affordance is offered for in Cockpit.
RESUMABLE_STATUS = "failed"


class ResumeError(Exception):
    """Raised when a confirmed resume cannot be submitted."""


@dataclass(frozen=True)
class ResumeDecision:
    """The projected resume affordance for the current run snapshot."""

    available: bool
    reason: str = ""
    step_id: str | None = None
    step_label: str = ""
    nested: bool = False
    parent_label: str = ""
    token: str | None = None


class ResumeState(str, Enum):
    """Write-once state of one resume attempt."""

    READY = "ready"
    SUBMITTED = "submitted"
    UNVERIFIED = "unverified"


@dataclass
class ResumeAttempt:
    """One confirmation attempt and its write-once ledger entry."""

    key: tuple
    token: str
    state: ResumeState = ResumeState.READY
    reserved_at: float | None = None


@dataclass(frozen=True)
class ResumeResult:
    """Outcome of one engine resume boundary crossing."""

    outcome: WriteOutcome
    detail: str = ""


class ResumeCoordinator:
    """Own the resume projection and the write-once resume ledger."""

    def __init__(
        self,
        *,
        graph: ControlFlowGraph | None,
        supervisor: EngineSupervisor,
        executable: Path,
        adopted: bool = False,
        read_only: bool = False,
        clock: Callable[[], float],
        stdin: StdinPolicy = StdinPolicy.DEVNULL,
    ) -> None:
        self._graph = graph
        self._supervisor = supervisor
        self._executable = Path(executable)
        self._adopted = adopted
        self._read_only = read_only
        self._clock = clock
        self._stdin = StdinPolicy(stdin)
        self._lock = threading.RLock()
        self._attempt: ResumeAttempt | None = None

    def project(
        self,
        *,
        state: RunStateData | None,
        run_id: str | None,
        condition: ProcessCondition,
    ) -> ResumeDecision | None:
        with self._lock:
            return self._project(state, run_id, condition)

    def submit(
        self,
        *,
        token: str | None,
        state: RunStateData | None,
        run_id: str | None,
        condition: ProcessCondition,
    ) -> None:
        """Validate and submit exactly one confirmed resume."""
        with self._lock:
            self._submit(token=token, state=state, run_id=run_id, condition=condition)

    # -- projection ----------------------------------------------------

    def _project(
        self,
        state: RunStateData | None,
        run_id: str | None,
        condition: ProcessCondition,
    ) -> ResumeDecision | None:
        if state is None or not run_id or state.status != RESUMABLE_STATUS:
            # Any persisted status other than ``failed`` has no resume affordance.
            self._attempt = None
            return None
        key = (run_id, "resume")
        if self._attempt is not None and self._attempt.key != key:
            self._attempt = None
        if (
            self._attempt is not None
            and self._attempt.state is not ResumeState.READY
            and condition.reaped
            and not condition.live
        ):
            # The owned resume was reaped while the run is still failed: the
            # failure is fresh and a new confirmation may mint a new token.
            self._attempt = None
        decision = self._decision(state)
        if self._read_only:
            return replace(
                decision,
                available=False,
                token=None,
                reason="View-only mode: the run cannot be resumed.",
            )
        if not self._adopted:
            return replace(
                decision,
                available=False,
                token=None,
                reason="Only an adopted run can be resumed.",
            )
        if condition.live:
            return replace(
                decision,
                available=False,
                token=None,
                reason="The engine is running; wait for the run to stop before resuming.",
            )
        if self._attempt is None:
            self._attempt = ResumeAttempt(key=key, token=secrets.token_urlsafe(12))
        token = self._attempt.token if self._attempt.state is ResumeState.READY else None
        return replace(decision, available=True, token=token)

    def _decision(self, state: RunStateData) -> ResumeDecision:
        step_id, step_label, nested, parent_label = self._resume_point(state)
        return ResumeDecision(
            available=True,
            step_id=step_id,
            step_label=step_label,
            nested=nested,
            parent_label=parent_label,
        )

    def _resume_point(self, state: RunStateData) -> tuple[str | None, str, bool, str]:
        """Resolve the recorded current step to a declared node and its parent."""
        runtime_id = state.current_step_id
        step_id = runtime_id
        step_label = runtime_id or "—"
        if self._graph is None or not runtime_id:
            return step_id, step_label, False, ""
        declared = resolve_declared_id(runtime_id, self._graph.declared_ids)
        if declared is None:
            return step_id, step_label, False, ""
        step_id = declared
        node = self._graph.by_id.get(declared)
        if node is None:
            return step_id, step_label, False, ""
        step_label = node.label or node.id
        if node.parent_id:
            parent = self._graph.by_id.get(node.parent_id)
            if parent is not None:
                return step_id, step_label, True, parent.label or parent.id
        return step_id, step_label, False, ""

    # -- submission ----------------------------------------------------

    def _submit(
        self,
        *,
        token: str | None,
        state: RunStateData | None,
        run_id: str | None,
        condition: ProcessCondition,
    ) -> None:
        if self._read_only:
            raise ResumeError("Cannot resume a run in view-only mode.")
        if not self._adopted:
            raise ResumeError("Only an adopted run can be resumed.")
        if state is None or not run_id or state.status not in ELIGIBLE_STATUSES:
            persisted = state.status if state else "unavailable"
            raise ResumeError(
                "This run cannot be resumed: only a paused or failed run can be resumed; "
                f"this run is {persisted} and stays read-only."
            )
        attempt = self._attempt
        if (
            attempt is None
            or attempt.key != (run_id, "resume")
            or attempt.state is not ResumeState.READY
        ):
            raise ResumeError("This run has no pending resume; nothing was submitted.")
        if not token or token != attempt.token:
            raise ResumeError(
                "The resume request changed; this confirmation is stale and was not submitted."
            )
        # Reserve the attempt under the coordinator lock before the engine
        # boundary runs, so a concurrent confirmation cannot also write.
        attempt.reserved_at = self._clock()
        result = self._issue(run_id)
        if result.outcome is WriteOutcome.NOT_WRITTEN:
            # Zero bytes were written: release the reservation and report it.
            attempt.reserved_at = None
            raise ResumeError(result.detail or "The resume could not be submitted.")
        # Both complete and uncertain writes consume the attempt permanently.
        attempt.state = (
            ResumeState.SUBMITTED
            if result.outcome is WriteOutcome.WRITTEN
            else ResumeState.UNVERIFIED
        )

    def _issue(self, run_id: str) -> ResumeResult:
        argv = build_interactive_resume_argv(self._executable, run_id)
        try:
            self._supervisor.resume(run_id, argv, stdin=self._stdin)
        except SupervisorError as exc:
            return ResumeResult(WriteOutcome.NOT_WRITTEN, str(exc))
        return ResumeResult(WriteOutcome.WRITTEN)
