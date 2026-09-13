"""Immutable snapshot value objects published by the polling loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .projection import GraphProjection


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
class RunSnapshot:
    """Everything S01 presents about one run at one instant."""

    run_id: str
    workflow_id: str = ""
    workflow_name: str = ""
    status: str = "initializing"
    current_step_id: str | None = None
    branch: str | None = None
    baseline_commit: str | None = None
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

    @property
    def terminal(self) -> bool:
        return self.outcome is not None

    @property
    def abbreviated_run_id(self) -> str:
        return self.run_id[:8] if self.run_id else ""
