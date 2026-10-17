"""Trace a child gate's ``verdict_input`` back to the root input that feeds it.

The engine accepts only *root* input names on ``resume -i``, and re-evaluates
each bound call's ``input:`` mapping against the merged root inputs. A mapping
value that is exactly ``{{ inputs.<name> }}`` (one whole-string reference) is
therefore an identity step in that chain; anything else (a literal, a
concatenation, two references) means the child value does not follow a root
input, so the gate is undecidable from Cockpit and must be reported rather than
guessed at.

The module is Textual-free and pure: callers supply the call chain either from
the frozen execution tree (a bound run) or from the resolved definitions (Start).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

#: A mapping value that is exactly one root-input reference, e.g. ``{{ inputs.x }}``.
_EXACT_REFERENCE = re.compile(r"^\s*\{\{\s*inputs\.([A-Za-z0-9_.\-]+)\s*\}\}\s*$")

#: The engine's maximum call depth; Cockpit only stops recursing here.
MAX_TRACE_DEPTH = 16

#: Control-flow keys whose children declare further steps.
_NESTED_KEYS = ("then", "else", "steps", "default")


@dataclass(frozen=True)
class TracedInput:
    """The root input name that supplies a child gate's verdict."""

    root_input: str


@dataclass(frozen=True)
class Untraceable:
    """A child verdict input no root input feeds, with the reason why."""

    reason: str
    scope_path: tuple[Any, ...] = ()

    @property
    def display_scope_path(self) -> str:
        return " > ".join(str(part) for part in self.scope_path)


@dataclass(frozen=True)
class CallStep:
    """One ``type: workflow`` step on the path to a gate."""

    step_id: str
    input_mapping: Mapping[str, Any]

    @property
    def scope_component(self) -> str:
        return self.step_id


def trace_chain(
    chain: Iterable[CallStep], verdict_input: str | None
) -> TracedInput | Untraceable:
    """Walk ``chain`` from the innermost call outwards to the root input name."""
    calls = tuple(chain)
    if not verdict_input:
        return Untraceable("the gate declares no verdict_input")
    name = verdict_input
    for call in reversed(calls):
        if not isinstance(call.input_mapping, Mapping):
            return Untraceable(
                f"call {call.step_id!r} declares no input mapping for {name!r}",
                (call.step_id,),
            )
        raw = call.input_mapping.get(name)
        if not isinstance(raw, str):
            return Untraceable(
                f"call {call.step_id!r} does not map {name!r} from the parent scope",
                (call.step_id,),
            )
        match = _EXACT_REFERENCE.match(raw)
        if match is None:
            return Untraceable(
                f"call {call.step_id!r} maps {name!r} from {raw!r}, which is not a single "
                "root input reference",
                (call.step_id,),
            )
        name = match.group(1)
    return TracedInput(name)


@dataclass(frozen=True)
class VerdictTraceReport:
    """Every root input consumed by a verdict gate, and every untraceable one."""

    root_inputs: frozenset[str] = frozenset()
    problems: tuple[Untraceable, ...] = ()


def _iter_steps(steps: Iterable[Any]) -> Iterable[Mapping[str, Any]]:
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        yield step
        for key in _NESTED_KEYS:
            nested = step.get(key)
            if isinstance(nested, list):
                yield from _iter_steps(nested)
        cases = step.get("cases")
        if isinstance(cases, dict):
            for case_steps in cases.values():
                if isinstance(case_steps, list):
                    yield from _iter_steps(case_steps)


def collect_verdict_traces(
    steps: Iterable[Any],
    resolve_definition: Callable[[str], Iterable[Any] | None] | None = None,
    *,
    max_depth: int = MAX_TRACE_DEPTH,
) -> VerdictTraceReport:
    """Every verdict gate in the composition, traced to its root input.

    Dynamic call targets are skipped: the engine binds them at run time, so they
    are re-checked then (FR-012) rather than guessing at Start.
    """
    root_inputs: set[str] = set()
    problems: list[Untraceable] = []

    def walk(
        current: Iterable[Any],
        chain: tuple[CallStep, ...],
        visited: frozenset[str],
        depth: int,
    ) -> None:
        for step in _iter_steps(current):
            step_id = step.get("id")
            step_type = str(step.get("type", "command"))
            verdict = step.get("verdict_input")
            if step_type == "gate" and isinstance(verdict, str) and verdict:
                traced = trace_chain(chain, verdict)
                if isinstance(traced, TracedInput):
                    root_inputs.add(traced.root_input)
                else:
                    scope = tuple(call.scope_component for call in chain) + (
                        step_id if isinstance(step_id, str) else "gate",
                    )
                    problems.append(Untraceable(traced.reason, scope))
            if step_type != "workflow":
                continue
            target = step.get("workflow")
            if not isinstance(target, str) or not target or "{{" in target:
                continue
            if target in visited or depth >= max_depth or resolve_definition is None:
                continue
            sub_steps = resolve_definition(target)
            if sub_steps is None:
                continue
            mapping = step.get("input")
            chain_step = CallStep(
                step_id=step_id if isinstance(step_id, str) else target,
                input_mapping=mapping if isinstance(mapping, Mapping) else {},
            )
            walk(sub_steps, (*chain, chain_step), (*visited, target), depth + 1)

    walk(steps, (), frozenset(), 0)
    return VerdictTraceReport(frozenset(root_inputs), tuple(problems))


def call_chain_from_tree(tree: Any, enclosing_calls: Iterable[str]) -> tuple[CallStep, ...]:
    """The call chain to a node, using the frozen definitions in the tree."""
    from .execution_walk import iter_steps

    by_id: dict[str, Mapping[str, Any]] = {}
    for node in iter_steps(tree):
        if node.is_call:
            by_id.setdefault(node.step_id, node.config)
    chain: list[CallStep] = []
    for call_id in enclosing_calls:
        config = by_id.get(call_id, {})
        mapping = config.get("input") if isinstance(config, Mapping) else None
        chain.append(
            CallStep(
                step_id=call_id,
                input_mapping=mapping if isinstance(mapping, Mapping) else {},
            )
        )
    return tuple(chain)
