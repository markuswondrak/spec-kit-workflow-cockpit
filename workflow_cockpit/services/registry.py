"""Parse the installed workflow registry, failing closed on corruption."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RegistryError(Exception):
    """Raised when the workflow registry cannot be read or is malformed."""


@dataclass(frozen=True)
class WorkflowEntry:
    id: str
    name: str
    version: str
    description: str
    source: str
    enabled: bool
    raw: dict[str, Any]


class WorkflowRegistry:
    """Read ``.specify/workflows/workflow-registry.json``."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.registry_path = self.project_root / ".specify" / "workflows" / "workflow-registry.json"

    def load(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            raise RegistryError(
                f"Workflow registry not found: {self.registry_path}. "
                "Install a workflow with 'specify workflow add'."
            )
        try:
            with open(self.registry_path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RegistryError(f"Failed to read workflow registry: {exc}") from exc
        if not isinstance(data, dict):
            raise RegistryError("Workflow registry must be a JSON object.")
        workflows = data.get("workflows")
        if not isinstance(workflows, dict):
            raise RegistryError("Workflow registry is missing a 'workflows' object.")
        return data

    def entries(self) -> tuple[WorkflowEntry, ...]:
        """Return every installed (enabled and disabled) entry."""
        workflows = self.load()["workflows"]
        result: list[WorkflowEntry] = []
        for workflow_id, raw in workflows.items():
            if not isinstance(workflow_id, str) or not isinstance(raw, dict):
                raise RegistryError(f"Corrupt registry entry for {workflow_id!r}.")
            result.append(
                WorkflowEntry(
                    id=workflow_id,
                    name=str(raw.get("name") or workflow_id),
                    version=str(raw.get("version") or ""),
                    description=str(raw.get("description") or ""),
                    source=str(raw.get("source") or ""),
                    enabled=raw.get("enabled", True) is not False,
                    raw=raw,
                )
            )
        return tuple(result)

    def list_runnable(self) -> tuple[WorkflowEntry, ...]:
        """Return enabled workflows only, sorted by name then id."""
        return tuple(
            sorted(
                (entry for entry in self.entries() if entry.enabled),
                key=lambda entry: (entry.name.casefold(), entry.id),
            )
        )

    def get(self, workflow_id: str) -> WorkflowEntry | None:
        for entry in self.entries():
            if entry.id == workflow_id:
                return entry
        return None
