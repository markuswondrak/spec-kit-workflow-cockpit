"""Helpers that turn a recorded composition fixture into live test objects.

Kept separate from :mod:`tests.fixtures.composition` so the fixture module stays
a pure data reader, and separate from :mod:`tests.support` so flat-workflow
helpers stay unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from tests.fakes import FakeSupervisor
from tests.fixtures import composition as fx
from workflow_cockpit.services.execution_tree import ExecutionTree
from workflow_cockpit.services.execution_tree import parse as parse_execution
from workflow_cockpit.services.graph import ControlFlowGraph, graph_from_execution_tree
from workflow_cockpit.services.run_state import RunStateData
from workflow_cockpit.session.gate_decision import GateDecisionCoordinator

_MISSING = object()


def state_data(scenario: str, **overrides: Any) -> RunStateData:
    """A :class:`RunStateData` carrying the scenario's parsed execution tree.

    Pass ``execution=None`` explicitly to model a legacy (no-tree) run.
    """
    raw = fx.load_state(scenario)
    execution = overrides.pop("execution", _MISSING)
    if execution is _MISSING:
        execution = parse_execution(raw)
    return RunStateData(
        status=overrides.pop("status", raw["status"]),
        current_step_id=overrides.pop("current_step_id", raw.get("current_step_id")),
        step_results=overrides.pop("step_results", raw.get("step_results") or {}),
        complete=overrides.pop("complete", True),
        execution=execution,
        **overrides,
    )


def tree_graph(scenario: str) -> tuple[ExecutionTree, ControlFlowGraph]:
    tree = parse_execution(fx.load_state(scenario))
    return tree, graph_from_execution_tree(tree)


def coordinator(
    graph: ControlFlowGraph | None = None,
    *,
    version: str = "1.0.6",
    adopted: bool = False,
    read_only: bool = False,
    supervisor: FakeSupervisor | None = None,
    clock=None,
    watch: float = 10.0,
) -> tuple[GateDecisionCoordinator, FakeSupervisor]:
    supervisor = supervisor or FakeSupervisor()
    supervisor.run_id = "run-1"
    return (
        GateDecisionCoordinator(
            graph=graph,
            supervisor=supervisor,
            executable=Path("/usr/bin/specify"),
            version=version,
            clock=clock or (lambda: 100.0),
            watch_seconds=watch,
            adopted=adopted,
            read_only=read_only,
        ),
        supervisor,
    )


def write_project(
    root: Path,
    scenario: str = "reference",
    *,
    extra_children: dict[str, dict[str, Any]] | None = None,
    disabled: tuple[str, ...] = (),
    workflow_id: str | None = None,
) -> Path:
    """Materialize a scenario as an installed project the resolver can read.

    Child definitions come from the fixture's own frozen bindings, so the
    installed copies are exactly what the recorded run used.
    """
    workflows = root / ".specify" / "workflows"
    children = child_definitions(scenario)
    registry: dict[str, Any] = {}
    for child_id, definition in children.items():
        _write_workflow(workflows, child_id, definition)
        registry[child_id] = {
            "name": child_id,
            "version": "1.0.0",
            "enabled": child_id not in disabled,
        }
    for child_id, data in (extra_children or {}).items():
        _write_workflow(workflows, child_id, yaml.safe_dump(data, sort_keys=False))
        registry[child_id] = {"name": child_id, "version": "1.0.0", "enabled": child_id not in disabled}
    root_id = workflow_id or fx.load_state(scenario)["workflow_id"]
    root_text = (fx.scenario_dir(scenario) / "workflow.yml").read_text(encoding="utf-8")
    _write_workflow(workflows, root_id, root_text)
    registry[root_id] = {"name": root_id, "version": "1.0.0", "enabled": True}
    (workflows / "workflow-registry.json").write_text(
        json.dumps({"schema_version": "1.0", "workflows": registry}),
        encoding="utf-8",
    )
    return workflows / root_id / "workflow.yml"


def _write_workflow(workflows: Path, workflow_id: str, text: str) -> None:
    path = workflows / workflow_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "workflow.yml").write_text(text, encoding="utf-8")


def timings_for(scenario: str):
    """The fixture log aggregated the way a composed run keys it."""
    import tempfile

    from workflow_cockpit.services.log_aggregator import RunLogAggregator

    aggregator = RunLogAggregator(None)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "log.jsonl"
        path.write_bytes((fx.scenario_dir(scenario) / "log.jsonl").read_bytes())
        return aggregator.update(path)


def composed_snapshot(
    scenario: str,
    *,
    read_only: bool = False,
    status: str | None = None,
    gate_attempt: int = 1,
):
    """A presentation snapshot for one recorded composed run."""
    from workflow_cockpit.engine.supervisor import ProcessCondition
    from workflow_cockpit.services.projection import GraphProjector
    from workflow_cockpit.services.snapshot import RunSnapshot

    state = state_data(scenario)
    if status is not None:
        state = RunStateData(**{**state.__dict__, "status": status})
    _tree, graph = tree_graph(scenario)
    gate, _supervisor = coordinator(graph, read_only=read_only)
    snapshot_gate = gate.project(
        state=state,
        run_id="run-1",
        condition=ProcessCondition(
            live=False, exit_code=0, reaped=True, aborting=False, stdin_pty=False
        ),
        gate_attempt=gate_attempt,
    )
    projection = GraphProjector().project(graph, state, timings_for(scenario))
    raw = fx.load_state(scenario)
    return RunSnapshot(
        run_id="run-1",
        workflow_id=raw["workflow_id"],
        workflow_name=raw["workflow_id"],
        status=state.status,
        current_step_id=state.current_step_id,
        engine_status=state.status,
        gate=snapshot_gate,
        read_only=read_only,
        graph_projection=projection,
    )


def child_definitions(scenario: str) -> dict[str, str]:
    """``workflow_id -> frozen definition YAML`` for every bound call."""
    state = fx.load_state(scenario)
    found: dict[str, str] = {}

    def walk(sequence: dict[str, Any]) -> None:
        for node in sequence.get("nodes", []) or []:
            binding = node.get("binding")
            if isinstance(binding, dict) and isinstance(binding.get("workflow"), str):
                found.setdefault(binding["workflow"], binding["definition"])
            for child in node.get("children", []) or []:
                walk(child)

    walk(state["execution"]["sequence"])
    return found
