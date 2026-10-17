"""Unified gate decision coordinator.

The coordinator owns the decision state machine. It projects the current
persisted state, the resolved gate target (declared node or execution-tree
active node), the process condition, and the verified engine contract into one
:class:`GateSnapshot`; selects the structured or PTY transport internally;
issues and validates opaque decision tokens; serializes submission, the
write-once ledger, and Abort visibility; and reconciles submitted, unverified,
and advanced attempts without ever trusting ``updated_at`` as an attempt
identity.

The write-once ledger is keyed per scope occurrence, so a root gate and a
same-named child gate, or the same child called twice, can never share or
block each other's attempt (FR-008).
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..engine.gate_decider import DecisionResult, InternalPtyDecider, VerdictInputDecider
from ..engine.interactive_contract import PromptContract, resolve_contract
from ..engine.pty_session import WriteOutcome
from ..engine.supervisor import (
    EngineSupervisor,
    ProcessCondition,
    StdinPolicy,
    SupervisorError,
    build_interactive_resume_argv,
)
from ..services.gate_target import GateTarget, resolve_gate_target
from ..services.graph import ControlFlowGraph
from ..services.run_state import RunStateData
from ..services.shape_rules import ShapeSupport, validate_shape
from ..services.snapshot import GateSnapshot, GateState

#: Bounded post-submission watch (about 40 ticks at the 250 ms cadence).
SUBMISSION_WATCH_SECONDS = 10.0

__all__ = [
    "GateDecisionCoordinator",
    "GateDecisionError",
    "ShapeSupport",
    "SUBMISSION_WATCH_SECONDS",
    "validate_shape",
]


class GateDecisionError(Exception):
    """Raised when a confirmed gate decision cannot be submitted."""


@dataclass
class _Attempt:
    """One gate execution attempt and its write-once ledger entry."""

    key: tuple
    token: str
    state: GateState = GateState.READY
    choice: str | None = None
    written_at: float | None = None


class GateDecisionCoordinator:
    """Own the unified gate projection and the write-once decision ledger."""

    def __init__(
        self,
        *,
        graph: ControlFlowGraph | None,
        supervisor: EngineSupervisor,
        executable: Path,
        version: object,
        clock: Callable[[], float],
        contract: PromptContract | None = None,
        watch_seconds: float = SUBMISSION_WATCH_SECONDS,
        adopted: bool = False,
        read_only: bool = False,
    ) -> None:
        self._graph = graph
        self._supervisor = supervisor
        self._executable = Path(executable)
        self._version = version
        self._contract = resolve_contract(version) if contract is None else contract
        self._adopted = adopted
        self._read_only = read_only
        self._clock = clock
        self._watch_seconds = watch_seconds
        self._verdict_decider = VerdictInputDecider(executable, supervisor)
        self._pty_decider = (
            InternalPtyDecider(self._contract, supervisor) if self._contract is not None else None
        )
        self._lock = threading.RLock()
        self._attempt: _Attempt | None = None

    @property
    def contract(self) -> PromptContract | None:
        return self._contract

    def target(self, state: RunStateData | None) -> GateTarget | None:
        """The current gate target, resolution rules included."""
        return resolve_gate_target(state, self._graph)

    def project(
        self,
        *,
        state: RunStateData | None,
        run_id: str | None,
        condition: ProcessCondition,
        gate_attempt: int = 0,
    ) -> GateSnapshot | None:
        with self._lock:
            return self._project(state, run_id, condition, gate_attempt)

    def submit(
        self,
        *,
        choice: str,
        token: str | None,
        state: RunStateData | None,
        run_id: str | None,
        condition: ProcessCondition,
        gate_attempt: int = 0,
    ) -> None:
        """Validate and submit exactly one confirmed declared choice."""
        with self._lock:
            self._submit(
                choice=choice,
                token=token,
                state=state,
                run_id=run_id,
                condition=condition,
                gate_attempt=gate_attempt,
            )

    # -- projection ----------------------------------------------------

    def _project(
        self,
        state: RunStateData | None,
        run_id: str | None,
        condition: ProcessCondition,
        gate_attempt: int,
    ) -> GateSnapshot | None:
        target = self.target(state)
        if state is None or not run_id or target is None:
            self._attempt = None
            return None
        if target.blocked:
            # A gate Cockpit cannot decide never mints a token.
            self._attempt = None
            return self._snapshot(target, GateState.BLOCKED, reason=target.reason)
        key = (
            run_id,
            target.scope_path,
            target.step_id,
            target.occurrence,
            target.kind,
            gate_attempt,
        )
        if self._attempt is not None and self._attempt.key != key:
            # The run left the consumed attempt or began a new execution.
            self._attempt = None
        if self._read_only:
            return self._snapshot(
                target,
                GateState.BLOCKED,
                reason="View-only mode: gate decisions cannot be submitted.",
            )
        if target.kind == "structured":
            return self._project_structured(state, target, condition, key)
        return self._project_interactive(state, target, condition, key)

    def _project_structured(
        self,
        state: RunStateData,
        target: GateTarget,
        condition: ProcessCondition,
        key: tuple,
    ) -> GateSnapshot:
        if self._attempt is not None and self._attempt.state is not GateState.READY:
            return self._attempt_snapshot(target)
        if state.status != "paused":
            return self._snapshot(
                target,
                GateState.BLOCKED,
                reason="The persisted gate is not paused; only Abort is available.",
            )
        if condition.live:
            return self._snapshot(
                target,
                GateState.BLOCKED,
                reason="The engine is still running; wait for the gate to pause.",
            )
        if self._attempt is None:
            self._attempt = self._new_attempt(key)
        return self._attempt_snapshot(target)

    def _project_interactive(
        self,
        state: RunStateData,
        target: GateTarget,
        condition: ProcessCondition,
        key: tuple,
    ) -> GateSnapshot:
        if self._attempt is not None and self._attempt.state is not GateState.READY:
            return self._attempt_snapshot(target)
        reason = self._interactive_blocked_reason(state, condition)
        if reason:
            return self._snapshot(target, GateState.BLOCKED, reason=reason)
        if self._attempt is None:
            self._attempt = self._new_attempt(key)
        return self._attempt_snapshot(target)

    def _interactive_blocked_reason(
        self, state: RunStateData, condition: ProcessCondition
    ) -> str:
        if self._contract is None:
            return (
                f"The specify version {self._version!r} could not be mapped to an interactive "
                "prompt; only Abort is available."
            )
        if condition.aborting:
            return "This run is aborting; only Abort is available."
        if self._adopted:
            # An adopted paused run has no live process until the single guarded
            # resume is spawned on confirmation; a live resumed child is then
            # treated exactly like a started interactive gate.
            if state.status == "paused":
                return ""
            if state.status == "running" and condition.live and condition.stdin_pty:
                return ""
            if state.status == "running":
                return "The engine is not waiting at this gate; only Abort is available."
            return "The engine is not waiting at this gate; only Abort is available."
        if not state.complete or state.status != "running":
            return "The engine is not waiting at this gate; only Abort is available."
        if not condition.live:
            return "No live engine process is waiting at this gate; only Abort is available."
        if not condition.stdin_pty:
            return (
                "The engine process was not started with an interactive prompt; only Abort is available."
            )
        return ""

    # -- submission ----------------------------------------------------

    def _submit(
        self,
        *,
        choice: str,
        token: str | None,
        state: RunStateData | None,
        run_id: str | None,
        condition: ProcessCondition,
        gate_attempt: int,
    ) -> None:
        if self._read_only:
            raise GateDecisionError("Cannot submit decisions in view-only mode.")
        gate = self._project(state, run_id, condition, gate_attempt)
        if gate is None:
            raise GateDecisionError("The run is not at a declared gate.")
        if gate.state is not GateState.READY or not gate.token:
            raise GateDecisionError(gate.reason or "This gate cannot be decided.")
        if not token or token != gate.token:
            raise GateDecisionError(
                "The gate changed; this decision is stale and was not submitted."
            )
        if choice not in gate.options:
            raise GateDecisionError(f"{choice!r} is not one of the declared gate options.")
        target = self.target(state)
        if target is None or target.blocked or self._attempt is None:
            raise GateDecisionError("The gate attempt is no longer available.")
        attempt = self._attempt
        # Reserve the attempt under the coordinator lock before the engine
        # boundary runs, so a concurrent confirmation cannot also write.
        attempt.choice = choice
        attempt.written_at = self._clock()
        result = self._decide(target, run_id or "", choice, gate.options)
        if result.result is WriteOutcome.NOT_WRITTEN:
            # Zero bytes were written: release the reservation and report it.
            attempt.choice = None
            attempt.written_at = None
            raise GateDecisionError(result.detail or "The decision could not be submitted.")
        # Both complete and uncertain writes consume the attempt permanently.
        attempt.state = (
            GateState.SUBMITTED
            if result.result is WriteOutcome.WRITTEN
            else GateState.UNVERIFIED
        )

    def _decide(
        self, target: GateTarget, run_id: str, choice: str, options: tuple[str, ...]
    ) -> DecisionResult:
        if target.kind == "structured":
            verdict_input = target.root_input or target.verdict_input
            if not verdict_input:
                return DecisionResult(
                    WriteOutcome.NOT_WRITTEN,
                    "The gate's verdict input could not be traced to a root input.",
                )
            return self._verdict_decider.submit(
                run_id=run_id, verdict_input=verdict_input, choice=choice
            )
        if self._pty_decider is None:
            return DecisionResult(WriteOutcome.NOT_WRITTEN, "Interactive submission is unavailable.")
        if self._adopted and not self._supervisor.verify_live():
            # Exactly one guarded resume; the PTY buffers the choice until the
            # resumed prompt reads it. A spawn failure writes nothing.
            try:
                self._supervisor.resume(
                    run_id,
                    build_interactive_resume_argv(self._executable, run_id),
                    stdin=StdinPolicy.PTY,
                )
            except SupervisorError as exc:
                return DecisionResult(WriteOutcome.NOT_WRITTEN, str(exc))
        return self._pty_decider.submit(choice=choice, options=options)

    # -- snapshots -----------------------------------------------------

    def _new_attempt(self, key: tuple) -> _Attempt:
        return _Attempt(key=key, token=secrets.token_urlsafe(12))

    def _attempt_snapshot(self, target: GateTarget) -> GateSnapshot:
        attempt = self._attempt
        if attempt is None:
            raise GateDecisionError("The gate attempt is no longer available.")
        state = attempt.state
        acknowledged = ""
        if state is GateState.SUBMITTED:
            written_at = attempt.written_at or 0.0
            if self._clock() - written_at >= self._watch_seconds:
                attempt.state = GateState.UNVERIFIED
                state = GateState.UNVERIFIED
            else:
                acknowledged = (
                    "Choice submitted once. Persisted engine state stays authoritative; "
                    "waiting for it to advance."
                )
        if state is GateState.UNVERIFIED:
            acknowledged = (
                "CHOICE SENT, STATE NOT ADVANCED\n"
                "The choice was submitted once and will not be sent again. "
                "Expand Engine Output to inspect the prompt state."
            )
        return self._snapshot(
            target,
            state,
            acknowledged=acknowledged,
            token=(attempt.token if state is GateState.READY else None),
        )

    def _snapshot(
        self,
        target: GateTarget,
        state: GateState,
        *,
        reason: str = "",
        acknowledged: str = "",
        token: str | None = None,
    ) -> GateSnapshot:
        return GateSnapshot(
            runtime_step_id=target.runtime_step_id or target.step_id,
            step_id=target.step_id or None,
            message=target.message,
            options=target.options,
            on_reject=target.on_reject,
            state=state,
            token=token,
            reason=reason,
            acknowledged=acknowledged,
            scope_path=target.scope_path,
            root_input=target.root_input,
            reason_kind=target.reason_kind,
        )
