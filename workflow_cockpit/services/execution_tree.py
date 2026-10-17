"""Read the engine's persisted execution tree from ``state.json``.

Spec Kit 1.1.3 stores a run as a tree of scopes: the root sequence plus one
child sequence per bound ``type: workflow`` call, loop iteration and fan-out
item. Nodes carry ``phase``/``active``/``result``/``outcome`` but **no step
ids**: the ids live in a YAML ``source`` string that is zipped with the parallel
``nodes`` list. This module turns that persisted structure into frozen
dataclasses; :mod:`workflow_cockpit.services.execution_walk` walks it.

Cockpit re-implements a *reading* of the format, never importing the engine.
The ``version == 2`` guard is deliberate: the engine itself rejects every other
version, so there is no older format to interpret. Absent ``execution`` is a
legacy run and stays ``None``; a structurally invalid tree is ``UNRESOLVED``,
never an exception.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

#: The only ``execution.version`` Cockpit interprets.
EXECUTION_VERSION = 2

#: Statuses in which the engine leaves the halted node ``blocked`` with a result.
HALTED_STATUSES = frozenset({"paused", "failed", "aborted"})

#: Loop step types whose child sequences beyond the first share the first's steps.
LOOP_TYPES = frozenset({"while", "do-while"})

#: Step types whose children are fanned out as one sequence per item.
FANOUT_TYPE = "fan-out"

#: Step type that runs another workflow as a private scope.
WORKFLOW_TYPE = "workflow"


class Resolution(str, Enum):
    """Whether the persisted tree yields one trustworthy active position."""

    OK = "ok"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class UnsupportedExecution:
    """An ``execution`` block Cockpit must not interpret.

    The version is kept for the diagnostic; ``None`` means the block itself was
    not a mapping, so no version could be read at all.
    """

    version: Any = None


@dataclass(frozen=True)
class Binding:
    """The frozen target of a bound ``type: workflow`` call."""

    workflow: str
    definition: Mapping[str, Any]
    inputs: Mapping[str, Any]
    workflow_dir: str | None = None


@dataclass(frozen=True)
class StepNode:
    """One executed step, zipped from the sequence's YAML source and node record."""

    step_id: str
    qualified_id: str
    kind: str
    config: Mapping[str, Any]
    phase: str
    active: bool
    result: Mapping[str, Any] | None
    outcome: str | None
    error: str | None
    scope_path: tuple[Any, ...]
    occurrence_path: tuple[Any, ...]
    workflow_id: str
    children: tuple[SequenceNode, ...]
    binding: Binding | None
    index: int
    #: True only inside the run's root sequence; log events from the root scope
    #: carry no scope fields, so their timing key is the bare qualified id.
    root_scope: bool = True

    @property
    def key(self) -> tuple[Any, ...]:
        """Scope-qualified identity: ``scope_path`` already ends at this node."""
        return self.scope_path

    @property
    def is_call(self) -> bool:
        return self.kind == WORKFLOW_TYPE

    @property
    def is_bound(self) -> bool:
        return self.binding is not None

    @property
    def is_done(self) -> bool:
        return self.phase == "done"

    @property
    def target(self) -> str | None:
        raw = self.config.get("workflow")
        return raw if isinstance(raw, str) and raw else None

    @property
    def dynamic_target(self) -> bool:
        target = self.target
        return bool(target and "{{" in target)

    @property
    def verdict_input(self) -> str | None:
        raw = self.config.get("verdict_input")
        return raw if isinstance(raw, str) and raw else None

    @property
    def on_reject(self) -> str | None:
        raw = self.config.get("on_reject")
        return raw if isinstance(raw, str) and raw else None

    @property
    def continue_on_error(self) -> bool:
        return bool(self.config.get("continue_on_error"))

    @property
    def handled_failure(self) -> bool:
        """A call failure the engine continued past, so the run itself succeeded."""
        own = self.result or {}
        return (
            self.is_call
            and self.continue_on_error
            and self.outcome == "completed"
            and own.get("status") == "failed"
        )


@dataclass(frozen=True)
class SequenceNode:
    """One ordered list of steps: the root, one call body, or one iteration/item."""

    steps: tuple[StepNode, ...]
    workflow_id: str


