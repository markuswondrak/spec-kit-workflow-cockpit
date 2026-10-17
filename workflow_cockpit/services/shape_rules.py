"""Validate that a workflow's gates can be decided before the run starts.

Interactive gates change the engine's stdin policy for the whole child, so
mixing gate kinds, dynamic interactive values, retry over the PTY, and parallel
or looped interactive gates are refused with an actionable error rather than
started and left undecidable later. Structured-only workflows keep the
non-TTY policy and are always supported.

Composition extends the same rules across scopes: the graph models called
workflows as nested nodes, so a gate hidden inside a ``type: workflow`` call is
checked too. Verified in the Spec Kit 1.1.3 engine sources and by recorded runs:

* gate ids are unique per scope, not per run, so scope paths are needed in
  messages;
* the engine itself rejects ``verdict_input`` inside a fan-out template, so
  Cockpit refuses it before Start instead of failing the run;
* a call whose literal target is missing or disabled fails at run time, so
  Cockpit refuses it before Start.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from ..engine.interactive_contract import resolve_contract
from ..engine.supervisor import StdinPolicy
from .graph import ControlFlowGraph, GraphNode
from .verdict_trace import collect_verdict_traces

#: Container types whose interactive prompt ownership cannot be proven.
PARALLEL_TYPES = frozenset({"while", "do-while", "fan-out"})


@dataclass(frozen=True)
class ShapeSupport:
    """Whether an effective workflow's gates can be decided, and how."""

    ok: bool
    stdin: StdinPolicy
    error: str = ""


@dataclass(frozen=True)
class ScopedGate:
    """One gate with the scope it lives in, so messages can name both."""

    node: GraphNode

    @property
    def scope_path(self) -> tuple[Any, ...]:
        return self.node.key[:-1]

    @property
    def display_scope(self) -> str:
        return " > ".join(str(part) for part in self.node.key)


def is_dynamic(value: str) -> bool:
    return "{{" in value


def ancestor_types(graph: ControlFlowGraph, node: GraphNode) -> tuple[str, ...]:
    """The types of every enclosing node, derived from the scope path."""
    by_key = graph.by_key
    found: list[str] = []
    key = node.key
    for cut in range(1, len(key)):
        parent = by_key.get(key[:cut])
        if parent is not None:
            found.append(parent.type)
    return tuple(found)


def nested_in_parallel(graph: ControlFlowGraph, node: GraphNode) -> bool:
    """True when a gate executes under a loop or fan-out container."""
    return any(kind in PARALLEL_TYPES for kind in ancestor_types(graph, node))


def under_fanout(graph: ControlFlowGraph, node: GraphNode) -> bool:
    return "fan-out" in ancestor_types(graph, node)


def scoped_gates(graph: ControlFlowGraph) -> tuple[ScopedGate, ...]:
    """Every gate with the scope path it lives in, in graph order."""
    return tuple(ScopedGate(node) for node in graph.nodes if node.gate)


def _where(gate: ScopedGate) -> str:
    if gate.scope_path:
        return f"Gate {gate.node.id!r} in scope {gate.display_scope!r}"
    return f"Gate {gate.node.id!r}"


