"""Unified gate decision coordinator.

The coordinator owns the decision state machine. It projects the current
persisted state, declared graph node, process condition, and verified engine
contract into one :class:`GateSnapshot`; selects the structured or PTY
transport internally; issues and validates opaque decision tokens; serializes
submission, the write-once ledger, and Abort visibility; and reconciles
submitted, unverified, and advanced attempts without ever trusting
``updated_at`` as an attempt identity.
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
from ..engine.supervisor import EngineSupervisor, ProcessCondition, StdinPolicy
from ..services.graph import ControlFlowGraph, GraphNode, resolve_declared_id
from ..services.run_state import RunStateData
from ..services.snapshot import GateSnapshot, GateState

#: Bounded post-submission watch (about 40 ticks at the 250 ms cadence).
SUBMISSION_WATCH_SECONDS = 10.0

_PARALLEL_TYPES = frozenset({"while", "do-while", "fan-out"})


class GateDecisionError(Exception):
    """Raised when a confirmed gate decision cannot be submitted."""


@dataclass(frozen=True)
class ShapeSupport:
    """Whether an effective workflow's gates can be decided, and how."""

    ok: bool
    stdin: StdinPolicy
    error: str = ""


def _is_dynamic(value: str) -> bool:
    return "{{" in value


def _nested_in_parallel(graph: ControlFlowGraph, node: GraphNode) -> bool:
    """True when a gate executes under a loop or fan-out container."""
    by_id = graph.by_id
    parent_id = node.parent_id
    while parent_id is not None:
        parent = by_id.get(parent_id)
        if parent is None:
            return False
        if parent.type in _PARALLEL_TYPES:
            return True
        parent_id = parent.parent_id
    return False


