"""View model helpers mapping snapshots to renderable strings (no Textual)."""

from __future__ import annotations

from dataclasses import dataclass

from ..services.graph import resolve_declared_id
from ..services.projection import GraphProjection
from ..services.snapshot import GateState, RunSnapshot
from ..session.resume import ResumeDecision

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


TAIL_COLUMN = 8
"""Fixed width of the gate/attempt tail that follows a label."""


@dataclass(frozen=True)
class RunwayRow:
    id: str
    text: str
    status: str
    active: bool
    full_label: str = ""


def default_focus_mode(snapshot: RunSnapshot) -> str:
    if snapshot.terminal:
        return "outcome"
    if snapshot.gate is not None:
        return "gate"
    return "output"


GATE_BUTTON_LIMIT = 3
"""Declared choices at or below this count render as equal-weight buttons."""


def gate_affordance(options: tuple[str, ...] | list[str]) -> str:
    """Select the gate decision affordance from the declared choice count.

    ``none`` for zero choices, ``buttons`` for one to ``GATE_BUTTON_LIMIT``,
    and ``select`` for more. The boundary is inclusive at three.
    """
    if not options:
        return "none"
    return "buttons" if len(options) <= GATE_BUTTON_LIMIT else "select"


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
    affordance: str


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
            "none",
        )
    selectable = gate.selectable
    affordance = gate_affordance(gate.options)
    if gate.state is GateState.READY:
        notice = "Choose an option, then confirm. Opening files is optional."
        tone = "fog"
        if affordance == "select":
            hint = "1..N/enter confirm  down open"
        else:
            hint = "1..N/enter confirm  left/right"
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
        affordance=affordance,
    )


def resume_decision(snapshot: RunSnapshot) -> ResumeDecision:
    """Resolve the Resume affordance for an adopted, non-read-only failed run.

    Availability and the named resume point are derived from the snapshot only;
    the write-once token comes from the coordinator through the session. A
    missing declaration degrades to the raw runtime id and no nested parent.
    """
    if not snapshot.adopted:
        return ResumeDecision(False, reason="Only an adopted run can be resumed.")
    if snapshot.read_only:
        return ResumeDecision(False, reason="View-only mode: the run cannot be resumed.")
    if snapshot.engine_status != "failed":
        return ResumeDecision(False, reason="The run is not in a failed state.")
    step_id = snapshot.current_step_id
    step_label = step_id or "—"
    nested = False
    parent_label = ""
    projection = snapshot.graph_projection
    if projection is not None and step_id:
        declared = resolve_declared_id(step_id, projection.graph.declared_ids)
        node = projection.graph.by_id.get(declared) if declared is not None else None
        if node is not None:
            step_id = declared
            step_label = node.label or node.id
            if node.parent_id:
                parent = projection.graph.by_id.get(node.parent_id)
                if parent is not None:
                    nested = True
                    parent_label = parent.label or parent.id
    return ResumeDecision(
        available=True,
        step_id=step_id,
        step_label=step_label,
        nested=nested,
        parent_label=parent_label,
    )


def _tail_truncate(value: str, limit: int) -> str:
    """Clip a label to ``limit`` columns, preserving its identifying prefix.

    Tail truncation keeps the leading identifier (e.g. ``assessment-...``) that
    distinguishes sibling steps, unlike middle truncation which drops it.
    """
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


def render_runway(projection: GraphProjection | None, *, width: int = 36) -> list[RunwayRow]:
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
        active = node.id == projection.current_node_id
        show_duration = (
            state.duration_seconds is not None
            and not node.gate
            and (active or state.status == "completed")
        )
        tail = ("  " + "  ".join(meta)) if meta else ""
        # Reserve only the columns this row actually renders. The elapsed value
        # rides inline after the label, so no fixed duration column is carved
        # out of the label budget.
        tail_width = len(tail) if tail else 0
        label_width = max(8, width - len(prefix) - len(marker) - 1 - tail_width)
        label = _tail_truncate(node.label, label_width).ljust(label_width)
        body = f"{prefix}{marker} {label}{tail}"
        if show_duration:
            body += f" ({format_elapsed(state.duration_seconds)})"
        rows.append(RunwayRow(node.id, body, state.status, state.active, node.label))
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
