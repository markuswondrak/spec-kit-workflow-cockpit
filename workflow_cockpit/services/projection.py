"""Project persisted run state over a declared or bound control-flow graph.

Two paths share one projection shape. A legacy run (no execution tree) keeps the
original flat projection over ``step_results``. A composed run projects over the
scoped graph built from its execution tree, so the active nested step, its scope
path and the state of its enclosing calls are all marked from persisted phases
rather than inferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .execution_tree import ExecutionTree, StepNode
from .execution_walk import step_index, timing_key
from .graph import ControlFlowGraph, resolve_declared_id
from .log_aggregator import StepTiming
from .run_state import RunStateData


@dataclass(frozen=True)
class NodeState:
    id: str
    status: str = "pending"
    active: bool = False
    attempts: int = 0
    duration_seconds: float | None = None
    #: Scope-qualified identity; equal to ``(id,)`` for a flat root-scope node.
    key: tuple[Any, ...] = ()
    #: A ``continue_on_error`` call whose own result failed but the run went on.
    handled: bool = False


@dataclass(frozen=True)
class GraphProjection:
    graph: ControlFlowGraph
    nodes: tuple[NodeState, ...]
    current_node_id: str | None = None
    current_node_key: tuple[Any, ...] | None = None

    @property
    def by_id(self) -> dict[str, NodeState]:
        found: dict[str, NodeState] = {}
        for node in self.nodes:
            found.setdefault(node.id, node)
        return found

    @property
    def by_key(self) -> dict[tuple[Any, ...], NodeState]:
        return {node.key: node for node in self.nodes}

    @property
    def next_node_id(self) -> str | None:
        """The next pending node reachable from the current/resolved frontier.

        Completed nodes only reach forward along plain sequence edges; branch and
        loop body edges are alternatives, so they are followed only from the
        current node. This keeps an untaken branch from being reported as next.
        """
        by_id = self.by_id
        resolved = {node.id for node in self.nodes if node.status not in ("pending", "running")}
        order = {node.id: node.order for node in self.graph.nodes}
        candidates: set[str] = set()
        for edge in self.graph.edges:
            source_is_current = self.current_node_id is not None and edge.source == self.current_node_id
            if not source_is_current and (edge.source not in resolved or edge.kind != "sequence"):
                continue
            target = by_id.get(edge.target)
            if target is not None and target.status == "pending" and not target.active:
                candidates.add(edge.target)
        if not candidates:
            return None
        return min(candidates, key=lambda node_id: order[node_id])


def tree_node_status(node: StepNode) -> str:
    """Map a persisted node phase/result onto the runway's status vocabulary."""
    if node.phase == "done":
        result = node.result or {}
        if result.get("status") == "failed":
            # A ``continue_on_error`` call is shown as failed too; ``handled``
            # (set from the persisted derived field) carries the distinction.
            return "failed"
        if result.get("status") == "aborted":
            return "aborted"
        return "completed"
    if node.phase == "blocked":
        result = node.result or {}
        status = result.get("status")
        if status == "paused":
            return "paused"
        if status == "failed":
            return "failed"
        if status == "completed":
            return "completed"
        return "blocked"
    if node.phase == "children":
        return "running"
    if node.phase == "outputs":
        return "running"
    return "pending"


def _duration(
    timing: StepTiming,
    *,
    now: datetime,
    status: str,
    active: bool,
) -> float | None:
    if timing.started_at is None:
        return None
    end = timing.finished_at
    if end is None and active and status in ("running", "paused"):
        end = now
    if end is None:
        return None
    return max(0.0, (end - timing.started_at).total_seconds())


