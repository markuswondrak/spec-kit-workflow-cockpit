"""Explicit, owner-safe deletion of one existing run directory.

``RunCatalog`` is a read-only discovery service; removing a run is a distinct
mutation, so it lives here. Deletion is deliberately conservative: it refuses a
run that an engine may still be writing, a run another live owner holds, and
the run this session is currently using. It never signals a process.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .run_catalog import RunCatalog, RunCatalogError
from .run_claim import ClaimState, RunClaimStore

#: Persisted statuses that may still be written by a live engine.
PROTECTED_STATUSES = frozenset({"running", "initializing"})


class DeleteOutcome(str, Enum):
    """Result of one delete attempt."""

    DELETED = "deleted"
    REFUSED = "refused"


@dataclass(frozen=True)
class DeleteResult:
    """Outcome of one delete attempt with an actionable reason."""

    outcome: DeleteOutcome
    reason: str = ""
    index_cleared: bool = False

    @property
    def deleted(self) -> bool:
        return self.outcome is DeleteOutcome.DELETED


def _validate_run_id(run_id: str) -> str:
    """Return a safe single path segment or raise :class:`ValueError`."""
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("A run ID is required to delete a run.")
    if "\x00" in run_id:
        raise ValueError("The run ID contains an invalid character.")
    if run_id in (".", "..") or "/" in run_id or "\\" in run_id:
        raise ValueError("The run ID must be a single path segment.")
    return run_id


class RunStore:
    """Delete one run directory under explicit single-owner safety rules."""

    def __init__(
        self,
        project_root: Path,
        *,
        owner_id: str = "",
        claims: RunClaimStore | None = None,
        catalog: RunCatalog | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.runs_dir = self.project_root / ".specify" / "workflows" / "runs"
        self.owner_id = owner_id
        self.claims = claims or RunClaimStore(self.project_root)
        self.catalog = catalog or RunCatalog(self.project_root)

    def delete(self, run_id: str, *, protected_run_id: str | None = None) -> DeleteResult:
        """Remove one run directory, or refuse with an actionable reason."""
        try:
            run_id = _validate_run_id(run_id)
        except ValueError as exc:
            return DeleteResult(DeleteOutcome.REFUSED, str(exc))
        run_dir = self.runs_dir / run_id
        if not run_dir.is_dir():
            return DeleteResult(DeleteOutcome.REFUSED, f"Run directory is missing: {run_id}")
        if protected_run_id is not None and run_id == protected_run_id:
            return DeleteResult(
                DeleteOutcome.REFUSED,
                "This run is active in this Cockpit session and cannot be deleted.",
            )
        claim = self.claims.claim_state(run_id, self.owner_id)
        if claim in (ClaimState.LIVE_FOREIGN, ClaimState.OWNED):
            return DeleteResult(
                DeleteOutcome.REFUSED,
                "Another live Cockpit owns this run; refusing to delete it.",
            )
        try:
            descriptor = self.catalog.describe(run_id)
        except RunCatalogError as exc:
            return DeleteResult(DeleteOutcome.REFUSED, str(exc))
        if not descriptor.usable:
            return DeleteResult(
                DeleteOutcome.REFUSED,
                f"This run cannot be deleted: {descriptor.reason}.",
            )
        if descriptor.status in PROTECTED_STATUSES:
            return DeleteResult(
                DeleteOutcome.REFUSED,
                f"This run is {descriptor.status}; its engine may still be writing, "
                "so it cannot be deleted.",
            )
        resolved = run_dir.resolve()
        if resolved.parent != self.runs_dir.resolve():
            return DeleteResult(
                DeleteOutcome.REFUSED,
                "Refusing to delete a path outside the runs directory.",
            )
        try:
            shutil.rmtree(resolved)
        except OSError as exc:
            return DeleteResult(DeleteOutcome.REFUSED, f"Could not delete the run: {exc}")
        return DeleteResult(DeleteOutcome.DELETED)
