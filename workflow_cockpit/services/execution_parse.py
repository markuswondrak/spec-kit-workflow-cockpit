"""Low-level decoding and building of the persisted execution tree.

Split out of :mod:`workflow_cockpit.services.execution_tree` so the read model
file stays focused on the frozen dataclasses and their validation. This module
owns the engine's byte-level rules: zip a sequence's YAML ``source`` against its
parallel ``nodes`` list, and share a child sequence's steps with its parent when
the child has no ``source`` of its own (a call body reads ``binding.definition``,
a fan-out item reads ``template``, later loop iterations read iteration 0).

The dataclasses and constants stay in ``execution_tree``; this module imports
them, and ``execution_tree.parse`` imports this module lazily, so there is no
import cycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import yaml

from .execution_tree import (
    FANOUT_TYPE,
    LOOP_TYPES,
    WORKFLOW_TYPE,
    Binding,
    SequenceNode,
    StepNode,
)


class TreeError(Exception):
    """The persisted structure cannot be read as an execution tree."""


def build_root(
    sequence: Mapping[str, Any],
    *,
    workflow_id: str,
    root_offset: int,
) -> SequenceNode:
    """Build the root sequence, and with it every child sequence."""
    return _build_sequence(
        sequence,
        workflow_id=workflow_id,
        base_scope=(),
        base_occurrence=(),
        enclosing=(),
        cache={},
        root_offset=root_offset,
    )


def _frozen(value: Any) -> Any:
    """A read-only view of a decoded mapping so the tree cannot be mutated."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _frozen(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_frozen(item) for item in value)
    return value


