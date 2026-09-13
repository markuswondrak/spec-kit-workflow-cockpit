"""View model helpers mapping snapshots to renderable strings (no Textual)."""

from __future__ import annotations

from dataclasses import dataclass

from ..services.definition import WorkflowDefinition
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


@dataclass(frozen=True)
class StepRow:
    marker: str
    label: str
    status: str


def state_grammar(status: str) -> tuple[str, str]:
    return STATUS_GRAMMAR.get(status, ("[ ]", status.upper() or "UNKNOWN"))


def format_elapsed(seconds: float) -> str:
    total = int(max(0.0, seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def build_step_rows(
    definition: WorkflowDefinition | None, snapshot: RunSnapshot
) -> list[StepRow]:
    if definition is None:
        return []
    current_index: int | None = None
    if snapshot.current_step_id:
        for index, step in enumerate(definition.steps):
            if step.id == snapshot.current_step_id:
                current_index = index
                break
    terminal = snapshot.terminal
    rows: list[StepRow] = []
    for index, step in enumerate(definition.steps):
        if current_index is None:
            status = "pending"
        elif index < current_index:
            status = "done"
        elif index == current_index:
            if terminal or snapshot.status == "failed":
                status = "failed" if snapshot.status in ("failed", "failure") else "done"
            elif snapshot.status == "paused":
                status = "gate"
            else:
                status = "running"
        else:
            status = "pending"
        marker = {"pending": "[ ]", "running": "[>]", "gate": "[!]", "done": "[x]", "failed": "[X]"}[status]
        meta = "gate" if step.gate else ""
        label = f"{step.label}  {meta}".rstrip()
        rows.append(StepRow(marker=marker, label=label, status=status))
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
