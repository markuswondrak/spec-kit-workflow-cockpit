"""Pure lifecycle classification and launch-contract checks.

Extracted from the session facade so the rules are testable without a session
and the facade stays under its size budget.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from ..engine.supervisor import EngineSupervisor
from ..services.definition import (
    WorkflowDefinition,
    definition_signature,
    normalized_signature,
)
from ..services.run_state import RunStateData
from ..services.snapshot import Outcome, OutcomeKind

#: Characters kept from a failure detail before the render budget is at risk.
FAILURE_DETAIL_LIMIT = 2000

#: Lines kept from the live engine stream when no step output was captured.
STREAM_TAIL_LINES = 20

#: Label marking a failure detail that came from the live engine stream rather
#: than captured step output.
STREAM_DETAIL_LABEL = "engine output (last lines):"


def combine(*messages: str) -> str:
    """Join distinct non-empty diagnostics in first-seen order."""
    seen: list[str] = []
    for message in messages:
        if message and message not in seen:
            seen.append(message)
    return " ".join(seen)


def _bounded(text: str) -> str:
    """Trim surrounding whitespace and clamp a detail to the render budget."""
    trimmed = text.strip()
    if len(trimmed) <= FAILURE_DETAIL_LIMIT:
        return trimmed
    return trimmed[:FAILURE_DETAIL_LIMIT].rstrip() + "…"


def _stream_excerpt(stream_tail: Sequence[str]) -> str:
    """Return a bounded suffix of already-normalised engine-stream lines."""
    lines = list(stream_tail)[-STREAM_TAIL_LINES:]
    return "\n".join(lines).strip()


def _failure_source(
    state: RunStateData | None,
    persisted: str,
    stream_tail: Sequence[str],
) -> tuple[str, str]:
    """Select the failure detail and its label from captured output or the stream.

    Prefers the step's captured ``stderr``, then ``stdout`` (authoritative).
    When a step result exists but captured no output (a dispatched
    ``command``/``integration`` step), a bounded excerpt of the live engine
    stream is used before the step or top-level ``error``; without a step result
    the persisted error is kept. Falls back to the generic persisted-status
    message. The second value is a label marking a stream excerpt; it is empty
    for captured output.
    """
    result = state.current_result() if state is not None else None
    if result is not None:
        output = result.get("output")
        if isinstance(output, dict):
            for key in ("stderr", "stdout"):
                value = output.get(key)
                if isinstance(value, str) and value.strip():
                    return _bounded(value), ""
        excerpt = _stream_excerpt(stream_tail)
        if excerpt:
            return _bounded(excerpt), STREAM_DETAIL_LABEL
        step_error = result.get("error")
        if isinstance(step_error, str) and step_error.strip():
            return _bounded(step_error), ""
    if state is not None and isinstance(state.error, str) and state.error.strip():
        return _bounded(state.error), ""
    return f"Engine status: {persisted}", ""


def _failure_detail(
    state: RunStateData | None,
    persisted: str,
    stream_tail: Sequence[str] = (),
) -> str:
    """Derive the failure detail from captured output or the live engine stream."""
    detail, _label = _failure_source(state, persisted, stream_tail)
    return detail


def _failure_outcome(
    state: RunStateData | None,
    persisted: str,
    stream_tail: Sequence[str],
) -> Outcome:
    """Build the FAILURE outcome with its detail and source label."""
    detail, label = _failure_source(state, persisted, stream_tail)
    return Outcome(
        kind=OutcomeKind.FAILURE,
        detail=detail,
        detail_label=label,
        step_id=state.current_step_id if state else None,
        engine_status=persisted,
    )


def check_launch_contract(
    definition: WorkflowDefinition | None,
    run_dir: Path,
    supervisor: EngineSupervisor,
) -> str | None:
    """Return a fatal reason when the persisted launch copy diverges, else None.

    The persisted ``workflow.yml`` is authoritative; a mismatch aborts the owned
    run through the supervisor. An absent or unreadable launch copy is not a
    mismatch: the engine may simply not have written it yet.
    """
    if definition is None:
        return None
    path = Path(run_dir) / "workflow.yml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    if normalized_signature(data) != definition_signature(definition):
        supervisor.abort()
        return "The persisted workflow definition does not match the launch model."
    return None


def write_context_index(
    writer: Any,
    *,
    run_id: str,
    definition: WorkflowDefinition | None,
    branch: str | None,
    executable: Path,
) -> tuple[str, str]:
    """Write the stable context index; failure is reported, never fatal."""
    if definition is None:
        return "", ""
    try:
        result = writer.write(
            run_id=run_id,
            definition=definition,
            branch=branch,
            executable=executable,
        )
    except Exception as exc:  # noqa: BLE001 - context failure must not stop the run
        return "", f"Context index unavailable: {exc}"
    return result.relative, ""


def classify_outcome(
    *,
    contract_error: str | None,
    abort_requested: bool,
    reaped: bool,
    state: RunStateData | None,
    owned_process: bool = True,
    read_only: bool = False,
    stream_tail: Sequence[str] = (),
) -> Outcome | None:
    """Classify the run outcome from persisted state and process condition.

    ``owned_process`` is false for an adopted run that has not yet spawned a
    resume: a terminal persisted status is still authoritative, but an
    unexpected non-terminal status must not be reported as a crashed process.
    ``read_only`` reflects a passively inspected run where no process is owned;
    it also has no live stream, so ``stream_tail`` is ignored in that mode.
    """
    if contract_error is not None and reaped:
        return Outcome(
            kind=OutcomeKind.FAILURE,
            detail=contract_error,
            engine_status="contract-error",
        )
    if abort_requested and reaped:
        return Outcome(
            kind=OutcomeKind.ABORT,
            detail="Aborted by you. The engine is no longer running.",
            engine_status="aborted",
        )
    persisted = state.status if state else "initializing"
    if read_only:
        if persisted == "completed":
            return Outcome(kind=OutcomeKind.SUCCESS, engine_status=persisted)
        if persisted in ("failed", "aborted"):
            return _failure_outcome(state, persisted, ())
        return None
    if not reaped:
        return None
    if persisted == "completed":
        return Outcome(kind=OutcomeKind.SUCCESS, engine_status=persisted)
    if persisted in ("failed", "aborted"):
        return _failure_outcome(state, persisted, stream_tail)
    if persisted == "paused":
        return None
    if not owned_process:
        return None
    return Outcome(
        kind=OutcomeKind.FAILURE,
        detail="The engine process exited without a terminal run state.",
        step_id=state.current_step_id if state else None,
        engine_status=persisted,
    )
