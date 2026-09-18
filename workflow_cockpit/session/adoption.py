"""Prepare an existing paused run for adoption without spawning the engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..services.definition import DefinitionError, WorkflowDefinition
from ..services.launch_definition import definition_from_launch_copy
from ..services.run_catalog import RunCatalog, RunCatalogError, RunDescriptor
from ..services.run_claim import (
    ClaimOutcome,
    ClaimState,
    OwnershipClaim,
    RunClaimStore,
    current_claim,
)


class AdoptError(Exception):
    """Raised when an existing run cannot be adopted safely."""


@dataclass(frozen=True)
class AdoptedBinding:
    """The resolved result of adopting one run, ready for the session to bind."""

    run_id: str
    descriptor: RunDescriptor
    definition: WorkflowDefinition
    claim: OwnershipClaim


class RunAdopter:
    """Orchestrate describe -> claim -> launch-copy definition, spawning nothing."""

    def __init__(
        self,
        project_root: Path,
        *,
        catalog: RunCatalog | None = None,
        claims: RunClaimStore | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.claims = claims or RunClaimStore(self.project_root)
        self.catalog = catalog or RunCatalog(self.project_root, claim_store=self.claims)

    def prepare(self, run_id: str, owner_id: str, *, branch: str | None = None) -> AdoptedBinding:
        """Resolve one adoptable run or raise :class:`AdoptError`."""
        try:
            descriptor = self.catalog.describe(run_id)
        except RunCatalogError as exc:
            raise AdoptError(str(exc)) from exc
        if not descriptor.usable:
            raise AdoptError(f"This run cannot be adopted: {descriptor.reason}.")
        if descriptor.status != "paused":
            raise AdoptError(
                f"Only a paused run can be adopted; this run is {descriptor.status} and "
                "stays read-only."
            )
        if not descriptor.launch_copy:
            raise AdoptError(
                "This run has no launch-copy workflow definition; it cannot be adopted."
            )
        if descriptor.claim_state == ClaimState.LIVE_FOREIGN:
            raise AdoptError("Another live Cockpit owns this run; refusing to adopt it.")

        claim = current_claim(run_id, owner_id, branch=branch)
        outcome = self.claims.acquire(run_id, claim)
        if outcome is ClaimOutcome.HELD_BY_LIVE_FOREIGN:
            raise AdoptError("Another live Cockpit owns this run; refusing to adopt it.")
        if outcome is not ClaimOutcome.ACQUIRED:
            raise AdoptError("Could not establish ownership of this run.")

        try:
            definition = definition_from_launch_copy(self._run_dir(run_id) / "workflow.yml")
        except DefinitionError as exc:
            self.claims.release(run_id, owner_id)
            raise AdoptError(f"This run cannot be adopted: {exc}") from exc
        return AdoptedBinding(
            run_id=run_id,
            descriptor=descriptor,
            definition=definition,
            claim=claim,
        )

    def prepare_inspect(self, run_id: str) -> tuple[RunDescriptor, WorkflowDefinition]:
        """Resolve one viewable run for read-only inspection without claiming."""
        try:
            descriptor = self.catalog.describe(run_id)
        except RunCatalogError as exc:
            raise AdoptError(str(exc)) from exc
        if not descriptor.usable:
            raise AdoptError(f"This run cannot be viewed: {descriptor.reason}.")
        if not descriptor.launch_copy:
            raise AdoptError(
                "This run has no launch-copy workflow definition; it cannot be viewed."
            )
        try:
            definition = definition_from_launch_copy(self._run_dir(run_id) / "workflow.yml")
        except DefinitionError as exc:
            raise AdoptError(f"This run cannot be viewed: {exc}") from exc
        return descriptor, definition

    def _run_dir(self, run_id: str) -> Path:
        return self.project_root / ".specify" / "workflows" / "runs" / run_id

    def release(self, run_id: str, owner_id: str) -> None:
        self.claims.release(run_id, owner_id)
