"""Walk a parsed execution tree: active node, scoped indices and iteration.

The engine's definition of the active step is the first node whose ``phase`` is
not ``done`` in a children-first walk (a node's children come before the node
itself). A ``done`` node's subtree is skipped entirely, because the engine may
leave a handled ``continue_on_error`` child ``blocked`` while its call node has
already settled. The per-node ``active`` flag is deliberately ignored: the
engine sets it on every entered node, so enclosing calls carry it too.

Scope paths and occurrence paths come from the same walk, so gate evidence,
timings and the runway can be keyed by scope occurrence rather than by bare id.
"""

from __future__ import annotations

from typing import Any

from .execution_tree import (
    WORKFLOW_TYPE,
    ActiveNode,
    ExecutionTree,
    SequenceNode,
    StepNode,
)


def iter_sequences(
    sequence: SequenceNode, enclosing: tuple[str, ...] = ()
) -> list[tuple[SequenceNode, tuple[str, ...]]]:
    """Every sequence in the tree with the call step ids that enclose it."""
    found: list[tuple[SequenceNode, tuple[str, ...]]] = [(sequence, enclosing)]
    for node in sequence.steps:
        child_enclosing = enclosing
        if node.kind == WORKFLOW_TYPE and node.children:
            child_enclosing = (*enclosing, node.step_id)
        for child in node.children:
            found.extend(iter_sequences(child, child_enclosing))
    return found


def iter_steps(
    tree: ExecutionTree, sequence: SequenceNode | None = None, enclosing: tuple[str, ...] = ()
) -> tuple[StepNode, ...]:
    """Every node of the tree, parents before children, in persisted order."""
    sequence = tree.root if sequence is None else sequence
    collected: list[StepNode] = []
    for node in sequence.steps:
        collected.append(node)
        child_enclosing = enclosing
        if node.kind == WORKFLOW_TYPE and node.children:
            child_enclosing = (*enclosing, node.step_id)
        for child in node.children:
            collected.extend(iter_steps(tree, child, child_enclosing))
    return tuple(collected)


def iter_bound_calls(tree: ExecutionTree) -> tuple[StepNode, ...]:
    """Every bound ``type: workflow`` call, including nested ones."""
    return tuple(node for node in iter_steps(tree) if node.is_call and node.is_bound)


def enclosing_calls_of(tree: ExecutionTree, target: StepNode) -> tuple[str, ...]:
    """The call step ids on the path from the root to ``target``."""
    return _find_enclosing(tree.root, target.key, ()) or ()


def _find_enclosing(
    sequence: SequenceNode, key: tuple[Any, ...], enclosing: tuple[str, ...]
) -> tuple[str, ...] | None:
    for node in sequence.steps:
        child_enclosing = enclosing
        if node.kind == WORKFLOW_TYPE and node.children:
            child_enclosing = (*enclosing, node.step_id)
        if node.key == key:
            return enclosing
        for child in node.children:
            found = _find_enclosing(child, key, child_enclosing)
            if found is not None:
                return found
    return None


def active_step(tree: ExecutionTree) -> ActiveNode | None:
    """The engine-equivalent active step with its scope context, or ``None``."""
    if not tree.structurally_valid:
        return None
    return _walk(tree.root, tree.root.workflow_id, ())


def _walk(
    sequence: SequenceNode, workflow_id: str, enclosing: tuple[str, ...]
) -> ActiveNode | None:
    for node in sequence.steps:
        if node.is_done:
            # A settled subtree is skipped whole: a handled child failure can
            # stay ``blocked`` under a call node the engine already completed.
            continue
        child_enclosing = enclosing
        if node.kind == WORKFLOW_TYPE and node.children:
            child_enclosing = (*enclosing, node.step_id)
        for child in node.children:
            found = _walk(child, child.workflow_id, child_enclosing)
            if found is not None:
                return found
        return ActiveNode(
            scope_path=node.scope_path[:-1],
            workflow_id=workflow_id,
            step_id=node.step_id,
            qualified_id=node.qualified_id,
            phase=node.phase,
            result=node.result,
            enclosing_calls=enclosing,
            occurrence_path=node.occurrence_path,
            config=node.config,
            kind=node.kind,
            root_scope=node.root_scope,
        )
    return None


def find_node(tree: ExecutionTree, scope_path: tuple[Any, ...], step_id: str) -> StepNode | None:
    """Locate one node by its scope-qualified identity."""
    key = (*scope_path, step_id)
    return _find_node(tree.root, key)


def ancestors(tree: ExecutionTree, node: StepNode) -> tuple[StepNode, ...]:
    """Every enclosing node of ``node``, outermost first.

    A scope path is the engine's walk path, so its proper prefixes are exactly
    the enclosing nodes; this is how bind-time rule checks know whether a gate
    sits under a loop, a fan-out or another call.
    """
    found: list[StepNode] = []
    key = node.key
    for cut in range(1, len(key)):
        parent = _find_node(tree.root, key[:cut])
        if parent is not None:
            found.append(parent)
    return tuple(found)


def _find_node(sequence: SequenceNode, key: tuple[Any, ...]) -> StepNode | None:
    for node in sequence.steps:
        if node.key == key:
            return node
        for child in node.children:
            found = _find_node(child, key)
            if found is not None:
                return found
    return None


def scoped_key(node: StepNode) -> tuple[Any, ...]:
    """The scope-qualified identity of a node (its own walk path)."""
    return node.scope_path


#: Key prefix shared by every event logged from the run's root scope.
ROOT_TIMING_PREFIX: tuple[str, tuple] = ("", ())


def timing_key(node: StepNode) -> tuple[str, tuple, str]:
    """The log key of a node: ``(workflow_id, occurrence_path, qualified_id)``.

    The engine only writes scope fields on events from a called scope, so an
    event without them belongs to the root scope; root-scope nodes therefore
    collapse to ``("", (), qualified_id)``, which is exactly what the log holds
    (qualified ids already distinguish loop iterations).
    """
    if node.root_scope:
        return (*ROOT_TIMING_PREFIX, node.qualified_id)
    return (node.workflow_id, node.occurrence_path, node.qualified_id)


def step_index(tree: ExecutionTree) -> dict[tuple[Any, ...], StepNode]:
    """Every node keyed by its scope-qualified identity."""
    return {node.key: node for node in iter_steps(tree)}


def display_scope_path(scope_path: tuple[Any, ...]) -> str:
    """Join a scope path for the user: ``review-release > review``."""
    return " > ".join(str(part) for part in scope_path)
