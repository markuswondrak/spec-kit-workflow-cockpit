"""Declared workflow inputs: schema parsing, coercion, and validation.

Split out of :mod:`workflow_cockpit.services.definition` so that file stays a
focused resolver and stays under the project's file-size bound. The rules are
the engine's: an input's declared type coerces the provided string, an enum
restricts it, and a blank value falls back to the declared default or fails
when the input is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .definition import WorkflowDefinition


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


def parse_inputs(raw: Any) -> tuple[InputSpec, ...]:
    """Read the ``inputs:`` mapping of a raw workflow definition."""
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


def validate_inputs(
    definition: WorkflowDefinition, provided: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (resolved_values, field_errors) for a schema-driven form."""
    resolved: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for spec in definition.presented_inputs:
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
