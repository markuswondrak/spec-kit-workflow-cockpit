"""Parse effective workflow definitions into an immutable control-flow graph.

A ``type: workflow`` step runs another workflow as a private scope in the same
run, so the graph models a call as a node whose children come from the called
definition. Node identity is the engine's walk path (``scope_path``), so a bare
step id that appears in two scopes stays distinct, while ``by_id`` keeps the
original flat lookup for root-scope consumers.

The declared graph (resolved overlays plus installed call targets) is used for
Start validation. A run that is already bound uses
:func:`graph_from_execution_tree`, which reads the frozen definitions from
``state.json`` instead of the current install, per FR-010.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any

from .execution_tree import ExecutionTree, SequenceNode, StepNode

#: The engine's maximum call depth; used only to stop Cockpit recursing.
MAX_CALL_DEPTH = 16


@dataclass(frozen=True)
class GraphNode:
    """One workflow step, including inline control-flow children and calls."""

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
    #: Engine walk path ending at this node; the node's identity.
    scope_path: tuple[Any, ...] = ()
    workflow_id: str = ""
    is_call: bool = False
    #: False while a call's target cannot be shown yet (dynamic or unresolved).
    target_resolved: bool = True
    #: The configured call target, and why it could not be resolved.
    target: str = ""
    target_error: str = ""
    parent_key: tuple[Any, ...] | None = None
    #: The raw ``input:`` mapping of a call step, used to trace verdict inputs.
    input_mapping: Any = None

    @property
    def key(self) -> tuple[Any, ...]:
        return self.scope_path or (self.id,)

    @property
    def scope_root(self) -> tuple[Any, ...]:
        """The scope that contains this node (its parent's key)."""
        return self.key[:-1]

    @property
    def display_scope_path(self) -> str:
        return " > ".join(str(part) for part in self.key)


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
        """Bare-id lookup, first occurrence wins (legacy root-scope consumers)."""
        found: dict[str, GraphNode] = {}
        for node in self.nodes:
            found.setdefault(node.id, node)
        return found

    @property
    def by_key(self) -> dict[tuple[Any, ...], GraphNode]:
        return {node.key: node for node in self.nodes}

    @property
    def declared_ids(self) -> frozenset[str]:
        return frozenset(node.id for node in self.nodes)

    @property
    def calls(self) -> tuple[GraphNode, ...]:
        return tuple(node for node in self.nodes if node.is_call)


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


def _step_options(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, (list, tuple)):
        return tuple(str(item) for item in raw)
    return ()


class WorkflowDefinitionParser:
    """Build a graph from the resolver's overlay-composed raw step mappings.

    With ``expand_calls`` the parser follows literal ``type: workflow`` targets
    into their installed definitions so Start validation covers every scope.
    Dynamic targets stay leaves, because the engine resolves them only at run
    time (clarified: they must not block Start).
    """

    def __init__(
        self,
        *,
        expand_calls: bool = False,
        resolve_definition: Callable[[str], Iterable[dict[str, Any]] | None] | None = None,
        check_installed: Callable[[str], str | None] | None = None,
        max_depth: int = MAX_CALL_DEPTH,
        root_workflow_id: str = "",
    ) -> None:
        self.expand_calls = expand_calls
        self.resolve_definition = resolve_definition
        self.check_installed = check_installed
        self.max_depth = max_depth
        self.root_workflow_id = root_workflow_id

    def parse(self, effective_steps: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> ControlFlowGraph:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        known_keys: set[tuple[Any, ...]] = set()

        def add_steps(
            steps: Any,
            parent_key: tuple[Any, ...] | None = None,
            parent_id: str | None = None,
            branch: str | None = None,
            depth: int = 0,
            template: bool = False,
            scope: tuple[Any, ...] = (),
            workflow_id: str = "",
            visited: frozenset[str] = frozenset(),
        ) -> tuple[tuple[Any, ...] | None, list[tuple[Any, ...]]]:
            """Return the first node key and the keys control can exit through."""
            if not isinstance(steps, (list, tuple)):
                return None, []
            first: tuple[Any, ...] | None = None
            previous_exits: list[tuple[Any, ...]] = []
            for raw in steps:
                if not isinstance(raw, dict):
                    continue
                raw_id = raw.get("id")
                node_id = raw_id if isinstance(raw_id, str) and raw_id else f"step-{len(nodes)}"
                key = (*scope, node_id)
                if key in known_keys:
                    # Valid definitions cannot duplicate ids inside a scope;
                    # retain a graph for malformed input.
                    node_id = f"{node_id}-{len(nodes)}"
                    key = (*scope, node_id)
                known_keys.add(key)
                step_type = str(raw.get("type", "command"))
                max_iterations = raw.get("max_iterations")
                node = GraphNode(
                    id=node_id,
                    label=str(raw.get("name") or node_id),
                    type=step_type,
                    parent_id=parent_id,
                    branch=branch,
                    depth=depth,
                    order=len(nodes),
                    gate=step_type == "gate",
                    message=(str(raw["message"]) if raw.get("message") else ""),
                    options=_step_options(raw.get("options")),
                    verdict_input=(str(raw["verdict_input"]) if raw.get("verdict_input") else None),
                    on_reject=(str(raw["on_reject"]) if raw.get("on_reject") else None),
                    max_iterations=max_iterations if isinstance(max_iterations, int) else None,
                    is_template=template,
                    scope_path=key,
                    workflow_id=workflow_id,
                    is_call=step_type == "workflow",
                    target=str(raw.get("workflow") or "") if step_type == "workflow" else "",
                    parent_key=parent_key,
                    input_mapping=(raw.get("input") if step_type == "workflow" else None),
                )
                nodes.append(node)
                if first is None:
                    first = key
                # Edges keep bare ids for the flat root-scope consumers; a
                # scoped node's successor is not projected through them.
                if not scope:
                    for source in previous_exits:
                        edges.append(GraphEdge(source[-1], node_id, "sequence"))

                def add_branch(
                    children: Any,
                    label: str,
                    kind: str = "branch",
                    parent: GraphNode = node,
                    child_index: int | None = None,
                ) -> list[tuple[Any, ...]]:
                    child_scope = (
                        parent.key if child_index is None else (*parent.key, child_index)
                    )
                    child_first, child_exits = add_steps(
                        children,
                        parent.key,
                        parent.id,
                        label,
                        depth + 1,
                        template,
                        child_scope,
                        parent.workflow_id,
                        visited,
                    )
                    if child_first is not None and not scope:
                        edges.append(GraphEdge(parent.id, child_first[-1], kind, label))
                    # An empty or missing branch falls through from the container.
                    return child_exits or [parent.key]

                if step_type == "if":
                    exits = [
                        *add_branch(raw.get("then"), "then", child_index=0),
                        *add_branch(raw.get("else"), "else", child_index=1),
                    ]
                elif step_type == "switch":
                    exits = []
                    cases = raw.get("cases")
                    index = 0
                    if isinstance(cases, dict):
                        for case, children in cases.items():
                            exits.extend(add_branch(children, str(case), child_index=index))
                            index += 1
                    exits.extend(add_branch(raw.get("default"), "default", child_index=index))
                elif step_type in ("while", "do-while"):
                    _body_first, body_exits = add_steps(
                        raw.get("steps"),
                        node.key,
                        node_id,
                        "body",
                        depth + 1,
                        template,
                        (*key, 0),
                        workflow_id,
                        visited,
                    )
                    if _body_first is not None and not scope:
                        edges.append(GraphEdge(node_id, _body_first[-1], "branch", "body"))
                    if not scope:
                        for source in body_exits:
                            edges.append(GraphEdge(source[-1], node_id, "loop", "repeat"))
                    exits = [key]
                elif step_type == "fan-out":
                    child = raw.get("step")
                    child_first, _child_exits = add_steps(
                        [child] if isinstance(child, dict) else [],
                        node.key,
                        node_id,
                        "each",
                        depth + 1,
                        True,
                        (*key, 0),
                        workflow_id,
                        visited,
                    )
                    if child_first is not None and not scope:
                        edges.append(GraphEdge(node_id, child_first[-1], "fanout", "each"))
                    exits = [key]
                elif step_type == "fan-in":
                    wait_for = raw.get("wait_for")
                    if isinstance(wait_for, list) and not scope:
                        for source in wait_for:
                            if isinstance(source, str):
                                edges.append(GraphEdge(source, node_id, "join", "join"))
                    exits = [key]
                elif step_type == "workflow":
                    self._expand_call(
                        node, len(nodes) - 1, nodes, known_keys, depth, visited, add_steps,
                    )
                    exits = [key]
                else:
                    exits = [key]

                previous_exits = [*dict.fromkeys(exits)]
            return first, previous_exits

        add_steps(effective_steps or (), workflow_id=self.root_workflow_id)
        return ControlFlowGraph(tuple(nodes), tuple(edges))

    def _expand_call(
        self,
        node: GraphNode,
        index: int,
        nodes: list[GraphNode],
        known_keys: set[tuple[Any, ...]],
        depth: int,
        visited: frozenset[str],
        add_steps: Callable[..., Any],
    ) -> None:
        """Follow a literal call target into its definition."""
        if not self.expand_calls:
            return
        target = node.target
        if not target:
            _mark_unresolved(nodes, index, "the call declares no target")
            return
        if "{{" in target:
            _mark_unresolved(nodes, index, "dynamic")
            return
        if target in visited or depth >= self.max_depth:
            _mark_unresolved(nodes, index, "cycle")
            return
        error = self.check_installed(target) if self.check_installed is not None else None
        if error:
            _mark_unresolved(nodes, index, error)
            return
        steps = self.resolve_definition(target) if self.resolve_definition is not None else None
        if steps is None:
            _mark_unresolved(nodes, index, f"target {target!r} is not installed")
            return
        add_steps(
            list(steps),
            node.key,
            node.id,
            None,
            depth + 1,
            False,
            node.key,
            target,
            (*visited, target),
        )


def _mark_unresolved(nodes: list[GraphNode], index: int, reason: str) -> None:
    """Mark a call node as unresolved, keeping its row order."""
    nodes[index] = replace(nodes[index], target_resolved=False, target_error=reason)


def _sequence_steps(sequence: SequenceNode) -> Iterable[StepNode]:
    for step in sequence.steps:
        yield step
        for child in step.children:
            yield from _sequence_steps(child)


def graph_from_execution_tree(tree: ExecutionTree) -> ControlFlowGraph:
    """Build the bound run's graph from its frozen execution tree (FR-010).

    Only the scope occurrence that holds the active node is expanded for loops
    and fan-outs; a repeated call's other occurrences are already covered by the
    scope-qualified timings, and rendering every occurrence would duplicate rows.
    Nested steps therefore always come from the definition the engine froze at
    binding time, even if the installed workflow has changed since (US3.5).
    """
    active_key = tree.active.node_key if tree.active else None
    nodes: list[GraphNode] = []

    def pick_child(children: tuple[SequenceNode, ...]) -> int:
        if active_key is not None:
            for index, child in enumerate(children):
                if any(step.key == active_key for step in _sequence_steps(child)):
                    return index
        return 0

    def add_sequence(
        sequence: SequenceNode,
        parent_key: tuple[Any, ...] | None,
        parent_id: str | None,
        branch: str | None,
        depth: int,
    ) -> None:
        for step in sequence.steps:
            config = step.config
            max_iterations = config.get("max_iterations")
            nodes.append(
                GraphNode(
                    id=step.step_id,
                    label=str(config.get("name") or step.step_id),
                    type=step.kind,
                    parent_id=parent_id,
                    branch=branch,
                    depth=depth,
                    order=len(nodes),
                    gate=step.kind == "gate",
                    message=str(config.get("message") or ""),
                    options=_step_options(config.get("options")),
                    verdict_input=step.verdict_input,
                    on_reject=step.on_reject,
                    max_iterations=max_iterations if isinstance(max_iterations, int) else None,
                    is_template=(branch == "each"),
                    scope_path=step.key,
                    workflow_id=step.workflow_id,
                    is_call=step.is_call,
                    target_resolved=(step.is_bound or not step.dynamic_target),
                    target=step.target or "",
                    target_error=("dynamic" if step.dynamic_target and not step.is_bound else ""),
                    parent_key=parent_key,
                    input_mapping=(config.get("input") if step.is_call else None),
                )
            )
            if step.children:
                child = step.children[pick_child(step.children)]
                child_branch = {"while": "body", "do-while": "body", "fan-out": "each"}.get(step.kind)
                add_sequence(child, step.key, step.step_id, child_branch, depth + 1)

    add_sequence(tree.root, None, None, None, 0)
    return ControlFlowGraph(tuple(nodes), ())