def validate_shape(
    graph: ControlFlowGraph | None,
    version: object,
    *,
    resolve_definition: Callable[[str], Iterable[Any] | None] | None = None,
    installed: Callable[[str], str | None] | None = None,
    targets_resolved: bool = False,
) -> ShapeSupport:
    """Validate the effective composition before Start.

    ``targets_resolved`` says the graph already came from a run's frozen
    execution tree, so call targets are not re-resolved (FR-010) and only the
    gate rules apply.
    """
    if graph is None:
        return ShapeSupport(True, StdinPolicy.DEVNULL)

    fanout_verdict = _fanout_verdict_error(graph)
    if fanout_verdict:
        return ShapeSupport(False, StdinPolicy.DEVNULL, fanout_verdict)

    if not targets_resolved:
        target_error = _target_error(graph, installed)
        if target_error:
            return ShapeSupport(False, StdinPolicy.DEVNULL, target_error)

    gates = scoped_gates(graph)
    non_verdict = [gate for gate in gates if not gate.node.verdict_input]
    if not non_verdict:
        return _trace_error(graph, resolve_definition) or ShapeSupport(
            True, StdinPolicy.DEVNULL
        )

    contract = resolve_contract(version)
    if any(gate.node.verdict_input for gate in gates):
        return ShapeSupport(
            False,
            StdinPolicy.DEVNULL,
            "Workflows that mix gates with and without verdict_input cannot be decided "
            "safely; remove one gate type or split the workflow.",
        )
    if contract is None:
        return ShapeSupport(
            False,
            StdinPolicy.DEVNULL,
            f"Could not determine the specify version from {version!r}; interactive gates "
            "cannot be mapped. Reinstall a supported CLI or use verdict_input gates.",
        )
    for gate in non_verdict:
        node = gate.node
        where = _where(gate)
        if nested_in_parallel(graph, node):
            return ShapeSupport(
                False,
                StdinPolicy.DEVNULL,
                f"{where} runs inside a loop or fan-out, where interactive prompt "
                "ownership is not deterministic; make the gate sequential.",
            )
        if node.on_reject == "retry":
            return ShapeSupport(
                False,
                StdinPolicy.DEVNULL,
                f"{where} uses on_reject: retry, which requires re-prompting across "
                "processes and is not supported for interactive gates; use skip or abort, or "
                "a verdict_input gate.",
            )
        if is_dynamic(node.message) or any(is_dynamic(option) for option in node.options):
            return ShapeSupport(
                False,
                StdinPolicy.DEVNULL,
                f"{where} uses dynamic message or options that cannot be verified "
                "before Start; make them static or use a verdict_input gate.",
            )
        if not node.options:
            return ShapeSupport(
                False,
                StdinPolicy.DEVNULL,
                f"{where} declares no options; interactive decisions need explicit options.",
            )
    return ShapeSupport(True, StdinPolicy.PTY)


def _fanout_verdict_error(graph: ControlFlowGraph) -> str:
    """A ``verdict_input`` gate under a fan-out is undecidable at any scope.

    The engine rejects the same shape at run time ("'verdict_input' is not
    supported inside fan-out templates"), so refusing it before Start turns a
    late failure into an actionable message (FR-011).
    """
    for gate in scoped_gates(graph):
        if not gate.node.verdict_input:
            continue
        if under_fanout(graph, gate.node):
            return (
                f"{_where(gate)} uses verdict_input under a fan-out, where the engine "
                "cannot receive the decision; move the gate out of the fan-out or use a "
                "non-verdict gate."
            )
    return ""


def _target_error(
    graph: ControlFlowGraph, installed: Callable[[str], str | None] | None
) -> str:
    """A literal call target that is not installed or not enabled (FR-012)."""
    for node in graph.nodes:
        if not node.is_call or node.target_resolved:
            continue
        if node.target_error == "dynamic":
            # Dynamic targets never block Start (clarified, FR-012).
            continue
        where = f"Call step {node.id!r}"
        if node.scope_path and len(node.scope_path) > 1:
            where = f"Call step {node.id!r} in scope {' > '.join(str(p) for p in node.scope_path[:-1])!r}"
        if node.target_error == "cycle":
            return f"{where} calls {node.target or 'its target'!r} cyclically; the engine refuses this at run time."
        reason = node.target_error
        if not reason and installed is not None and node.target:
            reason = installed(node.target)
        if not reason:
            reason = f"target {node.target!r} could not be resolved"
        return f"{where} cannot be started: {reason}."
    return ""


def _trace_error(
    graph: ControlFlowGraph, resolve_definition: Callable[[str], Iterable[Any] | None] | None
) -> ShapeSupport | None:
    """A child verdict input no root input feeds is undecidable (FR-013)."""
    if resolve_definition is None:
        return None
    report = collect_verdict_traces(_declared_steps(graph), resolve_definition)
    if not report.problems:
        return None
    problem = report.problems[0]
    scope = " > ".join(str(part) for part in problem.scope_path)
    return ShapeSupport(
        False,
        StdinPolicy.DEVNULL,
        f"The gate in scope {scope!r} cannot be decided from Cockpit: {problem.reason}.",
    )


def _declared_steps(graph: ControlFlowGraph) -> tuple[dict[str, Any], ...]:
    """Root-scope step mappings rebuilt from the graph for the verdict trace.

    The trace itself follows nested calls through the resolved definitions, so
    only the root scope's steps are listed here, with each call's own ``input:``
    mapping carried through from the raw definition.
    """
    steps: list[dict[str, Any]] = []
    for node in graph.nodes:
        if len(node.scope_path) > 1:
            continue
        step: dict[str, Any] = {"id": node.id, "type": node.type}
        if node.verdict_input:
            step["verdict_input"] = node.verdict_input
        if node.is_call and node.target:
            step["workflow"] = node.target
            if isinstance(node.input_mapping, dict):
                step["input"] = node.input_mapping
        steps.append(step)
    return tuple(steps)
