"""Bounded, read-only discovery of existing engine runs.

Every value comes from persisted run files: ``state.json`` for status and step,
the launch-copy ``workflow.yml`` for display metadata, and the Cockpit-owned
``current_run`` index for the default suggestion. The catalog never infers state
from directory names or ``log.jsonl`` and imports no engine internals.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .launch_definition import MAX_LAUNCH_WORKFLOW_BYTES
from .run_claim import ClaimState

#: Maximum number of run directories inspected per discovery.
MAX_RUNS = 200

#: Bounded read for ``state.json`` (FR-003, FR-024).
MAX_STATE_BYTES = 256 * 1024

#: Bounded read for the launch-copy ``workflow.yml`` display fields.
MAX_WORKFLOW_BYTES = MAX_LAUNCH_WORKFLOW_BYTES

#: Bounded read for the Cockpit-owned ``current_run`` pointer.
MAX_INDEX_BYTES = 64 * 1024

#: Persisted statuses the engine is known to write.
KNOWN_STATUSES = frozenset(
    {"initializing", "running", "paused", "completed", "failed", "aborted"}
)

_DEFAULT_RUN_ID = re.compile(r"^- Run ID: `([^`]+)`", re.MULTILINE)


class RunCatalogError(Exception):
    """Raised when one run directory cannot be described."""


@dataclass(frozen=True)
class RunDescriptor:
    """Bounded, read-only summary of one discovered run."""

    run_id: str
    workflow_id: str = ""
    workflow_name: str = ""
    status: str = "unusable"
    current_step_id: str | None = None
    updated_at: str | None = None
    usable: bool = True
    reason: str = ""
    launch_copy: bool = True
    claim_state: ClaimState = ClaimState.NONE
    is_default: bool = False

    @property
    def adoptable(self) -> bool:
        """A paused run with a usable launch copy and no live foreign owner."""
        return (
            self.usable
            and self.launch_copy
            and self.status == "paused"
            and self.claim_state in (ClaimState.NONE, ClaimState.OWNED, ClaimState.STALE)
        )

    @property
    def viewable(self) -> bool:
        """A usable run with a launch copy can be inspected read-only."""
        return self.usable and self.launch_copy


def _signature(stat: Any) -> tuple[int, int, int]:
    return (stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _read_bounded(path: Path, max_bytes: int) -> tuple[bytes | None, str]:
    """Read a file with a before/after signature check and a byte cap."""
    try:
        before = path.stat()
    except OSError:
        return None, f"{path.name} is missing or unreadable"
    if before.st_size > max_bytes:
        return None, f"{path.name} exceeds {max_bytes} bytes"
    try:
        raw = path.read_bytes()
    except OSError:
        return None, f"{path.name} could not be read"
    try:
        after = path.stat()
    except OSError:
        return None, f"{path.name} changed while reading"
    if _signature(before) != _signature(after) or len(raw) > max_bytes:
        return None, f"{path.name} changed while reading"
    return raw, ""


class RunCatalog:
    """List and describe ``.specify/workflows/runs/`` without mutation."""

    def __init__(
        self,
        project_root: Path,
        *,
        max_runs: int = MAX_RUNS,
        max_state_bytes: int = MAX_STATE_BYTES,
        max_workflow_bytes: int = MAX_WORKFLOW_BYTES,
        owner_id: str | None = None,
        claim_store: Any | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.runs_dir = self.project_root / ".specify" / "workflows" / "runs"
        self.max_runs = max_runs
        self.max_state_bytes = max_state_bytes
        self.max_workflow_bytes = max_workflow_bytes
        self.owner_id = owner_id
        self.claim_store = claim_store

    def list_runs(self) -> tuple[RunDescriptor, ...]:
        """Return usable and unusable descriptors, newest-first, bounded."""
        if not self.runs_dir.is_dir():
            return ()
        candidates: list[tuple[int, str]] = []
        try:
            entries = list(self.runs_dir.iterdir())
        except OSError:
            return ()
        for entry in entries:
            try:
                if not entry.is_dir():
                    # The ``current_run`` pointer and temp files are skipped.
                    continue
                mtime = entry.stat().st_mtime_ns
            except OSError:
                continue
            candidates.append((mtime, entry.name))
        candidates.sort(key=lambda item: item[0], reverse=True)
        descriptors: list[RunDescriptor] = []
        for _mtime, run_id in candidates[: self.max_runs]:
            try:
                descriptors.append(self.describe(run_id))
            except RunCatalogError as exc:
                descriptors.append(
                    RunDescriptor(
                        run_id=run_id,
                        status="unusable",
                        usable=False,
                        reason=str(exc),
                    )
                )
        return tuple(descriptors)

    def describe(self, run_id: str) -> RunDescriptor:
        """Describe one run directory from its persisted files."""
        run_dir = self.runs_dir / run_id
        if not run_dir.is_dir():
            raise RunCatalogError(f"Run directory is missing: {run_id}")

        state, state_error = self._read_state(run_dir)
        current_run_id = self._default_run_id()
        if state_error:
            return RunDescriptor(
                run_id=run_id,
                status="unusable",
                usable=False,
                reason=state_error,
                is_default=False,
                claim_state=self._claim_state(run_id),
            )

        launch_id, launch_name, launch_error = self._read_launch_copy(run_dir)
        workflow_id = launch_id or _state_string(state, "workflow_id")
        workflow_name = launch_name or workflow_id
        # A missing launch copy stays readable; an oversized or unreadable one
        # is reported unusable because the definition is authoritative.
        if launch_error and "missing" not in launch_error:
            return RunDescriptor(
                run_id=run_id,
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                status="unusable",
                usable=False,
                reason=launch_error,
                launch_copy=False,
                is_default=False,
                claim_state=self._claim_state(run_id),
            )
        return RunDescriptor(
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            # A readable but unknown status is shown raw, never adopted.
            status=str(state.get("status")),
            current_step_id=_state_string(state, "current_step_id") or None,
            updated_at=_state_string(state, "updated_at") or None,
            usable=True,
            reason="",
            launch_copy=launch_error == "",
            claim_state=self._claim_state(run_id),
            is_default=run_id == current_run_id,
        )

    def _read_state(self, run_dir: Path) -> tuple[dict[str, Any], str]:
        raw, error = _read_bounded(run_dir / "state.json", self.max_state_bytes)
        if error:
            return {}, error
        assert raw is not None
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}, "state.json is not valid JSON"
        if not isinstance(data, dict):
            return {}, "state.json must be a JSON object"
        status = data.get("status")
        if not isinstance(status, str) or not status:
            return {}, "state.json has no status"
        return data, ""

    def _read_launch_copy(self, run_dir: Path) -> tuple[str, str, str]:
        path = run_dir / "workflow.yml"
        if not path.is_file():
            return "", "", "workflow.yml is missing"
        raw, error = _read_bounded(path, self.max_workflow_bytes)
        if error:
            return "", "", error
        assert raw is not None
        try:
            data = yaml.safe_load(raw.decode("utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError):
            return "", "", "workflow.yml is not valid YAML"
        if not isinstance(data, dict):
            return "", "", "workflow.yml must be a mapping"
        workflow = data.get("workflow")
        workflow = workflow if isinstance(workflow, dict) else {}
        workflow_id = workflow.get("id")
        workflow_name = workflow.get("name")
        return (
            workflow_id if isinstance(workflow_id, str) else "",
            workflow_name if isinstance(workflow_name, str) else "",
            "",
        )

    def _default_run_id(self) -> str | None:
        path = self.runs_dir / "current_run"
        raw, error = _read_bounded(path, MAX_INDEX_BYTES)
        if error or raw is None:
            return None
        text = raw.decode("utf-8", errors="replace")
        match = _DEFAULT_RUN_ID.search(text)
        return match.group(1) if match else None

    def _claim_state(self, run_id: str) -> ClaimState:
        if self.claim_store is None:
            return ClaimState.NONE
        try:
            return self.claim_store.claim_state(run_id, self.owner_id)
        except Exception:  # noqa: BLE001 - discovery must not crash on a claim
            return ClaimState.NONE


def _state_string(state: dict[str, Any], key: str) -> str:
    value = state.get(key)
    return value if isinstance(value, str) else ""
