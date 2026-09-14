"""View model helpers mapping snapshots to renderable strings (no Textual)."""

from __future__ import annotations

from dataclasses import dataclass

from ..services.projection import GraphProjection
from ..services.snapshot import GateState, RunSnapshot

STATUS_GRAMMAR: dict[str, tuple[str, str]] = {
    "idle": ("[ ]", "IDLE"),
    "initializing": ("[>]", "STARTING"),
    "running": ("[>]", "RUNNING"),
    "paused": ("[!]", "PAUSED"),
    "awaiting": ("[!]", "AWAITING DECISION"),
    "aborting": ("[/]", "ABORTING"),
    "completed": ("[x]", "COMPLETE"),
    "success": ("[x]", "COMPLETE"),
    "failed": ("[X]", "FAILED"),
    "failure": ("[X]", "FAILED"),
    "aborted": ("[/]", "ABORTED"),
    "abort": ("[/]", "ABORTED"),
    "unknown": ("[ ]", "UNKNOWN"),
}


def state_grammar(status: str) -> tuple[str, str]:
    return STATUS_GRAMMAR.get(status, ("[ ]", status.upper() or "UNKNOWN"))


def format_elapsed(seconds: float) -> str:
    total = int(max(0.0, seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


DURATION_COLUMN = 8
"""Fixed width of the right-aligned elapsed column; gates never get one."""

TAIL_COLUMN = 8
"""Fixed width of the gate/attempt column between label and duration."""


@dataclass(frozen=True)
class RunwayRow:
    id: str
    text: str
    status: str
    active: bool


def default_focus_mode(snapshot: RunSnapshot) -> str:
    if snapshot.terminal:
        return "outcome"
    if snapshot.gate is not None:
        return "gate"
    return "output"


@dataclass(frozen=True)
class GateDecision:
    """Presentation decision for the current gate, free of Textual imports."""

    mode: str
    message: str
    notice: str
    tone: str
    options: tuple[str, ...]
    selectable: bool
    hint: str


def gate_decision(snapshot: RunSnapshot) -> GateDecision:
    """Resolve how the unified gate snapshot is presented.

    Transport is never consulted: the gate's presentation state decides
    whether choices are live. Declared options stay visible while submitted,
    unverified, or blocked, but only ``ready`` gates are selectable.
    """
    gate = snapshot.gate
    if gate is None:
        return GateDecision(
            "blocked",
            "The engine is paused.",
            "This pause is not a declared gate; only Abort is available.",
            "fog",
            (),
            False,
            "selection unavailable",
        )
    selectable = gate.selectable
    if gate.state is GateState.READY:
        notice = "Choose an option, then confirm. Opening files is optional."
        tone = "fog"
        hint = "1..N or enter  confirm selected"
    elif gate.state is GateState.SUBMITTED:
        notice = gate.acknowledged or (
            "Choice submitted once. Persisted engine state stays authoritative; "
            "waiting for it to advance."
        )
        tone = "hold"
        hint = "waiting for persisted state"
    elif gate.state is GateState.UNVERIFIED:
        notice = gate.acknowledged or (
            "CHOICE SENT, STATE NOT ADVANCED\n"
            "The choice was submitted once and will not be sent again. "
            "Expand Engine Output to inspect the prompt state."
        )
        tone = "fault"
        hint = "choices disabled  /  x  abort run"
    else:
        notice = gate.reason or "This gate cannot be decided; only Abort is available."
        tone = "fault"
        hint = "only x  abort run is available"
    return GateDecision(
        mode=gate.state.value,
        message=gate.message,
        notice=notice,
        tone=tone,
        options=gate.options,
        selectable=selectable,
        hint=hint,
    )


def _middle_truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit < 5:
        return value[:limit]
    left = (limit - 3) // 2
    return f"{value[:left]}...{value[-(limit - 3 - left) :]}"


def render_runway(projection: GraphProjection | None, *, width: int = 29) -> list[RunwayRow]:
    """Render graph data into stable, terminal-sized runway rows."""
    if projection is None:
        return []
    states = projection.by_id
    first_in_branch: set[tuple[str | None, str | None]] = set()
    rows: list[RunwayRow] = []
    for node in projection.graph.nodes:
        state = states[node.id]
        branch_key = (node.parent_id, node.branch)
        connector = ""
        if node.branch:
            connector = "+-- " if branch_key not in first_in_branch else "|   "
            first_in_branch.add(branch_key)
        prefix = "  " * node.depth + connector
        marker = {
            "pending": "[ ]",
            "running": "[>]",
            "paused": "[!]",
            "completed": "[x]",
            "skipped": "[-]",
            "failed": "[X]",
            "aborted": "[/]",
        }.get(state.status, "[ ]")
        meta: list[str] = []
        if node.gate:
            meta.append("gate")
        if state.attempts > 1:
            meta.append(f"#{state.attempts}")
        duration = ""
        if state.duration_seconds is not None and not node.gate:
            duration = format_elapsed(state.duration_seconds).rjust(DURATION_COLUMN)
        tail = ("  " + "  ".join(meta)) if meta else ""
        label_width = max(8, width - len(prefix) - len(marker) - 1 - TAIL_COLUMN - DURATION_COLUMN)
        label = _middle_truncate(node.label, label_width).ljust(label_width)
        body = f"{prefix}{marker} {label}{tail}"
        if duration:
            body = body.ljust(width - DURATION_COLUMN)
        rows.append(RunwayRow(node.id, body + duration, state.status, state.active))
    return rows


def header_fields(snapshot: RunSnapshot) -> dict[str, str]:
    status = "awaiting" if snapshot.awaiting_decision else snapshot.status
    _symbol, word = state_grammar(status)
    return {
        "word": word,
        "branch": snapshot.branch or "unknown",
        "elapsed": format_elapsed(snapshot.elapsed_seconds),
        "workflow": snapshot.workflow_name or snapshot.workflow_id or "workflow",
        "run": snapshot.abbreviated_run_id or "—",
    }
