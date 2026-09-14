"""Parse effective workflow definitions into an immutable control-flow graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GraphNode:
    """One declared workflow step, including inline control-flow children."""

    id: str
    label: str
    type: str
    parent_id: str | None
    branch: str | None
    depth: int
    order: int
    gate: bool = False
    message: str = ""
    options: tuple[str, ...] = ()
    verdict_input: str | None = None
    on_reject: str | None = None
    max_iterations: int | None = None
    is_template: bool = False


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    kind: str
    label: str = ""


@dataclass(frozen=True)
class ControlFlowGraph:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    @property
    def by_id(self) -> dict[str, GraphNode]:
        return {node.id: node for node in self.nodes}

    @property
    def declared_ids(self) -> frozenset[str]:
        return frozenset(node.id for node in self.nodes)


def resolve_declared_id(runtime_id: str | None, declared_ids: frozenset[str]) -> str | None:
    """Map engine-generated loop/fan-out ids back to a declared step id.

    Engine-generated ids append numeric iteration/index segments, so a declared
    step whose id is itself numeric must not shadow the real body step. Prefer a
    non-numeric declared segment, then fall back to any declared segment.
    """
    if not runtime_id:
        return None
    if runtime_id in declared_ids:
        return runtime_id
    parts = runtime_id.split(":")
    for part in reversed(parts):
        if part in declared_ids and not part.isdigit():
            return part
    for part in reversed(parts):
        if part in declared_ids:
            return part
    return None


class WorkflowDefinitionParser:
    """Build a graph from the resolver's overlay-composed raw step mappings."""

    def parse(self, effective_steps: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> ControlFlowGraph:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        known_ids: set[str] = set()

        def add_steps(
            steps: Any,
            parent_id: str | None = None,
            branch: str | None = None,
            depth: int = 0,
            template: bool = False,
        ) -> tuple[str | None, list[str]]:
            """Return the list's first node and the nodes control can exit through."""
            if not isinstance(steps, (list, tuple)):
                return None, []
            first: str | None = None
            previous_exits: list[str] = []
            for raw in steps:
                if not isinstance(raw, dict):
                    continue
                raw_id = raw.get("id")
                node_id = raw_id if isinstance(raw_id, str) and raw_id else f"step-{len(nodes)}"
                if node_id in known_ids:
                    # Valid definitions cannot duplicate ids; retain a graph for malformed input.
                    node_id = f"{node_id}-{len(nodes)}"
                known_ids.add(node_id)
                step_type = str(raw.get("type", "command"))
                options = raw.get("options")
                max_iterations = raw.get("max_iterations")
                nodes.append(
                    GraphNode(
                        id=node_id,
                        label=str(raw.get("name") or node_id),
                        type=step_type,
                        parent_id=parent_id,
                        branch=branch,
                        depth=depth,
                        order=len(nodes),
                        gate=step_type == "gate",
                        message=(str(raw["message"]) if raw.get("message") else ""),
                        options=tuple(str(item) for item in options) if isinstance(options, list) else (),
                        verdict_input=(
                            str(raw["verdict_input"]) if raw.get("verdict_input") else None
                        ),
                        on_reject=(str(raw["on_reject"]) if raw.get("on_reject") else None),
                        max_iterations=max_iterations if isinstance(max_iterations, int) else None,
                        is_template=template,
                    )
                )
                if first is None:
                    first = node_id
                # A branch container reaches its successor through its branch
                # exits, never by falling through itself.
                for source in previous_exits:
                    edges.append(GraphEdge(source, node_id, "sequence"))

                def add_branch(
                    children: Any,
                    label: str,
                    kind: str = "branch",
                    parent: str = node_id,
                ) -> list[str]:
                    child_first, child_exits = add_steps(children, parent, label, depth + 1, template)
                    if child_first is not None:
                        edges.append(GraphEdge(parent, child_first, kind, label))
                    # An empty or missing branch falls through from the container.
                    return child_exits or [parent]

                if step_type == "if":
                    exits = [*add_branch(raw.get("then"), "then"), *add_branch(raw.get("else"), "else")]
                elif step_type == "switch":
                    exits = []
                    cases = raw.get("cases")
                    if isinstance(cases, dict):
                        for case, children in cases.items():
                            exits.extend(add_branch(children, str(case)))
                    exits.extend(add_branch(raw.get("default"), "default"))
                elif step_type in ("while", "do-while"):
                    _body_first, body_exits = add_steps(
                        raw.get("steps"), node_id, "body", depth + 1, template
                    )
                    if _body_first is not None:
                        edges.append(GraphEdge(node_id, _body_first, "branch", "body"))
                    for source in body_exits:
                        edges.append(GraphEdge(source, node_id, "loop", "repeat"))
                    exits = [node_id]
                elif step_type == "fan-out":
                    child = raw.get("step")
                    child_first, _child_exits = add_steps(
                        [child] if isinstance(child, dict) else [],
                        node_id,
                        "each",
                        depth + 1,
                        True,
                    )
                    if child_first is not None:
                        edges.append(GraphEdge(node_id, child_first, "fanout", "each"))
                    exits = [node_id]
                elif step_type == "fan-in":
                    wait_for = raw.get("wait_for")
                    if isinstance(wait_for, list):
                        for source in wait_for:
                            if isinstance(source, str):
                                edges.append(GraphEdge(source, node_id, "join", "join"))
                    exits = [node_id]
                else:
                    exits = [node_id]

                previous_exits = list(dict.fromkeys(exits))
            return first, previous_exits

        add_steps(effective_steps)
        return ControlFlowGraph(tuple(nodes), tuple(edges))
