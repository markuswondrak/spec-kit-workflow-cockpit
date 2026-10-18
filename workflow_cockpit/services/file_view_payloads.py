"""Envelope shape: the condition report and the JSON payloads it describes.

Split from :mod:`workflow_cockpit.services.file_view` so the builder and the
shape each stay small and independently reviewable. Nothing here reads a file or
writes anything: these are pure mappings from already-read values onto the
envelope's declared shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .execution_tree import ExecutionTree, Resolution
from .feature_review import DEFAULT_PREVIEW_BYTES
from .gate_target import GateTarget
from .graph import ControlFlowGraph
from .limits import MAX_FEATURE_FILES
from .review import ReviewDocument, ReviewSnapshot
from .run_state import RunStateData

KIND_MISSING = "missing"
KIND_PARTIAL = "partial"
KIND_STALE = "stale"
KIND_TOO_LARGE = "too_large"

@dataclass(frozen=True)
class Condition:
    """One reported source condition: never a silent failure."""

    source: str
    kind: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "kind": self.kind, "detail": self.detail}


def node_key_payload(key: tuple[Any, ...] | None) -> list[Any] | None:
    return None if key is None else [str(part) for part in key]


def projection_payload(projection: Any | None) -> dict[str, Any] | None:
    """Serialize a :class:`GraphProjection` exactly as the UI consumes it."""
    if projection is None:
        return None
    graph = projection.graph
    nodes: list[dict[str, Any]] = []
    for node in graph.nodes:
        nodes.append(
            {
                "id": node.id,
                "label": node.label,
                "key": node_key_payload(node.key),
                "parent_key": node_key_payload(node.parent_key),
                "depth": node.depth,
                "branch": node.branch,
                "gate": bool(node.gate),
                "is_call": bool(node.is_call),
                "workflow_id": node.workflow_id,
                "order": node.order,
            }
        )
    states: list[dict[str, Any]] = []
    for state in projection.nodes:
        states.append(
            {
                "id": state.id,
                "key": node_key_payload(state.key),
                "status": state.status,
                "active": bool(state.active),
                "attempts": state.attempts,
                "duration_seconds": state.duration_seconds,
                "handled": bool(state.handled),
            }
        )
    return {
        "nodes": nodes,
        "states": states,
        "current_node_id": projection.current_node_id,
        "current_node_key": node_key_payload(projection.current_node_key),
        "next_node_id": projection.next_node_id,
    }


def gate_payload(target: GateTarget | None, attempts: int) -> dict[str, Any] | None:
    """The open gate with exactly the declared options, a null token, and its ledger.

    A read command never mints a decision token: the token is issued by the
    owning surface that can submit the decision (FR-005). ``ledger`` reports the
    authoritative execution count of this gate's scope occurrence.
    """
    if target is None:
        return None
    return {
        "id": target.step_id or None,
        "runtime_step_id": target.runtime_step_id or target.step_id or None,
        "kind": target.kind,
        "message": target.message,
        "options": list(target.options),
        "on_reject": target.on_reject,
        "scope_path": [str(part) for part in target.scope_path],
        "token": None,
        "ledger": {"state": "blocked" if target.blocked else "open", "attempts": attempts},
        "blocked": target.blocked,
        "reason": target.reason,
        "reason_kind": target.reason_kind,
    }


def step_payload(
    state: RunStateData | None,
    graph: ControlFlowGraph | None,
    projection: Any | None,
) -> dict[str, Any] | None:
    """The current step, composed-aware: the persisted active node wins (ADR-0015)."""
    if state is None:
        return None
    tree = state.execution
    active = (
        tree.active
        if isinstance(tree, ExecutionTree) and tree.resolution is Resolution.OK
        else None
    )
    if active is not None:
        step_id: str | None = active.step_id
        runtime_id: str | None = active.qualified_id
        scope_path = [str(part) for part in active.scope_path]
    else:
        step_id = state.current_step_id
        runtime_id = state.current_step_id
        scope_path = []
    label = ""
    status: str | None = None
    is_active: bool | None = None
    if projection is not None:
        key = projection.current_node_key
        node_state = projection.by_key.get(key) if key is not None else None
        if node_state is not None:
            status = node_state.status
            is_active = bool(node_state.active)
        if graph is not None and key is not None:
            node = graph.by_key.get(key)
            if node is not None:
                label = node.label
    return {
        "step_id": step_id,
        "runtime_step_id": runtime_id,
        "label": label,
        "scope_path": scope_path,
        "status": status,
        "active": is_active,
    }


def feature_files_payload(
    review: ReviewSnapshot,
    conditions: list[Condition],
) -> dict[str, Any]:
    """The bounded Feature Files index; truncation is reported, never silent."""
    entries = list(review.files)
    truncated = len(entries) > MAX_FEATURE_FILES
    if truncated:
        conditions.append(
            Condition(
                source="feature_files",
                kind=KIND_PARTIAL,
                detail=(
                    f"the Feature Files index has {len(entries)} entries; "
                    f"only the first {MAX_FEATURE_FILES} are reported."
                ),
            )
        )
        entries = entries[:MAX_FEATURE_FILES]
    return {
        "entries": [
            {
                "path": entry.path,
                "display": entry.label,
                "size": entry.size,
                "truncated": entry.size is not None and entry.size > DEFAULT_PREVIEW_BYTES,
            }
            for entry in entries
        ],
        "truncated": truncated,
    }


def file_payload(document: ReviewDocument) -> dict[str, Any]:
    return {
        "path": document.path,
        "content": document.text,
        "truncated": document.truncated,
        "binary": document.binary,
        "note": document.note,
        "error": document.error,
        "total_bytes": document.total_bytes,
    }