def validate_shape(
    graph: ControlFlowGraph | None,
    version: object,
) -> ShapeSupport:
    """Validate the effective workflow before Start.

    Interactive gates change the stdin policy for the whole child, so mixed
    workflows, dynamic interactive values, retry over the PTY, and parallel or
    looped interactive gates are rejected with an actionable error rather than
    started and left undecidable later. Structured-only workflows keep the
    non-TTY policy and are always supported.
    """
    if graph is None:
        return ShapeSupport(True, StdinPolicy.DEVNULL)
    gates = [node for node in graph.nodes if node.gate]
    non_verdict = [node for node in gates if not node.verdict_input]
    if not non_verdict:
        return ShapeSupport(True, StdinPolicy.DEVNULL)

    contract = resolve_contract(version)
    if any(node.verdict_input for node in gates):
        return ShapeSupport(
            False,
            StdinPolicy.DEVNULL,
            "Workflows that mix gates with and without verdict_input cannot be decided "
            "safely; remove one gate type or split the workflow.",
        )
    if contract is None:
        return ShapeSupport(
            False,
            StdinPolicy.DEVNULL,
            f"Interactive gates are not verified for specify {version}; this workflow "
            "would be undecidable. Upgrade or use a workflow with verdict_input gates.",
        )
    for node in non_verdict:
        if _nested_in_parallel(graph, node):
            return ShapeSupport(
                False,
                StdinPolicy.DEVNULL,
                f"Gate {node.id!r} runs inside a loop or fan-out, where interactive prompt "
                "ownership is not deterministic; make the gate sequential.",
            )
        if node.on_reject == "retry":
            return ShapeSupport(
                False,
                StdinPolicy.DEVNULL,
                f"Gate {node.id!r} uses on_reject: retry, which requires re-prompting across "
                "processes and is not supported for interactive gates; use skip or abort, or "
                "a verdict_input gate.",
            )
        if _is_dynamic(node.message) or any(_is_dynamic(option) for option in node.options):
            return ShapeSupport(
                False,
                StdinPolicy.DEVNULL,
                f"Gate {node.id!r} uses dynamic message or options that cannot be verified "
                "before Start; make them static or use a verdict_input gate.",
            )
        if not node.options:
            return ShapeSupport(
                False,
                StdinPolicy.DEVNULL,
                f"Gate {node.id!r} declares no options; interactive decisions need explicit options.",
            )
    return ShapeSupport(True, StdinPolicy.PTY)


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
    ) -> None:
        self._graph = graph
        self._supervisor = supervisor
        self._version = version
        self._contract = resolve_contract(version) if contract is None else contract
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

    def _declared_node(self, runtime_id: str | None) -> GraphNode | None:
        if self._graph is None or not runtime_id:
            return None
        declared_id = resolve_declared_id(runtime_id, self._graph.declared_ids)
        return self._graph.by_id.get(declared_id) if declared_id else None

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
        node = self._declared_node(state.current_step_id if state else None)
        if state is None or not run_id or node is None or not node.gate:
            self._attempt = None
            return None
        kind = "structured" if node.verdict_input else "interactive"
        key = (run_id, node.id, kind, gate_attempt)
        if self._attempt is not None and self._attempt.key != key:
            # The run left the consumed attempt or began a new execution.
            self._attempt = None
        runtime_id = state.current_step_id or node.id
        if kind == "structured":
            return self._project_structured(state, node, runtime_id, condition, key)
        return self._project_interactive(state, node, runtime_id, condition, key)

    def _project_structured(
        self,
        state: RunStateData,
        node: GraphNode,
        runtime_id: str,
        condition: ProcessCondition,
        key: tuple,
    ) -> GateSnapshot:
        message, options, reason = self._structured_evidence(state, node)
        if self._attempt is not None and self._attempt.state is not GateState.READY:
            return self._attempt_snapshot(node, runtime_id, message, options)
        if reason:
            return self._blocked(node, runtime_id, message, options, reason)
        if state.status != "paused":
            return self._blocked(
                node,
                runtime_id,
                message,
                options,
                "The persisted gate is not paused; only Abort is available.",
            )
        if condition.live:
            return self._blocked(
                node,
                runtime_id,
                message,
                options,
                "The engine is still running; wait for the gate to pause.",
            )
        if self._attempt is None:
            self._attempt = self._new_attempt(key)
        return self._attempt_snapshot(node, runtime_id, message, options)

    def _project_interactive(
        self,
        state: RunStateData,
        node: GraphNode,
        runtime_id: str,
        condition: ProcessCondition,
        key: tuple,
    ) -> GateSnapshot:
        message = node.message or "Review required."
        options = node.options
        if self._attempt is not None and self._attempt.state is not GateState.READY:
            return self._attempt_snapshot(node, runtime_id, message, options)
        reason = self._interactive_blocked_reason(state, condition)
        if reason:
            return self._blocked(node, runtime_id, message, options, reason)
        if self._attempt is None:
            self._attempt = self._new_attempt(key)
        return self._attempt_snapshot(node, runtime_id, message, options)

    def _interactive_blocked_reason(
        self, state: RunStateData, condition: ProcessCondition
    ) -> str:
        if self._contract is None:
            return (
                f"Interactive prompt readiness is not verified for specify {self._version}; "
                "only Abort is available."
            )
        if not state.complete or state.status != "running":
            return "The engine is not waiting at this gate; only Abort is available."
        if condition.aborting:
            return "This run is aborting; only Abort is available."
        if not condition.live:
            return "No live engine process is waiting at this gate; only Abort is available."
        if not condition.stdin_pty:
            return (
                "The engine process was not started with an interactive prompt; only Abort is available."
            )
        return ""

    def _structured_evidence(
        self, state: RunStateData, node: GraphNode
    ) -> tuple[str, tuple[str, ...], str]:
        """Resolve message/options from authoritative persisted evidence."""
        result = state.current_result()
        declared_message = node.message or "Gate evidence is unavailable."
        declared_options = node.options
        if state.status != "paused":
            return declared_message, declared_options, ""
        if not isinstance(result, dict) or result.get("type") != "gate":
            return (
                declared_message,
                declared_options,
                "The persisted gate evidence is unavailable; only Abort is available.",
            )
        output = result.get("output")
        if not isinstance(output, dict):
            return (
                declared_message,
                declared_options,
                "The persisted gate output is malformed; only Abort is available.",
            )
        raw_message = output.get("message")
        valid_message = isinstance(raw_message, str) and bool(raw_message)
        message = raw_message if valid_message else declared_message
        raw_options = output.get("options")
        if isinstance(raw_options, list):
            options = tuple(item for item in raw_options if isinstance(item, str))
            valid_options = len(options) == len(raw_options) and bool(options)
        else:
            options = ()
            valid_options = False
        if not valid_options:
            options = options or declared_options
        if not valid_message:
            return message, options, "The persisted gate message is missing or malformed; only Abort is available."
        if not valid_options:
            return message, options, "The persisted gate options are missing or malformed; only Abort is available."
        return message, options, ""

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
        node = self._declared_node(state.current_step_id if state else None)
        if node is None or not node.gate or self._attempt is None:
            raise GateDecisionError("The gate attempt is no longer available.")
        attempt = self._attempt
        # Reserve the attempt under the coordinator lock before the engine
        # boundary runs, so a concurrent confirmation cannot also write.
        attempt.choice = choice
        attempt.written_at = self._clock()
        result = self._decide(node, run_id or "", choice, gate.options)
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
        self, node: GraphNode, run_id: str, choice: str, options: tuple[str, ...]
    ) -> DecisionResult:
        if node.verdict_input:
            return self._verdict_decider.submit(
                run_id=run_id, verdict_input=node.verdict_input, choice=choice
            )
        if self._pty_decider is None:
            return DecisionResult(WriteOutcome.NOT_WRITTEN, "Interactive submission is unavailable.")
        return self._pty_decider.submit(choice=choice, options=options)

    # -- snapshots -----------------------------------------------------

    def _new_attempt(self, key: tuple) -> _Attempt:
        return _Attempt(key=key, token=secrets.token_urlsafe(12))

    def _attempt_snapshot(
        self, node: GraphNode, runtime_id: str, message: str, options: tuple[str, ...]
    ) -> GateSnapshot:
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
        return GateSnapshot(
            runtime_step_id=runtime_id,
            step_id=node.id,
            message=message,
            options=options,
            on_reject=node.on_reject,
            state=state,
            token=(attempt.token if state is GateState.READY else None),
            acknowledged=acknowledged,
        )

    def _blocked(
        self,
        node: GraphNode,
        runtime_id: str,
        message: str,
        options: tuple[str, ...],
        reason: str,
    ) -> GateSnapshot:
        return GateSnapshot(
            runtime_step_id=runtime_id,
            step_id=node.id,
            message=message,
            options=options,
            on_reject=node.on_reject,
            state=GateState.BLOCKED,
            reason=reason,
        )
