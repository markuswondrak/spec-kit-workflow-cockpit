"""View model helpers mapping snapshots to renderable strings (no Textual)."""

from __future__ import annotations

from dataclasses import dataclass

from ..services.projection import GraphProjection
from ..services.snapshot import RunSnapshot

STATUS_GRAMMAR: dict[str, tuple[str, str]] = {
    "idle": ("[ ]", "IDLE"),
    "initializing": ("[>]", "STARTING"),
    "running": ("[>]", "RUNNING"),
    "paused": ("[!]", "PAUSED"),
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


@dataclass(frozen=True)
class RunwayRow:
    id: str
    text: str
    status: str
    active: bool


def default_focus_mode(snapshot: RunSnapshot) -> str:
    if snapshot.terminal:
        return "outcome"
    if snapshot.status == "paused":
        return "gate"
    return "output"


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
        if state.duration_seconds is not None:
            meta.append(format_elapsed(state.duration_seconds))
        reserved = len(prefix) + len(marker) + 1 + sum(len(item) + 2 for item in meta)
        label = _middle_truncate(node.label, max(8, width - reserved))
        text = f"{prefix}{marker} {label}"
        if meta:
            text += "  " + "  ".join(meta)
        rows.append(RunwayRow(node.id, text, state.status, state.active))
    return rows


def header_fields(snapshot: RunSnapshot) -> dict[str, str]:
    _symbol, word = state_grammar(snapshot.status)
    return {
        "word": word,
        "branch": snapshot.branch or "unknown",
        "baseline": (snapshot.baseline_commit or "")[:7] or "unknown",
        "elapsed": format_elapsed(snapshot.elapsed_seconds),
        "workflow": snapshot.workflow_name or snapshot.workflow_id or "workflow",
        "run": snapshot.abbreviated_run_id or "—",
    }
