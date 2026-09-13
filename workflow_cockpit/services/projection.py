"""Project persisted run state over a declared control-flow graph."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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


@dataclass(frozen=True)
class GraphProjection:
    graph: ControlFlowGraph
    nodes: tuple[NodeState, ...]
    current_node_id: str | None = None

    @property
    def by_id(self) -> dict[str, NodeState]:
        return {node.id: node for node in self.nodes}

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


class GraphProjector:
    """Combine static graph, authoritative state, and log-derived timings."""

    def project(
        self,
        graph: ControlFlowGraph,
        state: RunStateData | None,
        timings: dict[str, StepTiming] | None = None,
        *,
        now: datetime | None = None,
        lifecycle_status: str | None = None,
    ) -> GraphProjection:
        timings = timings or {}
        now = now or datetime.now().astimezone()
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
            duration: float | None = None
            if timing.started_at is not None:
                end = timing.finished_at
                if end is None and node.id == current and status in ("running", "paused"):
                    end = now
                if end is not None:
                    duration = max(0.0, (end - timing.started_at).total_seconds())
            projected.append(
                NodeState(
                    id=node.id,
                    status=status,
                    active=node.id in active_ids,
                    attempts=timing.attempts,
                    duration_seconds=duration,
                )
            )
        return GraphProjection(graph, tuple(projected), current)
