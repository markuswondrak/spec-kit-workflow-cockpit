"""Refuse Start when the current-run pointer names a non-terminal run (FR-029/030).

Two surfaces can start a run in one worktree: the TUI's Start button and the
headless host's ``start`` operation. Both consult this one guard, so the refusal
rule, its message, and its actionable alternatives cannot drift apart.

The guard reads only the pointer pair and the persisted run files. It takes no
claim, writes nothing, and signals nothing: it is a read-side defense, not a
lock.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .current_run_pointer import CurrentRunPointerReader, PointerState
from .run_catalog import RunCatalog, RunCatalogError

#: Persisted statuses that mean the run is over, so a new run may start.
TERMINAL_STATUSES = frozenset({"completed", "failed", "aborted"})

#: Structured error code used by the host protocol for this refusal.
REFUSAL_CODE = "run_in_progress"


@dataclass(frozen=True)
class StartRefusal:
    """Why Start must be refused, and what the user can do about it."""

    run_id: str
    status: str
    message: str
    action: str = "adopt or abort the current run first"

    @property
    def code(self) -> str:
        return REFUSAL_CODE

    def details(self) -> dict[str, str]:
        return {"run_id": self.run_id, "status": self.status}


class StartGuard:
    """Decide whether a new run may start in this worktree."""

    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root)

    @property
    def runs_dir(self) -> Path:
        return self.project_root / ".specify" / "workflows" / "runs"

    def check(self) -> StartRefusal | None:
        """A refusal when the current-run pointer names a non-terminal run."""
        pointer = CurrentRunPointerReader(self.project_root).read()
        if pointer.state is PointerState.DISAGREEMENT:
            named = pointer.run_id or pointer.markdown_run_id or pointer.json_run_id or ""
            return StartRefusal(
                run_id=named,
                status="unknown",
                message=(
                    f"The current-run pointer is inconsistent: {pointer.detail} "
                    "Repair the pointer before starting a new run."
                ),
                action="repair the current-run pointer first",
            )
        if not pointer.usable or not pointer.run_id:
            return None
        run_id = pointer.run_id
        if not (self.runs_dir / run_id).is_dir():
            return None
        try:
            descriptor = RunCatalog(self.project_root).describe(run_id)
        except RunCatalogError:
            return None
        if not descriptor.usable or descriptor.status in TERMINAL_STATUSES:
            return None
        return StartRefusal(
            run_id=run_id,
            status=descriptor.status,
            message=(
                f"Run {run_id} is {descriptor.status}; a new run cannot start while it is "
                "non-terminal. Adopt that run to continue it, or abort it first."
            ),
        )
