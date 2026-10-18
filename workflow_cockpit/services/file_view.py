"""Build the versioned, bounded, read-only read envelope for one run (US1).

The envelope is the file view: one JSON object describing the current run the way
the UI shows it, built from the same persisted files through the same readers
(``run_state``, ``execution_tree``, ``projection``, ``feature_review``,
``review``). It never writes, never claims, never signals, and never imports the
engine.

Nothing here infers state. Every source that is missing, stale, oversized, or
only partially readable is reported in ``conditions`` and the fields derived from
it stay null, so a consumer can never mistake a guess for persisted evidence
(FR-004). Every read is bounded and reports truncation (FR-008).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .current_run_pointer import CurrentRunPointerReader, PointerState
from .execution_tree import ExecutionTree
from .execution_walk import find_node, timing_key
from .feature_review import FeatureReviewService, resolve_feature_directory
from .file_view_payloads import (
    KIND_MISSING,
    KIND_PARTIAL,
    KIND_STALE,
    KIND_TOO_LARGE,
    Condition,
    feature_files_payload,
    file_payload,
    gate_payload,
    projection_payload,
    step_payload,
)
from .gate_target import resolve_gate_target
from .graph import (
    ControlFlowGraph,
    WorkflowDefinitionParser,
    graph_from_execution_tree,
    resolve_declared_id,
)
from .launch_definition import DefinitionError, definition_from_launch_copy
from .limits import MAX_STATE_BYTES
from .log_aggregator import ROOT_TIMING_PREFIX, RunLogAggregator, TimingIndex
from .run_catalog import RunCatalog, RunCatalogError, RunDescriptor
from .run_claim import ClaimState, RunClaimStore
from .run_state import Freshness, RunStateData, RunStateReader

#: Envelope shape version; bumped on any shape change (FR-001).
SCHEMA_VERSION = 1

#: Statuses that mean the run is over (FR-029/FR-030).
TERMINAL_STATUSES = frozenset({"completed", "failed", "aborted"})


class FileViewError(Exception):
    """Raised for an invalid read request; the CLI maps this to exit code 2."""


@dataclass(frozen=True)
class FileView:
    """One built read envelope plus the exit-relevant facts about it."""

    envelope: dict[str, Any]

    @property
    def has_run(self) -> bool:
        return self.envelope.get("run") is not None


class _ProjectionContext:
    """The minimal composition-aware read state one envelope needs.

    Mirrors the session's composition context for a single stateless read: the
    graph comes from the frozen execution tree when one is readable, timings are
    keyed the way the run's log writes them, and the gate attempt is the
    authoritative execution count of the current gate's scope occurrence.
    """

    def __init__(self, runs_dir: Path, graph: ControlFlowGraph | None) -> None:
        self._runs_dir = Path(runs_dir)
        self._graph = graph
        self._aggregator: RunLogAggregator | None = None

    def graph_for(self, state: RunStateData | None) -> ControlFlowGraph | None:
        tree = getattr(state, "execution", None) if state is not None else None
        if isinstance(tree, ExecutionTree) and tree.structurally_valid:
            return graph_from_execution_tree(tree)
        return self._graph

    def timings(self, state: RunStateData | None, run_id: str | None) -> TimingIndex:
        if run_id is None:
            return TimingIndex()
        scoped = isinstance(getattr(state, "execution", None), ExecutionTree)
        declared = None if scoped else (self._graph.declared_ids if self._graph else frozenset())
        if self._aggregator is None:
            self._aggregator = RunLogAggregator(declared)
        return self._aggregator.update(self._runs_dir / run_id / "log.jsonl")

    def gate_attempt(self, state: RunStateData | None, run_id: str | None) -> int:
        if self._graph is None or state is None or run_id is None:
            return 0
        key: tuple | None = None
        tree = getattr(state, "execution", None)
        if isinstance(tree, ExecutionTree) and tree.active is not None:
            node = find_node(tree, tree.active.scope_path, tree.active.step_id)
            if node is not None:
                key = timing_key(node)
        if key is None:
            declared = resolve_declared_id(state.current_step_id, self._graph.declared_ids)
            if declared is None:
                return 0
            key = (*ROOT_TIMING_PREFIX, declared)
        timing = self.timings(state, run_id).get(key)
        return timing.attempts if timing is not None else 0


def _declared_graph(root: Path, definition: Any) -> ControlFlowGraph | None:
    if definition is None:
        return None
    resolver = _resolver_for(root)
    return WorkflowDefinitionParser(
        expand_calls=True,
        resolve_definition=resolver.effective_steps_of,
        root_workflow_id=definition.id,
    ).parse(definition.effective_steps)


def _resolver_for(root: Path) -> Any:
    from .definition import WorkflowDefinitionResolver

    return WorkflowDefinitionResolver(root)


def _state_conditions(
    state: RunStateData | None,
    run_dir: Path | None,
    conditions: list[Condition],
) -> bool:
    """Report state/inputs/log conditions; return whether run state is usable.

    ``False`` means the state source is conditioned, so every field derived from
    it must stay null rather than be inferred.
    """
    if run_dir is None:
        return False
    state_path = run_dir / "state.json"
    if state is None:
        conditions.append(
            Condition(source="state.json", kind=KIND_MISSING, detail="state.json is unreadable.")
        )
        return False
    if state.too_large or (
        state_path.is_file() and state_path.stat().st_size > MAX_STATE_BYTES
    ):
        conditions.append(
            Condition(
                source="state.json",
                kind=KIND_TOO_LARGE,
                detail=f"state.json exceeds the {MAX_STATE_BYTES} byte bound; it was not parsed.",
            )
        )
        return False
    if state.state_freshness is Freshness.STALE:
        conditions.append(
            Condition(
                source="state.json",
                kind=KIND_STALE,
                detail=state.diagnostic or "state.json could not be re-read.",
            )
        )
        return False
    if not state_path.is_file():
        conditions.append(
            Condition(source="state.json", kind=KIND_MISSING, detail="state.json is missing.")
        )
        return False
    if state.state_freshness in (Freshness.PENDING, Freshness.UNSTABLE):
        conditions.append(
            Condition(
                source="state.json",
                kind=KIND_PARTIAL,
                detail=state.diagnostic or "state.json could not be read completely.",
            )
        )
        return False
    if not (run_dir / "inputs.json").is_file():
        conditions.append(
            Condition(source="inputs.json", kind=KIND_MISSING, detail="inputs.json is missing.")
        )
    log_path = run_dir / "log.jsonl"
    if not log_path.is_file():
        conditions.append(
            Condition(source="log.jsonl", kind=KIND_MISSING, detail="log.jsonl is missing.")
        )
    elif state.log_freshness is Freshness.STALE:
        conditions.append(
            Condition(
                source="log.jsonl",
                kind=KIND_STALE,
                detail="log.jsonl could not be re-read; timings may be incomplete.",
            )
        )
    elif state.log_freshness in (Freshness.PENDING, Freshness.UNSTABLE):
        conditions.append(
            Condition(
                source="log.jsonl",
                kind=KIND_PARTIAL,
                detail="log.jsonl could not be read completely; timings may be incomplete.",
            )
        )
    if state.diagnostic and not any(c.source == "state.json" for c in conditions):
        conditions.append(
            Condition(source="state.json", kind=KIND_PARTIAL, detail=state.diagnostic)
        )
    return True


def _pointer_conditions(pointer_state: PointerState, detail: str, conditions: list[Condition]) -> None:
    if pointer_state is PointerState.DISAGREEMENT:
        conditions.append(Condition(source="current_run", kind=KIND_PARTIAL, detail=detail))
    elif pointer_state is PointerState.UNREADABLE:
        conditions.append(
            Condition(source="current_run", kind=KIND_PARTIAL, detail=detail or "the pointer is unreadable.")
        )


def _claim_owner(root: Path, run_id: str | None) -> str | None:
    if run_id is None:
        return None
    state = RunClaimStore(root).claim_state(run_id, None)
    return state.value if isinstance(state, ClaimState) else str(state)


def _git_branch(root: Path) -> tuple[str | None, str]:
    from .git import GitService

    try:
        read = GitService(root).branch_result()
    except Exception as exc:  # noqa: BLE001 - a Git failure is a condition, never fatal
        return None, str(exc)
    if not read.ok:
        return None, read.error or "the current branch could not be read."
    return read.value, ""


def build_envelope(
    project_root: Path | str,
    *,
    file_path: str | None = None,
    reader: RunStateReader | None = None,
) -> FileView:
    """Build the read envelope for one project/worktree (never writes).

    ``reader`` is an optional injectable :class:`RunStateReader`, so a caller (or
    a test) that already holds a primed reader sees the same stale detection the
    UI's polling loop sees. A fresh reader is created otherwise.
    """
    root = Path(project_root)
    conditions: list[Condition] = []

    pointer = CurrentRunPointerReader(root).read()
    _pointer_conditions(pointer.state, pointer.detail, conditions)
    run_id = pointer.run_id if pointer.usable else None

    runs_dir = root / ".specify" / "workflows" / "runs"
    run_dir = runs_dir / run_id if run_id else None
    descriptor: RunDescriptor | None = None
    if run_id is not None and run_dir is not None:
        if run_dir.is_dir():
            try:
                descriptor = RunCatalog(root).describe(run_id)
            except RunCatalogError as exc:
                conditions.append(
                    Condition(source="run", kind=KIND_PARTIAL, detail=str(exc))
                )
        else:
            conditions.append(
                Condition(
                    source="run",
                    kind=KIND_MISSING,
                    detail=f"the pointer names {run_id!r} but its run directory is missing.",
                )
            )
            run_dir = None

    definition = None
    if run_dir is not None:
        try:
            definition = definition_from_launch_copy(run_dir / "workflow.yml")
        except DefinitionError as exc:
            conditions.append(
                Condition(source="workflow.yml", kind=KIND_MISSING, detail=str(exc))
            )
            # The launch copy is authoritative, but its absence must not hide a
            # readable run: fall back to the installed definition for the graph.
            workflow_id = descriptor.workflow_id if descriptor else ""
            if workflow_id:
                try:
                    definition = _resolver_for(root).resolve(workflow_id)
                except Exception:  # noqa: BLE001 - the condition already reports it
                    definition = None

    reader = reader or (RunStateReader(root, run_id) if run_id is not None and run_dir is not None else None)
    state = reader.read() if reader is not None else None
    state_usable = _state_conditions(state, run_dir, conditions)

    graph = _declared_graph(root, definition)
    context = _ProjectionContext(runs_dir, graph)
    projection = None
    gate_attempt = 0
    if state_usable and state is not None:
        bound_graph = context.graph_for(state)
        timings = context.timings(state, run_id)
        from .projection import GraphProjector

        projection = GraphProjector().project(bound_graph, state, timings)
        gate_attempt = context.gate_attempt(state, run_id)

    gate = gate_payload(resolve_gate_target(state, graph) if state_usable else None, gate_attempt)

    branch, branch_error = _git_branch(root)
    if branch_error:
        conditions.append(Condition(source="git", kind=KIND_PARTIAL, detail=branch_error))

    review = FeatureReviewService(root).refresh()
    if review.status == "error":
        conditions.append(
            Condition(source="feature.json", kind=KIND_MISSING, detail=review.error)
        )
    feature_files = feature_files_payload(review, conditions)

    run_payload: dict[str, Any] | None = None
    if run_id is not None:
        run_payload = {
            "run_id": run_id,
            "workflow_id": descriptor.workflow_id if descriptor else None,
            "branch": branch,
            "status": state.status if state_usable and state is not None else None,
            "owner": _claim_owner(root, run_id),
        }

    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "pointer": {
            "state": pointer.state.value,
            "run_id": pointer.run_id,
            "detail": pointer.detail,
        },
        "run": run_payload,
        "step": step_payload(state, graph, projection) if state_usable else None,
        "gate": gate,
        "projection": projection_payload(projection),
        "feature_files": feature_files,
        "conditions": [condition.to_dict() for condition in conditions],
        "file": None,
    }
    if file_path is not None:
        envelope["file"] = _read_named_file(root, file_path, conditions)
    return FileView(envelope=envelope)


def _read_named_file(root: Path, file_path: str, conditions: list[Condition]) -> dict[str, Any]:
    """Read one named Feature File, bounded; refuse anything outside the index."""
    if not file_path or "\x00" in file_path:
        raise FileViewError("--file needs a project-relative Feature File path.")
    if Path(file_path).is_absolute():
        raise FileViewError("--file must be a project-relative path inside the Feature Files index.")
    feature_dir = resolve_feature_directory(root)
    if feature_dir is None:
        raise FileViewError("No feature directory is declared in .specify/feature.json.")
    service = FeatureReviewService(root)
    resolved = service.resolve_path(file_path)
    if resolved is None:
        raise FileViewError("--file escapes the project root.")
    base = (root.resolve() / feature_dir).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise FileViewError(
            f"--file must be inside the declared Feature Files index ({feature_dir})."
        ) from exc
    document = service.document(file_path)
    if document.error:
        conditions.append(Condition(source="file", kind=KIND_MISSING, detail=document.error))
    elif document.truncated:
        conditions.append(
            Condition(
                source="file",
                kind=KIND_PARTIAL,
                detail=(
                    f"the file is larger than the {document.limit_bytes} byte read bound; "
                    "only the first bytes are reported."
                ),
            )
        )
    return file_payload(document)


def envelope_json(view: FileView) -> str:
    """One JSON object, newline-terminated, as the command prints it."""
    return json.dumps(view.envelope, indent=2, sort_keys=False) + "\n"