class GraphProjector:
    """Combine a graph, authoritative state, and log-derived timings."""

    def project(
        self,
        graph: ControlFlowGraph,
        state: RunStateData | None,
        timings: dict[Any, StepTiming] | None = None,
        *,
        now: datetime | None = None,
        lifecycle_status: str | None = None,
    ) -> GraphProjection:
        timings = timings or {}
        now = now or datetime.now().astimezone()
        execution = getattr(state, "execution", None) if state is not None else None
        if isinstance(execution, ExecutionTree):
            return self.project_tree(
                graph,
                execution,
                timings,
                now=now,
                lifecycle_status=lifecycle_status,
            )
        return self._project_flat(graph, state, timings, now=now, lifecycle_status=lifecycle_status)

    def _project_flat(
        self,
        graph: ControlFlowGraph,
        state: RunStateData | None,
        timings: dict[Any, StepTiming],
        *,
        now: datetime,
        lifecycle_status: str | None,
    ) -> GraphProjection:
        declared_ids = graph.declared_ids
        current = resolve_declared_id(state.current_step_id if state else None, declared_ids)
        result_statuses: dict[str, str] = {}
        if state is not None:
            for runtime_id, result in state.step_results.items():
                if not isinstance(runtime_id, str) or not isinstance(result, dict):
                    continue
                declared_id = resolve_declared_id(runtime_id, declared_ids)
                status = result.get("status")
                if declared_id is not None and isinstance(status, str):
                    result_statuses[declared_id] = status

        active_ids = {node_id for node_id, status in result_statuses.items() if status != "pending"}
        if current is not None:
            active_ids.add(current)
        by_id = graph.by_id
        for node_id in tuple(active_ids):
            parent = by_id.get(node_id).parent_id if node_id in by_id else None
            while parent is not None:
                active_ids.add(parent)
                parent = by_id.get(parent).parent_id if parent in by_id else None

        projected: list[NodeState] = []
        for node in graph.nodes:
            status = result_statuses.get(node.id, "pending")
            if node.id == current and state is not None:
                effective_status = lifecycle_status or state.status
                if effective_status == "paused":
                    status = "paused"
                elif effective_status in ("running", "created", "initializing"):
                    status = "running"
                elif effective_status in ("failed", "failure"):
                    status = "failed"
                elif effective_status in ("aborted", "abort"):
                    status = "aborted"
                elif effective_status in ("completed", "success"):
                    status = "completed"
            timing = timings.get(node.id, StepTiming())
            projected.append(
                NodeState(
                    id=node.id,
                    status=status,
                    active=node.id in active_ids,
                    attempts=timing.attempts,
                    duration_seconds=_duration(
                        timing,
                        now=now,
                        status=status,
                        active=node.id == current,
                    ),
                    key=node.key,
                )
            )
        return GraphProjection(
            graph,
            tuple(projected),
            current,
            (current,) if current is not None else None,
        )

    def project_tree(
        self,
        graph: ControlFlowGraph,
        tree: ExecutionTree,
        timings: dict[Any, StepTiming],
        *,
        now: datetime | None = None,
        lifecycle_status: str | None = None,
    ) -> GraphProjection:
        """Project the scoped graph from the persisted execution tree.

        Statuses come from each node's persisted ``phase``/``result``; the active
        node and its enclosing calls are marked from the tree's own active-node
        rule, never from a bare ``current_step_id``.
        """
        now = now or datetime.now().astimezone()
        index = step_index(tree)
        active = tree.active
        active_key = active.node_key if active else None
        # Every prefix of the active key is an enclosing node (call or container),
        # so enclosing calls are marked active exactly as the engine behaves.
        active_scope_keys = (
            {active_key[:cut] for cut in range(1, len(active_key) + 1)}
            if active_key is not None
            else set()
        )

        projected: list[NodeState] = []
        for node in graph.nodes:
            tree_node = index.get(node.key)
            if tree_node is None:
                projected.append(NodeState(id=node.id, key=node.key))
                continue
            status = tree_node_status(tree_node)
            is_active = node.key == active_key or node.key in active_scope_keys
            timing = timings.get(timing_key(tree_node), StepTiming())
            projected.append(
                NodeState(
                    id=node.id,
                    status=status,
                    active=is_active,
                    attempts=timing.attempts,
                    duration_seconds=_duration(
                        timing,
                        now=now,
                        status=status,
                        active=node.key == active_key,
                    ),
                    key=node.key,
                    handled=tree_node.handled_failure,
                )
            )
        current_id = active.step_id if active else None
        return GraphProjection(graph, tuple(projected), current_id, active_key)
