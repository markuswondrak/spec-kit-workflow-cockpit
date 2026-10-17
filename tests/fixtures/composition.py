"""Recorded composition fixtures plus edge-case mutations.

The ``composition/`` directory holds run files recorded from a real pinned
engine (see ``scripts/record-composition-fixtures.sh``); hand-writing them would
test Cockpit against an invented shape. Edge cases that the engine cannot be
asked to produce (unsupported versions, corrupt trees, oversized files) are
derived here by small mutations of a recorded run.

Every loader returns fresh copies, so a test may mutate freely.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import yaml

FIXTURE_ROOT = Path(__file__).resolve().parent / "composition"

#: Scenarios recorded from the engine, each with state/log/status/workflow files.
SCENARIOS = (
    "reference",
    "collision",
    "depth2",
    "loop-paused",
    "loop-twice",
    "fanout",
    "fanout-verdict",
    "failed-child",
    "continue-on-error",
    "dynamic-target",
)


def scenario_dir(scenario: str) -> Path:
    path = FIXTURE_ROOT / scenario
    if not path.is_dir():
        raise FileNotFoundError(f"unknown composition fixture {scenario!r} at {path}")
    return path


def load_state(scenario: str) -> dict[str, Any]:
    """The recorded ``state.json`` of one scenario, as a fresh dict."""
    return json.loads((scenario_dir(scenario) / "state.json").read_text(encoding="utf-8"))


def load_status(scenario: str) -> dict[str, Any]:
    """The recorded ``specify workflow status --json`` oracle of one scenario."""
    return json.loads((scenario_dir(scenario) / "status.json").read_text(encoding="utf-8"))


def load_log(scenario: str) -> tuple[dict[str, Any], ...]:
    """The recorded ``log.jsonl`` events of one scenario."""
    path = scenario_dir(scenario) / "log.jsonl"
    events: list[dict[str, Any]] = []
    if not path.is_file():
        return ()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return tuple(events)


def load_workflow_yaml(scenario: str) -> dict[str, Any]:
    """The launch-copy workflow definition of one scenario."""
    return yaml.safe_load((scenario_dir(scenario) / "workflow.yml").read_text(encoding="utf-8"))


def write_run(
    root: Path,
    scenario: str = "reference",
    *,
    run_id: str = "cockpit-composed",
    state: dict[str, Any] | None = None,
    log: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
    inputs: dict[str, Any] | None = None,
    workflow_yaml: str | None = None,
) -> Path:
    """Materialize one recorded run under ``root`` and return its run directory.

    ``state`` overrides the recorded state; ``log`` / ``inputs`` / ``workflow_yaml``
    default to the recorded files.
    """
    source = scenario_dir(scenario)
    run_dir = root / ".specify" / "workflows" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "state.json").write_text(
        json.dumps(state if state is not None else load_state(scenario)),
        encoding="utf-8",
    )
    if log is not None:
        (run_dir / "log.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in log),
            encoding="utf-8",
        )
    elif (source / "log.jsonl").is_file():
        (run_dir / "log.jsonl").write_text(
            (source / "log.jsonl").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    if inputs is not None:
        (run_dir / "inputs.json").write_text(json.dumps({"inputs": inputs}), encoding="utf-8")
    elif (source / "inputs.json").is_file():
        (run_dir / "inputs.json").write_text(
            (source / "inputs.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    if workflow_yaml is not None:
        (run_dir / "workflow.yml").write_text(workflow_yaml, encoding="utf-8")
    elif (source / "workflow.yml").is_file():
        (run_dir / "workflow.yml").write_text(
            (source / "workflow.yml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    return run_dir


# ---------------------------------------------------------------------------
# Mutations: edge cases the engine never writes
# ---------------------------------------------------------------------------


def without_execution(state: dict[str, Any]) -> dict[str, Any]:
    """A legacy run: no ``execution`` (and no ``inputs``) at all."""
    mutated = copy.deepcopy(state)
    mutated.pop("execution", None)
    mutated.pop("inputs", None)
    return mutated


def with_version(state: dict[str, Any], version: Any) -> dict[str, Any]:
    """A run whose ``execution.version`` is anything Cockpit must not interpret."""
    mutated = copy.deepcopy(state)
    mutated["execution"]["version"] = version
    return mutated


def corrupt_tree(state: dict[str, Any]) -> dict[str, Any]:
    """A structurally invalid execution tree (nodes is not a list)."""
    mutated = copy.deepcopy(state)
    mutated["execution"]["sequence"]["nodes"] = "not-a-list"
    return mutated


def with_sequence_length_mismatch(state: dict[str, Any]) -> dict[str, Any]:
    """A tree whose nodes outnumber the decoded steps."""
    mutated = copy.deepcopy(state)
    nodes = mutated["execution"]["sequence"]["nodes"]
    nodes.append(copy.deepcopy(nodes[-1]))
    return mutated


def without_unfinished_node(state: dict[str, Any]) -> dict[str, Any]:
    """A paused-looking run whose tree has no node left to run."""
    mutated = copy.deepcopy(state)

    def finish(node: dict[str, Any]) -> None:
        node["phase"] = "done"
        for child in node.get("children", []) or []:
            for child_node in child.get("nodes", []) or []:
                finish(child_node)

    for node in mutated["execution"]["sequence"]["nodes"]:
        finish(node)
    return mutated


def with_current_step_id(state: dict[str, Any], value: str | None) -> dict[str, Any]:
    """A run whose ``current_step_id`` disagrees with the tree."""
    mutated = copy.deepcopy(state)
    mutated["current_step_id"] = value
    return mutated


def with_root_extra_step(state: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    """Append a root step config and its matching ready node."""
    mutated = copy.deepcopy(state)
    sequence = mutated["execution"]["sequence"]
    steps = yaml.safe_load(sequence["source"])
    steps.append(step)
    sequence["source"] = yaml.safe_dump(steps, sort_keys=False)
    sequence["nodes"].append({"phase": "ready"})
    return mutated


def inflated_state(state: dict[str, Any], min_bytes: int) -> dict[str, Any]:
    """A still-valid state whose serialized ``state.json`` is at least ``min_bytes``.

    The padding rides in ``step_results`` because that is what makes a real
    composed run large: the engine keeps each step's captured output after
    completion, while the embedded definitions stay small. Step/node alignment
    is untouched, so the tree remains structurally valid.
    """
    mutated = copy.deepcopy(state)
    results = mutated.setdefault("step_results", {})
    padding = "x" * max(1024, min_bytes)
    results["padding"] = {"type": "shell", "status": "completed", "output": {"stdout": padding}}
    while len(json.dumps(mutated)) < min_bytes:
        padding += "x" * max(1024, min_bytes - len(json.dumps(mutated)))
        results["padding"]["output"]["stdout"] = padding
    return mutated


def serialized_size(state: dict[str, Any]) -> int:
    return len(json.dumps(state))


def yaml_inflated_state(state: dict[str, Any], min_bytes: int) -> dict[str, Any]:
    """A still-valid tree whose *embedded YAML* approaches ``min_bytes``.

    This is the pathological worst case for parse cost: real composed runs grow
    through retained step output (JSON), not through multi-megabyte frozen
    definitions. It exists so the cost is measured and documented rather than
    assumed.
    """
    mutated = copy.deepcopy(state)
    sequence = mutated["execution"]["sequence"]
    steps = yaml.safe_load(sequence["source"])
    if not steps:
        steps = [{"id": "pad", "type": "shell", "run": "true"}]
        sequence["nodes"] = [{"phase": "done"}]
    padding = "x" * max(1024, min_bytes)
    steps[0]["description"] = padding
    sequence["source"] = yaml.safe_dump(steps, sort_keys=False)
    while len(json.dumps(mutated)) < min_bytes:
        padding += "x" * max(1024, min_bytes - len(json.dumps(mutated)))
        steps[0]["description"] = padding
        sequence["source"] = yaml.safe_dump(steps, sort_keys=False)
    return mutated


def normalized_scope_path(path: Any) -> tuple[str, ...]:
    """Compare engine scope paths (string indices) with Cockpit's (int indices)."""
    if path is None:
        return ()
    return tuple(str(part) for part in path)
