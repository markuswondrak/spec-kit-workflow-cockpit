"""Resolve the one gate the run is at, from persisted evidence only.

For a composed run the gate is the *active node* of the persisted execution
tree: its message and options come from that node's own ``result.output`` and
its static configuration from the frozen step config, never from
``step_results[current_step_id]`` (which holds root-scope steps only, so a
child gate whose id collides with a root step would otherwise be confused with
it).

When the persisted position cannot be trusted, or the active gate is one
Cockpit cannot decide from the running process, the resolver returns a named
blocked target instead of guessing. That keeps the "Abort only" fallback
explicit and testable without a running UI.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .execution_tree import (
    ActiveNode,
    ExecutionTree,
    Resolution,
    UnsupportedExecution,
)
from .execution_walk import ancestors, find_node
from .graph import ControlFlowGraph, GraphNode, resolve_declared_id
from .shape_rules import PARALLEL_TYPES, is_dynamic
from .verdict_trace import Untraceable, call_chain_from_tree, trace_chain

#: Statuses in which the engine leaves a halted node behind.
HALTED_STATUSES = frozenset({"paused", "failed", "aborted"})

#: Named Abort-only reasons, so the UI and tests can distinguish them (FR-007).
REASON_UNRESOLVED = "unresolved"
REASON_UNSUPPORTED_VERSION = "unsupported-version"
REASON_UNDECIDABLE = "undecidable"


@dataclass(frozen=True)
class GateTarget:
    """One gate with the scope context and the transport it needs."""

    step_id: str
    runtime_step_id: str
    kind: str = "structured"
    message: str = ""
    options: tuple[str, ...] = ()
    on_reject: str | None = None
    verdict_input: str | None = None
    scope_path: tuple[Any, ...] = ()
    root_input: str | None = None
    occurrence: tuple[Any, ...] = ()
    #: Non-empty when the gate cannot be decided; the state stays Abort-only.
    reason: str = ""
    reason_kind: str = ""

    @property
    def blocked(self) -> bool:
        return bool(self.reason)

    @property
    def display_scope_path(self) -> str:
        return " > ".join(str(part) for part in (*self.scope_path, self.step_id))


def display_scope_path(scope_path: tuple[Any, ...], step_id: str | None = None) -> str:
    parts = list(scope_path) + ([step_id] if step_id else [])
    return " > ".join(str(part) for part in parts)


def resolve_gate_target(
    state: Any,
    graph: ControlFlowGraph | None = None,
    *,
    scope_rules: bool = True,
) -> GateTarget | None:
    """The current gate target, or ``None`` when the run is not at a gate."""
    if state is None:
        return None
    execution = getattr(state, "execution", None)
    status = getattr(state, "status", "")
    if isinstance(execution, UnsupportedExecution):
        if status == "paused":
            return _blocked(
                REASON_UNSUPPORTED_VERSION,
                f"state.json execution version {execution.version!r} is not supported; "
                "only Abort is available.",
            )
        return None
    if isinstance(execution, ExecutionTree):
        return _resolve_tree_target(state, execution, scope_rules=scope_rules)
    return _resolve_declared_target(state, graph)


def _blocked(reason_kind: str, reason: str, **fields: Any) -> GateTarget:
    return GateTarget(
        step_id=fields.pop("step_id", "") or "",
        runtime_step_id=fields.pop("runtime_step_id", "") or "",
        kind="blocked",
        reason=reason,
        reason_kind=reason_kind,
        **fields,
    )


def _resolve_tree_target(
    state: Any, tree: ExecutionTree, *, scope_rules: bool
) -> GateTarget | None:
    status = getattr(state, "status", "")
    active = tree.active
    if tree.resolution is not Resolution.OK or active is None:
        if status == "paused":
            return _blocked(
                REASON_UNRESOLVED,
                "The persisted run position is unresolved; only Abort is available.",
                step_id=active.step_id if active else "",
                runtime_step_id=active.qualified_id if active else "",
                scope_path=active.scope_path if active else (),
            )
        return None
    node = find_node(tree, active.scope_path, active.step_id)
    if node is None or node.kind != "gate":
        return None
    enclosing = ancestors(tree, node)
    nested_parallel = any(parent.kind in PARALLEL_TYPES for parent in enclosing)
    under_fanout = any(parent.kind == "fan-out" for parent in enclosing)
    verdict_input = node.verdict_input
    root_input: str | None = None
    if verdict_input:
        traced = trace_chain(call_chain_from_tree(tree, active.enclosing_calls), verdict_input)
        if scope_rules and under_fanout:
            return _blocked(
                REASON_UNDECIDABLE,
                _undecidable_message(
                    "uses verdict_input under a fan-out, where the engine cannot receive "
                    "the decision",
                    active,
                    node.verdict_input,
                ),
                step_id=node.step_id,
                runtime_step_id=active.qualified_id,
                scope_path=active.scope_path,
                verdict_input=verdict_input,
                occurrence=active.occurrence_path,
            )
        if isinstance(traced, Untraceable):
            return _blocked(
                REASON_UNDECIDABLE,
                _undecidable_message(traced.reason, active, node.verdict_input),
                step_id=node.step_id,
                runtime_step_id=active.qualified_id,
                scope_path=active.scope_path,
                verdict_input=verdict_input,
                occurrence=active.occurrence_path,
            )
        root_input = traced.root_input
        kind = "structured"
    else:
        kind = "interactive"
        reason = _interactive_shape_reason(node, active, nested_parallel, scope_rules)
        if reason:
            return _blocked(
                REASON_UNDECIDABLE,
                reason,
                step_id=node.step_id,
                runtime_step_id=active.qualified_id,
                scope_path=active.scope_path,
                occurrence=active.occurrence_path,
            )
    message, options, evidence_reason = _structured_evidence(node, status)
    if kind == "interactive":
        message = str(node.config.get("message") or "Review required.")
        options = _options(node.config)
    if evidence_reason and kind == "structured":
        return _blocked(
            REASON_UNRESOLVED,
            evidence_reason,
            step_id=node.step_id,
            runtime_step_id=active.qualified_id,
            scope_path=active.scope_path,
            verdict_input=verdict_input,
            occurrence=active.occurrence_path,
        )
    if status != "paused" and kind == "structured":
        return _blocked(
            REASON_UNRESOLVED,
            "The persisted gate is not paused; only Abort is available.",
            step_id=node.step_id,
            runtime_step_id=active.qualified_id,
            scope_path=active.scope_path,
            verdict_input=verdict_input,
            message=message,
            options=options,
            occurrence=active.occurrence_path,
        )
    return GateTarget(
        step_id=node.step_id,
        runtime_step_id=active.qualified_id,
        kind=kind,
        message=message,
        options=options,
        on_reject=node.on_reject,
        verdict_input=verdict_input,
        scope_path=active.scope_path,
        root_input=root_input,
        occurrence=active.occurrence_path,
    )


def _undecidable_message(reason: str, active: ActiveNode, verdict_input: str | None) -> str:
    scope = display_scope_path(active.scope_path, active.step_id)
    detail = f"{reason}" if reason.endswith(".") else f"{reason}."
    return f"Undecidable gate in {scope!r}: {detail} Only Abort is available."


def _interactive_shape_reason(
    node: Any, active: ActiveNode, nested_parallel: bool, scope_rules: bool
) -> str:
    """The FR-011 rules applied to a bound interactive gate (T023)."""
    if not scope_rules:
        return ""
    scope = display_scope_path(active.scope_path, active.step_id)
    if nested_parallel:
        return (
            f"Undecidable gate in {scope!r}: it runs inside a loop or fan-out, where "
            "interactive prompt ownership cannot be proven. Only Abort is available."
        )
    if node.on_reject == "retry":
        return (
            f"Undecidable gate in {scope!r}: on_reject: retry requires re-prompting across "
            "processes. Only Abort is available."
        )
    message = str(node.config.get("message") or "")
    if is_dynamic(message) or any(is_dynamic(option) for option in _options(node.config)):
        return (
            f"Undecidable gate in {scope!r}: its message or options are dynamic. "
            "Only Abort is available."
        )
    if not _options(node.config):
        return (
            f"Undecidable gate in {scope!r}: it declares no options. Only Abort is available."
        )
    return ""


def _options(config: Mapping[str, Any]) -> tuple[str, ...]:
    raw = config.get("options")
    if isinstance(raw, (list, tuple)):
        return tuple(str(item) for item in raw)
    return ()


def _structured_evidence(node: Any, status: str) -> tuple[str, tuple[str, ...], str]:
    """Resolve message/options from the active node's own persisted output."""
    declared_message = str(node.config.get("message") or "") or "Gate evidence is unavailable."
    declared_options = _options(node.config)
    if status != "paused":
        return declared_message, declared_options, ""
    result = node.result
    if not isinstance(result, Mapping) or result.get("type") != "gate":
        return declared_message, declared_options, (
            "The persisted gate evidence is unavailable; only Abort is available."
        )
    output = result.get("output")
    if not isinstance(output, Mapping):
        return declared_message, declared_options, (
            "The persisted gate output is malformed; only Abort is available."
        )
    raw_message = output.get("message")
    valid_message = isinstance(raw_message, str) and bool(raw_message)
    message = raw_message if valid_message else declared_message
    raw_options = output.get("options")
    if isinstance(raw_options, (list, tuple)):
        options = tuple(item for item in raw_options if isinstance(item, str))
        valid_options = len(options) == len(raw_options) and bool(options)
    else:
        options = ()
        valid_options = False
    if not valid_options:
        options = options or declared_options
    if not valid_message:
        return message, options, (
            "The persisted gate message is missing or malformed; only Abort is available."
        )
    if not valid_options:
        return message, options, (
            "The persisted gate options are missing or malformed; only Abort is available."
        )
    return message, options, ""


