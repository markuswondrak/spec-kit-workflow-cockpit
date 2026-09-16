"""Tolerant read of the project's ``.specify/integration.json`` descriptor.

This is the only place that interprets the integration descriptor. It never
raises: every missing, unreadable, malformed, or absent-field input is reported
as a reason so the caller can fall back to the neutral default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IntegrationDescriptor:
    """The declared ``default_integration`` or the reason it is unavailable."""

    value: str | None
    reason: str = ""

    @property
    def declared(self) -> bool:
        return bool(self.value)


def read_default_integration(specify_dir: Path | str) -> IntegrationDescriptor:
    path = Path(specify_dir) / "integration.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return IntegrationDescriptor(None, "no .specify/integration.json")
    except OSError as exc:
        return IntegrationDescriptor(None, f"cannot read .specify/integration.json: {exc}")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        return IntegrationDescriptor(None, f"malformed .specify/integration.json: {exc}")
    if not isinstance(data, dict):
        return IntegrationDescriptor(None, "malformed .specify/integration.json: not an object")
    value = data.get("default_integration")
    if not isinstance(value, str) or not value.strip():
        return IntegrationDescriptor(None, "no default_integration declared")
    return IntegrationDescriptor(value.strip())
