"""View model helpers mapping snapshots to renderable strings (no Textual)."""

from __future__ import annotations

from dataclasses import dataclass

from ..services.graph import resolve_declared_id
from ..services.projection import GraphProjection, NodeState
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


def format_duration(seconds: float) -> str:
    """Inline runway duration: ``(MM:SS)``, or a lone ``-`` when it took no time."""
    if int(max(0.0, seconds)) == 0:
        return "-"
    return f"({format_elapsed(seconds)})"


TAIL_COLUMN = 8
"""Fixed width of the gate/attempt tail that follows a label."""


@dataclass(frozen=True)
class RunwayRow:
    id: str
    text: str
    status: str
    active: bool
    full_label: str = ""
    #: Scope-qualified identity, so a nested row is distinct from a root one.
    key: tuple = ()
    #: Display scope path for a nested row (``review-release > review``).
    scope_path: str = ""
    #: A handled ``continue_on_error`` call failure.
    handled: bool = False


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
    #: The scope the gate lives in, e.g. ``review-release > review`` ("" at root).
    scope_line: str = ""


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
    scope_line = f"scope {gate.display_scope_path}" if gate.nested else ""
    return GateDecision(
        mode=gate.state.value,
        message=gate.message,
        notice=notice,
        tone=tone,
        options=gate.options,
        selectable=selectable,
        hint=hint,
        affordance=affordance,
        scope_line=scope_line,
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


def _row_key(node) -> tuple:
    return node.key if node.key else (node.id,)


def render_runway(projection: GraphProjection | None, *, width: int = 36) -> list[RunwayRow]:
    """Render graph data into stable, terminal-sized runway rows."""
    if projection is None:
        return []
    states = projection.by_key or projection.by_id
    current_key = projection.current_node_key
    first_in_branch: set[tuple[str | None, str | None]] = set()
    rows: list[RunwayRow] = []
    for node in projection.graph.nodes:
        key = _row_key(node)
        state = states.get(key) or states.get(node.id) or NodeState(id=node.id, key=key)
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
            "blocked": "[!]",
        }.get(state.status, "[ ]")
        meta: list[str] = []
        if node.gate:
            meta.append("gate")
        if node.is_call and not node.target_resolved:
            meta.append("target not yet resolved")
        if state.handled:
            meta.append("handled")
        if state.attempts > 1:
            meta.append(f"#{state.attempts}")
        scope_path = " > ".join(str(part) for part in key)
        if len(key) > 1:
            meta.append("in " + " > ".join(str(part) for part in key[:-1]))
        active = state.active or (current_key is not None and key == current_key)
        is_current = current_key is not None and key == current_key
        if not is_current and len(key) == 1 and projection.current_node_id is not None:
            is_current = node.id == projection.current_node_id
        show_duration = (
            state.duration_seconds is not None
            and not node.gate
            and (is_current or state.status == "completed")
        )
        tail = ("  " + "  ".join(meta)) if meta else ""
        duration = format_duration(state.duration_seconds) if show_duration else ""
        # The elapsed value is right-aligned to the row's trailing edge, so its
        # columns are reserved out of the label budget and the row never grows
        # past `width`.
        fixed = len(prefix) + len(marker) + 1 + len(tail)
        duration_width = len(duration) + 1 if duration else 0
        if duration and fixed + duration_width + 8 > width:
            duration = ""
            duration_width = 0
        label_width = max(8, width - fixed - duration_width)
        label = _tail_truncate(node.label, label_width).ljust(label_width)
        body = f"{prefix}{marker} {label}{tail}"
        if duration:
            body += " " * max(1, width - len(body) - len(duration)) + duration
        rows.append(
            RunwayRow(
                node.id if len(key) == 1 else ">".join(str(part) for part in key),
                body,
                state.status,
                active,
                node.label,
                key=key,
                scope_path=scope_path,
                handled=state.handled,
            )
        )
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