def _decode_steps(source: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(source, str):
        raise TreeError("source")
    try:
        data = yaml.safe_load(source)
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise TreeError("yaml") from exc
    if not isinstance(data, list):
        raise TreeError("steps")
    steps: list[Mapping[str, Any]] = []
    for entry in data:
        steps.append(entry if isinstance(entry, Mapping) else {})
    return tuple(steps)


def _steps_from_definition(definition: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(definition, Mapping):
        raise TreeError("definition")
    steps = definition.get("steps")
    if not isinstance(steps, (list, tuple)):
        raise TreeError("definition.steps")
    return tuple(entry if isinstance(entry, Mapping) else {} for entry in steps)


def _build_sequence(
    sequence: Mapping[str, Any],
    *,
    workflow_id: str,
    base_scope: tuple[Any, ...],
    base_occurrence: tuple[Any, ...],
    enclosing: tuple[str, ...],
    cache: dict[str, Any],
    qualifier: tuple[str, int, bool] | None = None,
    root_offset: int = 0,
    steps: tuple[Mapping[str, Any], ...] | None = None,
    root_scope: bool = True,
) -> SequenceNode:
    """Build one sequence, decoding its own or inherited step list."""
    if steps is None:
        source = sequence.get("source")
        if source is None and qualifier is None:
            raise TreeError("sequence.source")
        decoded = _decode_cached(source, cache)
        if root_offset:
            if len(decoded) - root_offset == _expected_nodes(sequence):
                decoded = decoded[root_offset:]
            elif len(decoded) != _expected_nodes(sequence):
                raise TreeError("offset")
        steps = decoded

    nodes = sequence.get("nodes")
    if not isinstance(nodes, (list, tuple)) or len(nodes) != len(steps):
        raise TreeError("nodes")

    built: list[StepNode] = []
    for index, (step, node) in enumerate(zip(steps, nodes, strict=False)):
        if not isinstance(node, Mapping):
            raise TreeError("node")
        raw_id = step.get("id")
        step_id = raw_id if isinstance(raw_id, str) and raw_id else f"step-{index}"
        if qualifier is not None:
            prefix, item_index, include_zero = qualifier
            if include_zero or item_index > 0:
                qualified = f"{prefix}:{step_id}:{item_index}"
            else:
                qualified = step_id
        else:
            qualified = step_id
        scope_path = (*base_scope, step_id)
        occurrence_path = (*base_occurrence, index)
        children, binding = _build_children(
            step,
            node,
            workflow_id=workflow_id,
            scope_path=scope_path,
            occurrence_path=occurrence_path,
            enclosing=enclosing,
            cache=cache,
            root_scope=root_scope,
        )
        built.append(
            StepNode(
                step_id=step_id,
                qualified_id=qualified,
                kind=_kind(step),
                config=_frozen(step),
                phase=str(node.get("phase") or ""),
                active=bool(node.get("active", False)),
                result=_frozen(node["result"]) if isinstance(node.get("result"), Mapping) else None,
                outcome=node.get("outcome") if isinstance(node.get("outcome"), str) else None,
                error=node.get("error") if isinstance(node.get("error"), str) else None,
                scope_path=scope_path,
                occurrence_path=occurrence_path,
                workflow_id=workflow_id,
                children=children,
                binding=binding,
                index=index,
                root_scope=root_scope,
            )
        )
    return SequenceNode(tuple(built), workflow_id)


def _expected_nodes(sequence: Mapping[str, Any]) -> int:
    nodes = sequence.get("nodes")
    return len(nodes) if isinstance(nodes, (list, tuple)) else -1


def _kind(step: Mapping[str, Any]) -> str:
    raw = step.get("type", "command")
    return raw if isinstance(raw, str) and raw else "command"


def _decode_cached(source: Any, cache: dict[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Decode each distinct YAML string exactly once per parse."""
    if source is None:
        raise TreeError("source")
    if not isinstance(source, str):
        raise TreeError("source")
    cached = cache.get(source)
    if cached is None:
        cached = _decode_steps(source)
        cache[source] = cached
    return cached


def _build_children(
    step: Mapping[str, Any],
    node: Mapping[str, Any],
    *,
    workflow_id: str,
    scope_path: tuple[Any, ...],
    occurrence_path: tuple[Any, ...],
    enclosing: tuple[str, ...],
    cache: dict[str, Any],
    root_scope: bool = True,
) -> tuple[tuple[SequenceNode, ...], Binding | None]:
    """Build the child sequences and the binding of one node.

    The engine shares a child sequence's step list with its parent when the
    child has no ``source`` of its own: a call body reads the frozen
    ``binding.definition``, a fan-out item reads ``template``, and a loop
    iteration after the first reads iteration 0's steps.
    """
    raw_children = node.get("children")
    children = list(raw_children) if isinstance(raw_children, (list, tuple)) else []
    kind = _kind(step)
    binding: Binding | None = None

    if kind == WORKFLOW_TYPE:
        raw_binding = node.get("binding")
        if raw_binding is not None:
            if not isinstance(raw_binding, Mapping):
                raise TreeError("binding")
            definition_source = raw_binding.get("definition")
            definition = _decode_mapping(definition_source, cache)
            inputs = raw_binding.get("inputs")
            binding = Binding(
                workflow=str(raw_binding.get("workflow") or ""),
                definition=definition,
                inputs=_frozen(inputs) if isinstance(inputs, Mapping) else MappingProxyType({}),
                workflow_dir=(
                    raw_binding.get("workflow_dir")
                    if isinstance(raw_binding.get("workflow_dir"), str)
                    else None
                ),
            )
        if not children:
            if binding is not None:
                raise TreeError("binding without children")
            return (), binding
        child_steps = _steps_from_definition(binding.definition if binding is not None else None)
        built = _build_sequence(
            children[0],
            workflow_id=binding.workflow if binding is not None else workflow_id,
            base_scope=scope_path,
            base_occurrence=(*occurrence_path, "workflow"),
            enclosing=(*enclosing, _step_id(step)),
            cache=cache,
            steps=child_steps,
            root_scope=False,
        )
        return (built,), binding

    if kind == FANOUT_TYPE:
        if not children:
            return (), None
        template_source = node.get("template")
        decoded_template = _decode_mapping(template_source, cache) if template_source is not None else None
        if decoded_template is None:
            raise TreeError("fan-out template")
        item_step: dict[str, Any] = {"id": "item", **dict(decoded_template)}
        built_items: list[SequenceNode] = []
        for item_index, child in enumerate(children):
            built_items.append(
                _build_sequence(
                    child if isinstance(child, Mapping) else {},
                    workflow_id=workflow_id,
                    base_scope=(*scope_path, item_index),
                    base_occurrence=(*occurrence_path, "item", item_index),
                    enclosing=enclosing,
                    cache=cache,
                    qualifier=(_step_id(step), item_index, True),
                    steps=(item_step,),
                    root_scope=root_scope,
                )
            )
        return tuple(built_items), None

    if kind in LOOP_TYPES:
        if not children:
            return (), None
        built_iterations: list[SequenceNode] = []
        first_steps: tuple[Mapping[str, Any], ...] | None = None
        for iteration, child in enumerate(children):
            child_mapping = child if isinstance(child, Mapping) else {}
            built = _build_sequence(
                child_mapping,
                workflow_id=workflow_id,
                base_scope=(*scope_path, iteration),
                base_occurrence=(*occurrence_path, iteration),
                enclosing=enclosing,
                cache=cache,
                qualifier=(_step_id(step), iteration, False),
                steps=first_steps,
                root_scope=root_scope,
            )
            if first_steps is None:
                first_steps = _child_step_configs(child_mapping, cache)
            built_iterations.append(built)
        return tuple(built_iterations), None

    # A plain step with child sequences is not part of the persisted format.
    if children:
        raise TreeError("unexpected children")
    return (), None


def _child_step_configs(
    sequence: Mapping[str, Any], cache: dict[str, Any]
) -> tuple[Mapping[str, Any], ...]:
    source = sequence.get("source")
    if source is None:
        raise TreeError("loop body source")
    return _decode_cached(source, cache)


def _step_id(step: Mapping[str, Any]) -> str:
    raw = step.get("id")
    return raw if isinstance(raw, str) and raw else ""


def _decode_mapping(source: Any, cache: dict[str, Any]) -> Mapping[str, Any]:
    if not isinstance(source, str):
        raise TreeError("definition source")
    cached = cache.get(source)
    if cached is None:
        try:
            data = yaml.safe_load(source)
        except yaml.YAMLError as exc:  # pragma: no cover - defensive
            raise TreeError("yaml") from exc
        if not isinstance(data, Mapping):
            raise TreeError("definition")
        cached = _frozen(data)
        cache[source] = cached
    return cached
