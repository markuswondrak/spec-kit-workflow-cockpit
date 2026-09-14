"""Immutable snapshot value objects published by the polling loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .projection import GraphProjection
from .review import ReviewSnapshot


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


class GateState(str, Enum):
    """Transport-independent presentation state of one current declared gate."""

    READY = "ready"
    SUBMITTED = "submitted"
    UNVERIFIED = "unverified"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class GateSnapshot:
    """One current declared gate, regardless of how its decision is transported.

    The UI knows only this object: the resolved message and declared options,
    a presentation ``state``, an opaque ``token`` when a confirmed choice is
    allowed, and either an acknowledgement or a blocked ``reason``. Whether a
    confirmation becomes a structured resume or one PTY write is never exposed.
    """

    runtime_step_id: str
    step_id: str | None
    message: str
    options: tuple[str, ...] = ()
    on_reject: str | None = None
    state: GateState = GateState.BLOCKED
    token: str | None = None
    reason: str = ""
    acknowledged: str = ""

    @property
    def selectable(self) -> bool:
        """True only when a confirmed declared choice may be submitted."""
        return self.state is GateState.READY and bool(self.token)


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
    def awaiting_decision(self) -> bool:
        """A current declared gate is waiting, whatever its raw engine status."""
        return self.gate is not None and not self.terminal

    @property
    def abbreviated_run_id(self) -> str:
        return self.run_id[:8] if self.run_id else ""