def _resolve_declared_target(state: Any, graph: ControlFlowGraph | None) -> GateTarget | None:
    """The original flat-workflow resolution, expressed as a target."""
    if graph is None:
        return None
    runtime_id = getattr(state, "current_step_id", None)
    if not runtime_id:
        return None
    declared_id = resolve_declared_id(runtime_id, graph.declared_ids)
    node: GraphNode | None = graph.by_id.get(declared_id) if declared_id else None
    if node is None or not node.gate:
        return None
    kind = "structured" if node.verdict_input else "interactive"
    if kind == "structured":
        message, options, reason = _legacy_structured_evidence(state, node)
    else:
        message, options, reason = node.message or "Review required.", node.options, ""
    if reason:
        return _blocked(
            REASON_UNRESOLVED,
            reason,
            step_id=node.id,
            runtime_step_id=runtime_id,
            message=message,
            options=options,
            on_reject=node.on_reject,
            verdict_input=node.verdict_input,
        )
    return GateTarget(
        step_id=node.id,
        runtime_step_id=runtime_id,
        kind=kind,
        message=message,
        options=options,
        on_reject=node.on_reject,
        verdict_input=node.verdict_input,
        scope_path=node.scope_root if node.scope_path else (),
        root_input=node.verdict_input if kind == "structured" else None,
    )


