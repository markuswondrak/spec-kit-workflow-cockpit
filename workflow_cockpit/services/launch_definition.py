"""Build a ``WorkflowDefinition`` from the persisted launch-copy ``workflow.yml``.

The launch copy is authoritative for an adopted run's control flow graph and
declared gates, so it is parsed directly rather than re-resolved through the
installed workflow and its overlays.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .definition import (
    DefinitionError,
    WorkflowDefinition,
    _parse_inputs,
    _step_from_dict,
)

#: Bounded read for the persisted launch-copy definition (FR-024).
MAX_LAUNCH_WORKFLOW_BYTES = 512 * 1024


def definition_from_launch_copy(
    path: Path,
    *,
    max_bytes: int = MAX_LAUNCH_WORKFLOW_BYTES,
) -> WorkflowDefinition:
    """Parse the persisted launch copy into a ``WorkflowDefinition``.

    Raises :class:`DefinitionError` when the copy is missing, oversized,
    undecodable, or not a mapping.
    """
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise DefinitionError(f"Launch-copy workflow definition is unavailable: {path}") from exc
    if size > max_bytes:
        raise DefinitionError(
            f"Launch-copy workflow definition exceeds {max_bytes} bytes: {path}"
        )
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise DefinitionError(f"Invalid launch-copy workflow definition {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise DefinitionError(f"Launch-copy workflow definition must be a mapping: {path}")

    workflow = data.get("workflow")
    workflow = workflow if isinstance(workflow, dict) else {}
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        raise DefinitionError(f"Launch-copy workflow definition has no steps list: {path}")
    effective_steps = tuple(step for step in raw_steps if isinstance(step, dict))
    step_specs = tuple(
        _step_from_dict(step, index) for index, step in enumerate(effective_steps)
    )
    return WorkflowDefinition(
        id=str(workflow.get("id") or ""),
        name=str(workflow.get("name") or workflow.get("id") or ""),
        version=str(workflow.get("version") or ""),
        description=str(workflow.get("description") or ""),
        inputs=_parse_inputs(data.get("inputs")),
        steps=step_specs,
        source=path,
        raw=data,
        effective_steps=effective_steps,
    )
