"""Scope-aware graph and timing lookups for one session's run.

Kept out of :class:`CockpitSession` so the facade stays a thin composition root:
this collaborator owns the bound-run graph cache, the log aggregator's mode, and
the call-target install check. Every value it returns is derived from persisted
run files, so a composed run is projected from its frozen execution tree and a
legacy run keeps the declared graph unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..services.definition import WorkflowDefinition
from ..services.execution_tree import ExecutionTree
from ..services.execution_walk import find_node, timing_key
from ..services.graph import (
    ControlFlowGraph,
    WorkflowDefinitionParser,
    graph_from_execution_tree,
    resolve_declared_id,
)
from ..services.log_aggregator import ROOT_TIMING_PREFIX, RunLogAggregator, TimingIndex
from ..services.registry import RegistryError, WorkflowRegistry

#: Modes of the timing index: legacy declared ids, or scope occurrences.
DECLARED = "declared"
SCOPED = "scoped"


class CompositionContext:
    """Own the composition-specific read caches for one session."""

    def __init__(
        self,
        *,
        resolver: Any,
        registry: WorkflowRegistry,
        runs_dir: Path,
    ) -> None:
        self._resolver = resolver
        self._registry = registry
        self._runs_dir = Path(runs_dir)
        self._graph: ControlFlowGraph | None = None
        self._tree_graph_cache: tuple[ExecutionTree, ControlFlowGraph] | None = None
        self._aggregator: RunLogAggregator | None = None
        self._mode = ""

    @property
    def graph(self) -> ControlFlowGraph | None:
        return self._graph

    def reset(self, definition: WorkflowDefinition) -> ControlFlowGraph:
        """Build the declared graph for a newly selected or adopted definition."""
        self._graph = self.build_declared_graph(definition)
        self._tree_graph_cache = None
        self._aggregator = None
        self._mode = ""
        return self._graph

    def build_declared_graph(self, definition: WorkflowDefinition) -> ControlFlowGraph:
        """The declared graph, following literal call targets into their installs."""
        return WorkflowDefinitionParser(
            expand_calls=True,
            resolve_definition=self._resolver.effective_steps_of,
            check_installed=self.target_install_error,
            root_workflow_id=definition.id,
        ).parse(definition.effective_steps)

    def target_install_error(self, workflow_id: str) -> str | None:
        """Why a literal call target cannot run, or ``None`` when it can."""
        try:
            entry = self._registry.get(workflow_id)
        except RegistryError as exc:
            return str(exc)
        if entry is None:
            return f"target {workflow_id!r} is not installed"
        if not entry.enabled:
            return f"target {workflow_id!r} is disabled"
        return None

    def graph_for(self, state: Any) -> ControlFlowGraph | None:
        """The graph to project: the bound tree's when one is readable."""
        tree = getattr(state, "execution", None) if state is not None else None
        if isinstance(tree, ExecutionTree) and tree.structurally_valid:
            if self._tree_graph_cache is not None and self._tree_graph_cache[0] is tree:
                return self._tree_graph_cache[1]
            graph = graph_from_execution_tree(tree)
            self._tree_graph_cache = (tree, graph)
            return graph
        return self._graph

    def timings(self, state: Any, run_id: str | None) -> TimingIndex:
        """Timings keyed the way this run's log writes them.

        A composed run keys by scope occurrence; a legacy run keys by declared
        id, exactly as before. The aggregator is re-seated once when the mode
        becomes known, re-reading the bounded log from the start.
        """
        if run_id is None:
            return TimingIndex()
        scoped = isinstance(getattr(state, "execution", None), ExecutionTree)
        wanted = SCOPED if scoped else DECLARED
        if self._mode != wanted or self._aggregator is None:
            declared = None if scoped else (self._graph.declared_ids if self._graph else frozenset())
            self._aggregator = RunLogAggregator(declared)
            self._mode = wanted
        return self._aggregator.update(self._runs_dir / run_id / "log.jsonl")

    def diagnostic(self) -> str:
        return self._aggregator.diagnostic if self._aggregator is not None else ""

    def gate_attempt(self, state: Any, run_id: str | None) -> int:
        """Authoritative execution count of the current gate's scope occurrence.

        The engine appends one ``step_started`` log event per execution, so this
        increments exactly when a gate is re-executed (a retry) and never when an
        unrelated state write only changes ``updated_at``. A composed run's
        attempt is keyed by scope occurrence, so a same-named gate elsewhere
        never contributes (FR-016).
        """
        if self._graph is None or state is None or run_id is None:
            return 0
        key: tuple | None = None
        tree = getattr(state, "execution", None)
        if isinstance(tree, ExecutionTree) and tree.active is not None:
            active = tree.active
            node = find_node(tree, active.scope_path, active.step_id)
            if node is not None:
                key = timing_key(node)
        if key is None:
            declared_id = resolve_declared_id(state.current_step_id, self._graph.declared_ids)
            if declared_id is None:
                return 0
            key = (*ROOT_TIMING_PREFIX, declared_id)
        timing = self.timings(state, run_id).get(key)
        return timing.attempts if timing is not None else 0


def declared_graph_for(
    definition: WorkflowDefinition, check: Callable[[str], str | None], resolver: Any
) -> ControlFlowGraph:
    """Build a declared graph without a session (used by tests and tools)."""
    return WorkflowDefinitionParser(
        expand_calls=True,
        resolve_definition=resolver.effective_steps_of,
        check_installed=check,
        root_workflow_id=definition.id,
    ).parse(definition.effective_steps)