def _legacy_structured_evidence(
    state: Any, node: GraphNode
) -> tuple[str, tuple[str, ...], str]:
    """Message/options from ``step_results`` for a flat (legacy) run."""
    declared_message = node.message or "Gate evidence is unavailable."
    declared_options = node.options
    if getattr(state, "status", "") != "paused":
        return declared_message, declared_options, ""
    result = state.current_result() if hasattr(state, "current_result") else None
    if not isinstance(result, dict) or result.get("type") != "gate":
        return declared_message, declared_options, (
            "The persisted gate evidence is unavailable; only Abort is available."
        )
    output = result.get("output")
    if not isinstance(output, dict):
        return declared_message, declared_options, (
            "The persisted gate output is malformed; only Abort is available."
        )
    raw_message = output.get("message")
    valid_message = isinstance(raw_message, str) and bool(raw_message)
    message = raw_message if valid_message else declared_message
    raw_options = output.get("options")
    if isinstance(raw_options, list):
        options = tuple(item for item in raw_options if isinstance(item, str))
        valid_options = len(options) == len(raw_options) and bool(options)
    else:
        options = ()
        valid_options = False
    if not valid_options:
        options = options or declared_options
    if not valid_message:
        return message, options, "The persisted gate message is missing or malformed; only Abort is available."
    if not valid_options:
        return message, options, "The persisted gate options are missing or malformed; only Abort is available."
    return message, options, ""


