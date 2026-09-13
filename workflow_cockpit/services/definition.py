"""Resolve effective workflow definitions (base plus enabled overlays)."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

NESTED_LIST_KEYS = ("then", "else", "steps", "default")
VALID_OPERATIONS = ("insert_after", "insert_before", "replace", "remove")


class DefinitionError(Exception):
    """Raised when a workflow definition or overlay cannot be resolved."""


@dataclass(frozen=True)
class InputSpec:
    name: str
    type: str = "string"
    required: bool = False
    has_default: bool = False
    default: Any = None
    prompt: str = ""
    description: str = ""
    enum: tuple[Any, ...] | None = None

    @property
    def label(self) -> str:
        return self.description or self.prompt or self.name


@dataclass(frozen=True)
class StepSpec:
    id: str
    label: str
    type: str = "command"
    gate: bool = False
    message: str = ""
    options: tuple[str, ...] = ()
    verdict_input: str | None = None
    on_reject: str | None = None


@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    version: str
    description: str
    inputs: tuple[InputSpec, ...]
    steps: tuple[StepSpec, ...]
    source: Path | None = None
    raw: dict[str, Any] | None = None
    effective_steps: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class OverlayEdit:
    operation: str
    anchor: str
    step: dict[str, Any] | None = None


@dataclass(frozen=True)
class OverlayLayer:
    id: str
    priority: int
    source: str
    edits: tuple[OverlayEdit, ...]


def _parse_inputs(raw: Any) -> tuple[InputSpec, ...]:
    if not isinstance(raw, dict):
        return ()
    specs: list[InputSpec] = []
    for name, spec in raw.items():
        if not isinstance(name, str) or not isinstance(spec, dict):
            continue
        enum = spec.get("enum")
        specs.append(
            InputSpec(
                name=name,
                type=str(spec.get("type", "string")),
                required=bool(spec.get("required", False)),
                has_default="default" in spec,
                default=spec.get("default"),
                prompt=str(spec.get("prompt") or ""),
                description=str(spec.get("description") or ""),
                enum=tuple(enum) if isinstance(enum, list) else None,
            )
        )
    return tuple(specs)


def _step_from_dict(raw: dict[str, Any], index: int) -> StepSpec:
    step_id = raw.get("id")
    if not isinstance(step_id, str) or not step_id:
        step_id = f"step-{index}"
    step_type = str(raw.get("type", "command"))
    options = raw.get("options")
    options_tuple: tuple[str, ...]
    if isinstance(options, list):
        options_tuple = tuple(str(option) for option in options)
    else:
        options_tuple = ()
    return StepSpec(
        id=step_id,
        label=str(raw.get("name") or step_id),
        type=step_type,
        gate=step_type == "gate",
        message=str(raw.get("message") or ""),
        options=options_tuple,
        verdict_input=(str(raw["verdict_input"]) if raw.get("verdict_input") else None),
        on_reject=(str(raw["on_reject"]) if raw.get("on_reject") else None),
    )


def _top_level_steps(data: dict[str, Any]) -> list[dict[str, Any]]:
    steps = data.get("steps", [])
    return steps if isinstance(steps, list) else []


def _iter_step_dicts(steps: list[Any]):
    for step in steps:
        if not isinstance(step, dict):
            continue
        yield step
        for key in NESTED_LIST_KEYS:
            nested = step.get(key)
            if isinstance(nested, list):
                yield from _iter_step_dicts(nested)
        cases = step.get("cases")
        if isinstance(cases, dict):
            for case_steps in cases.values():
                if isinstance(case_steps, list):
                    yield from _iter_step_dicts(case_steps)


def _all_step_ids(steps: list[Any]) -> set[str]:
    return {step["id"] for step in _iter_step_dicts(steps) if isinstance(step.get("id"), str)}


def _descendant_ids(step: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in NESTED_LIST_KEYS:
        nested = step.get(key)
        if isinstance(nested, list):
            ids.update(_all_step_ids(nested))
    cases = step.get("cases")
    if isinstance(cases, dict):
        for case_steps in cases.values():
            if isinstance(case_steps, list):
                ids.update(_all_step_ids(case_steps))
    return ids


def _find_step(steps: list[Any], step_id: str) -> tuple[list[Any], int] | None:
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        if step.get("id") == step_id:
            return steps, index
        for key in NESTED_LIST_KEYS:
            nested = step.get(key)
            if isinstance(nested, list):
                found = _find_step(nested, step_id)
                if found is not None:
                    return found
        cases = step.get("cases")
        if isinstance(cases, dict):
            for case_steps in cases.values():
                if isinstance(case_steps, list):
                    found = _find_step(case_steps, step_id)
                    if found is not None:
                        return found
    return None


def _traverse_and_apply(
    steps: list[Any],
    edits_by_anchor: dict[str, list[tuple[OverlayLayer, OverlayEdit]]],
) -> list[Any]:
    result: list[Any] = []
    for step in steps:
        if not isinstance(step, dict):
            result.append(step)
            continue
        step_id = step.get("id")
        edits = edits_by_anchor.get(step_id, []) if isinstance(step_id, str) else []
        winning = edits[-1][1] if edits else None
        if winning is not None and winning.operation == "remove":
            continue
        for _layer, edit in edits:
            if edit.operation == "insert_before":
                result.append(copy.deepcopy(edit.step))
        if winning is not None and winning.operation == "replace":
            result.append(copy.deepcopy(winning.step))
        else:
            for key in NESTED_LIST_KEYS:
                nested = step.get(key)
                if isinstance(nested, list):
                    step[key] = _traverse_and_apply(nested, edits_by_anchor)
            cases = step.get("cases")
            if isinstance(cases, dict):
                for case_key, case_steps in cases.items():
                    if isinstance(case_steps, list):
                        cases[case_key] = _traverse_and_apply(case_steps, edits_by_anchor)
            result.append(step)
        groups: list[list[tuple[OverlayLayer, OverlayEdit]]] = []
        for layer, edit in edits:
            if edit.operation != "insert_after":
                continue
            if groups and groups[-1][0][0] is layer:
                groups[-1].append((layer, edit))
            else:
                groups.append([(layer, edit)])
        for group in reversed(groups):
            for _layer, edit in group:
                result.append(copy.deepcopy(edit.step))
    return result


def _parse_overlay(path: Path, workflow_id: str) -> tuple[OverlayLayer | None, list[str]]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return None, [f"Invalid overlay {path}: {exc}"]
    if not isinstance(data, dict):
        return None, [f"Invalid overlay {path}: expected a mapping."]
    overlay_id = data.get("id")
    extends = data.get("extends")
    if not isinstance(overlay_id, str) or not overlay_id:
        return None, [f"Invalid overlay {path}: missing 'id'."]
    if not isinstance(extends, str) or not extends:
        return None, [f"Invalid overlay {path}: missing 'extends'."]
    if extends != workflow_id:
        return None, [f"Overlay {path} extends {extends!r}, but is stored under workflow {workflow_id!r}."]
    if data.get("enabled", True) is False:
        return None, []
    priority = data.get("priority", 10)
    try:
        priority = int(priority)
    except (TypeError, ValueError):
        return None, [f"Invalid overlay {path}: 'priority' must be an integer."]
    edits_raw = data.get("edits")
    if not isinstance(edits_raw, list) or not edits_raw:
        return None, [f"Invalid overlay {path}: 'edits' must be a non-empty list."]
    edits: list[OverlayEdit] = []
    for idx, edit_raw in enumerate(edits_raw):
        if not isinstance(edit_raw, dict):
            return None, [f"Invalid overlay {path}: edit {idx} must be a mapping."]
        shorthand = [key for key in edit_raw if key in VALID_OPERATIONS]
        if len(shorthand) == 1 and "operation" not in edit_raw:
            operation = shorthand[0]
            anchor = edit_raw[operation]
        else:
            operation = edit_raw.get("operation")
            anchor = edit_raw.get("anchor")
        if operation not in VALID_OPERATIONS:
            return None, [f"Invalid overlay {path}: edit {idx} has invalid operation."]
        if not isinstance(anchor, str) or not anchor:
            return None, [f"Invalid overlay {path}: edit {idx} has invalid anchor."]
        step = edit_raw.get("step")
        if operation != "remove" and not isinstance(step, dict):
            return None, [f"Invalid overlay {path}: edit {idx} requires a 'step' mapping."]
        edits.append(OverlayEdit(operation=operation, anchor=anchor, step=step))
    return (
        OverlayLayer(id=overlay_id, priority=priority, source=f"project:{overlay_id}", edits=tuple(edits)),
        [],
    )


def _apply_overlays(base_data: dict[str, Any], layers: list[OverlayLayer]) -> list[Any]:
    base_steps = _top_level_steps(base_data)
    base_ids = _all_step_ids(base_steps)
    errors: list[str] = []
    for layer in layers:
        for idx, edit in enumerate(layer.edits):
            if edit.anchor not in base_ids:
                errors.append(
                    f"Overlay '{layer.id}' edit {idx}: anchor '{edit.anchor}' does not match any base step id."
                )
    if errors:
        raise DefinitionError("; ".join(errors))

    merge_order = sorted(layers, key=lambda layer: (-layer.priority, layer.id))
    edits_by_anchor: dict[str, list[tuple[OverlayLayer, OverlayEdit]]] = {}
    for layer in merge_order:
        for edit in layer.edits:
            edits_by_anchor.setdefault(edit.anchor, []).append((layer, edit))

    for anchor, anchor_edits in edits_by_anchor.items():
        winning = anchor_edits[-1][1]
        if winning.operation in ("replace", "remove"):
            location = _find_step(base_steps, anchor)
            if location is not None:
                descendants = _descendant_ids(location[0][location[1]])
                overlap = descendants & set(edits_by_anchor)
                if overlap:
                    raise DefinitionError(
                        f"Overlay anchor conflict: '{anchor}' replaces or removes a "
                        f"subtree also targeted by {', '.join(sorted(overlap))}."
                    )

    return _traverse_and_apply(copy.deepcopy(base_steps), edits_by_anchor)


class WorkflowDefinitionResolver:
    """Resolve base workflow YAML while applying enabled project overlays."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.workflows_dir = self.project_root / ".specify" / "workflows"

    def base_path(self, workflow_id: str) -> Path:
        return self.workflows_dir / workflow_id / "workflow.yml"

    def _overlay_dir(self, workflow_id: str) -> Path:
        return self.workflows_dir / "overlays" / workflow_id

    def collect_overlays(self, workflow_id: str) -> list[OverlayLayer]:
        overlay_dir = self._overlay_dir(workflow_id)
        if not overlay_dir.is_dir():
            return []
        layers: list[OverlayLayer] = []
        for path in sorted(overlay_dir.iterdir()):
            if not path.is_file() or path.suffix not in (".yml", ".yaml"):
                continue
            layer, errors = _parse_overlay(path, workflow_id)
            if errors:
                raise DefinitionError(" ".join(errors))
            if layer is None:
                continue
            layers.append(layer)
        return layers

    def resolve(self, workflow_id: str) -> WorkflowDefinition:
        path = self.base_path(workflow_id)
        if not path.is_file():
            raise DefinitionError(f"Workflow definition not found: {path}")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise DefinitionError(f"Invalid workflow definition {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise DefinitionError(f"Workflow definition must be a mapping: {path}")

        overlays = self.collect_overlays(workflow_id)
        composed_steps = _apply_overlays(data, overlays)

        workflow = data.get("workflow")
        workflow = workflow if isinstance(workflow, dict) else {}
        step_specs = tuple(
            _step_from_dict(step, index) for index, step in enumerate(composed_steps) if isinstance(step, dict)
        )
        return WorkflowDefinition(
            id=str(workflow.get("id") or workflow_id),
            name=str(workflow.get("name") or workflow_id),
            version=str(workflow.get("version") or ""),
            description=str(workflow.get("description") or ""),
            inputs=_parse_inputs(data.get("inputs")),
            steps=step_specs,
            source=path,
            raw=data,
            effective_steps=tuple(composed_steps),
        )


def coerce_input_value(name: str, value: Any, spec: InputSpec) -> Any:
    """Coerce one value to its declared type, mirroring the engine."""
    if spec.type == "number":
        if isinstance(value, bool):
            raise ValueError(f"Input {name!r} expected a number.")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"Input {name!r} expected a number, got {value!r}.") from None
        coerced: Any = int(number) if number == int(number) else number
    elif spec.type == "boolean":
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "1", "yes", "on"):
                coerced = True
            elif lowered in ("false", "0", "no", "off"):
                coerced = False
            else:
                raise ValueError(f"Input {name!r} expected a boolean, got {value!r}.")
        elif isinstance(value, bool):
            coerced = value
        else:
            raise ValueError(f"Input {name!r} expected a boolean, got {value!r}.")
    else:
        if not isinstance(value, str):
            raise ValueError(f"Input {name!r} expected a string, got {value!r}.")
        coerced = value

    if spec.enum is not None and coerced not in spec.enum:
        raise ValueError(f"Input {name!r} value {coerced!r} not in allowed values: {list(spec.enum)}.")
    return coerced