@dataclass(frozen=True)
class ActiveNode:
    """The engine's active step, with the scope context Cockpit must report."""

    scope_path: tuple[Any, ...]
    workflow_id: str
    step_id: str
    qualified_id: str
    phase: str
    result: Mapping[str, Any] | None
    enclosing_calls: tuple[str, ...]
    occurrence_path: tuple[Any, ...]
    #: The frozen step config, so gate rules read the persisted definition
    #: rather than a second, possibly newer, copy.
    config: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    kind: str = "command"
    root_scope: bool = True

    @property
    def node_key(self) -> tuple[Any, ...]:
        return (*self.scope_path, self.step_id)

    @property
    def verdict_input(self) -> str | None:
        raw = self.config.get("verdict_input")
        return raw if isinstance(raw, str) and raw else None

    @property
    def on_reject(self) -> str | None:
        raw = self.config.get("on_reject")
        return raw if isinstance(raw, str) and raw else None

    @property
    def continue_on_error(self) -> bool:
        return bool(self.config.get("continue_on_error"))

    @property
    def target(self) -> str | None:
        raw = self.config.get("workflow")
        return raw if isinstance(raw, str) and raw else None

    @property
    def dynamic_target(self) -> bool:
        target = self.target
        return bool(target and "{{" in target)

    @property
    def display_scope_path(self) -> tuple[Any, ...]:
        """The full path the user sees, including the active step itself."""
        return (*self.scope_path, self.step_id)


@dataclass(frozen=True)
class ExecutionTree:
    """The persisted execution tree of one run, plus its position cross-check."""

    version: int
    offset: int
    root: SequenceNode
    run_status: str
    current_step_id: str | None
    structurally_valid: bool = True

    @property
    def active(self) -> ActiveNode | None:
        """The engine-equivalent active node, or ``None``."""
        from .execution_walk import active_step

        return active_step(self)

    @property
    def resolution(self) -> Resolution:
        """``OK`` only when one node is both unfinished and the persisted position."""
        if not self.structurally_valid:
            return Resolution.UNRESOLVED
        node = self.active
        if node is None:
            return Resolution.UNRESOLVED
        if self.current_step_id and node.qualified_id != self.current_step_id:
            return Resolution.UNRESOLVED
        if self.run_status in HALTED_STATUSES and not (node.phase == "blocked" and node.result):
            return Resolution.UNRESOLVED
        return Resolution.OK

    @property
    def steps(self) -> tuple[StepNode, ...]:
        """Every node in the tree, children-first order preserved."""
        from .execution_walk import iter_steps

        return iter_steps(self)


def parse(state: Mapping[str, Any]) -> ExecutionTree | UnsupportedExecution | None:
    """Read ``state["execution"]`` into a tree, or report why it cannot be read."""
    execution = state.get("execution") if isinstance(state, Mapping) else None
    if execution is None:
        return None
    if not isinstance(execution, Mapping):
        return UnsupportedExecution(None)
    version = execution.get("version")
    if version != EXECUTION_VERSION:
        return UnsupportedExecution(version)

    run_status = state.get("status") if isinstance(state.get("status"), str) else ""
    current_step_id = state.get("current_step_id")
    current_step_id = current_step_id if isinstance(current_step_id, str) else None
    root_workflow = state.get("workflow_id") if isinstance(state.get("workflow_id"), str) else ""

    from .execution_parse import TreeError, build_root

    try:
        offset = execution.get("offset", 0)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise TreeError("offset")
        sequence = execution.get("sequence")
        if not isinstance(sequence, Mapping):
            raise TreeError("sequence")
        root = build_root(sequence, workflow_id=root_workflow, root_offset=offset)
    except TreeError:
        return ExecutionTree(
            version=EXECUTION_VERSION,
            offset=0,
            root=SequenceNode((), root_workflow),
            run_status=run_status,
            current_step_id=current_step_id,
            structurally_valid=False,
        )
    return ExecutionTree(
        version=EXECUTION_VERSION,
        offset=offset,
        root=root,
        run_status=run_status,
        current_step_id=current_step_id,
    )



