"""Immutable snapshot value objects published by the polling loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .projection import GraphProjection
from .review import ReviewSnapshot
from .run_state import RunStateData


class OutcomeKind(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    ABORT = "abort"


@dataclass(frozen=True)
class Outcome:
    kind: OutcomeKind
    detail: str = ""
    step_id: str | None = None
    engine_status: str | None = None


@dataclass(frozen=True)
class GateSnapshot:
    """A declared gate paused in the persisted engine state."""

    runtime_step_id: str
    step_id: str | None
    message: str
    options: tuple[str, ...] = ()
    verdict_input: str | None = None
    on_reject: str | None = None
    malformed: bool = False
    error: str = ""

    @property
    def structured(self) -> bool:
        """True when S03 can submit a confirmed structured resume."""
        return bool(self.verdict_input) and not self.malformed and bool(self.options)


def extract_gate(state: RunStateData | None, declared_node) -> GateSnapshot | None:
    """Build a gate snapshot only from a persisted paused gate result.

    The persisted ``output`` supplies the resolved message and the exact
    option order. The declared graph node supplies ``verdict_input`` and
    ``on_reject`` because they are not written into the gate result.
    """
    if state is None or state.status != "paused":
        return None
    if declared_node is None or not getattr(declared_node, "gate", False):
        return None
    declared_id = declared_node.id
    result = state.current_result()
    if not isinstance(result, dict):
        return GateSnapshot(
            runtime_step_id=state.current_step_id or "",
            step_id=declared_id,
            message="Gate evidence is unavailable.",
            verdict_input=declared_node.verdict_input,
            on_reject=declared_node.on_reject,
            malformed=True,
            error="The persisted gate result is missing.",
        )
    if result.get("type") != "gate":
        return GateSnapshot(
            runtime_step_id=state.current_step_id or "",
            step_id=declared_id,
            message="Gate evidence is unavailable.",
            verdict_input=declared_node.verdict_input,
            on_reject=declared_node.on_reject,
            malformed=True,
            error="The persisted current-step result is not a gate.",
        )
    output = result.get("output")
    if not isinstance(output, dict):
        return GateSnapshot(
            runtime_step_id=state.current_step_id or "",
            step_id=declared_id,
            message="Gate evidence is unavailable.",
            verdict_input=declared_node.verdict_input,
            on_reject=declared_node.on_reject,
            malformed=True,
            error="The persisted gate output is malformed.",
        )
    raw_message = output.get("message")
    valid_message = isinstance(raw_message, str) and bool(raw_message)
    message = raw_message if valid_message else "Gate evidence is unavailable."
    raw_options = output.get("options")
    if isinstance(raw_options, list):
        valid_options = all(isinstance(item, str) for item in raw_options)
        options = tuple(item for item in raw_options if isinstance(item, str))
        malformed = not valid_message or not valid_options or not options
    else:
        options = ()
        malformed = True
    if not valid_message:
        error = "The persisted gate message is missing or malformed."
    elif malformed:
        error = "The persisted gate options are missing or malformed."
    else:
        error = ""
    return GateSnapshot(
        runtime_step_id=state.current_step_id or "",
        step_id=declared_id,
        message=message,
        options=options,
        verdict_input=declared_node.verdict_input,
        on_reject=declared_node.on_reject,
        malformed=malformed,
        error=error,
    )


@dataclass(frozen=True)
class RunSnapshot:
    """Everything Cockpit presents about one run at one instant."""

    run_id: str
    workflow_id: str = ""
    workflow_name: str = ""
    status: str = "initializing"
    current_step_id: str | None = None
    branch: str | None = None
    elapsed_seconds: float = 0.0
    output_tail: tuple[str, ...] = ()
    partial_line: str = ""
    output_emitted: int = 0
    process_live: bool = False
    engine_status: str | None = None
    engine_error: str | None = None
    outcome: Outcome | None = None
    stale: bool = False
    inputs: tuple[tuple[str, Any], ...] = field(default_factory=tuple)
    graph_projection: GraphProjection | None = None
    gate: GateSnapshot | None = None
    review: ReviewSnapshot | None = None
    reviewing: bool = False
    diagnostic: str = ""

    @property
    def terminal(self) -> bool:
        return self.outcome is not None

    @property
    def abbreviated_run_id(self) -> str:
        return self.run_id[:8] if self.run_id else ""