def validate_inputs(definition: WorkflowDefinition, provided: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (resolved_values, field_errors) for a schema-driven form."""
    resolved: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for spec in definition.inputs:
        raw = provided.get(spec.name)
        blank = raw is None or (isinstance(raw, str) and raw.strip() == "")
        if not blank:
            candidate = raw
        elif spec.has_default:
            candidate = spec.default
        elif spec.required:
            errors[spec.name] = "Required."
            continue
        else:
            continue
        try:
            resolved[spec.name] = coerce_input_value(spec.name, candidate, spec)
        except ValueError as exc:
            errors[spec.name] = str(exc)
    return resolved, errors


def inputs_to_argv(values: dict[str, Any]) -> list[str]:
    """Render resolved inputs as repeated ``-i key=value`` argv pairs."""
    argv: list[str] = []
    for name, value in values.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        argv.extend(["-i", f"{name}={rendered}"])
    return argv


def normalized_signature(data: dict[str, Any]) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Return the comparable launch structure of a raw definition mapping."""
    if not isinstance(data, dict):
        return ((), ())
    steps = tuple(
        step["id"] for step in _top_level_steps(data) if isinstance(step, dict) and isinstance(step.get("id"), str)
    )
    raw_inputs = data.get("inputs")
    inputs: tuple[tuple[str, str], ...] = ()
    if isinstance(raw_inputs, dict):
        inputs = tuple(
            sorted(
                (name, str(spec.get("type", "string")) if isinstance(spec, dict) else "string")
                for name, spec in raw_inputs.items()
                if isinstance(name, str)
            )
        )
    return (steps, inputs)


def definition_signature(definition: WorkflowDefinition) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Return the comparable launch structure of a resolved definition."""
    return (
        tuple(step.id for step in definition.steps),
        tuple(sorted((spec.name, spec.type) for spec in definition.inputs)),
    )
