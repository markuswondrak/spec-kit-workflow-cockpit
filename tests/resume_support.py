"""Fixtures for seeding failed/resumable runs.

Split from :mod:`tests.support` (which is at its 500-line cap) so the resume
suites share one helper. The helper reuses the ``write_run`` state seeding and
adds a parseable launch-copy ``workflow.yml`` plus an optional ownership claim.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from tests.support import LINEAR_WORKFLOW, write_run
from workflow_cockpit.services.run_claim import CLAIM_FILE, ClaimState, OwnershipClaim

#: Fixed identity used to seed a claim whose liveness a test's store decides.
HOST = "test-host"
LIVE_PID = 4321
PROCESS_START = "100"


def write_launch_copy(root: Path, run_id: str, workflow: dict[str, Any] | None = None) -> Path:
    run_dir = root / ".specify" / "workflows" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "workflow.yml").write_text(
        yaml.safe_dump(workflow or LINEAR_WORKFLOW, sort_keys=False), encoding="utf-8"
    )
    return run_dir


def seed_failed_run(
    root: Path,
    run_id: str = "cockpit-failed",
    *,
    workflow: dict[str, Any] | None = None,
    current_step_id: str = "review",
    status: str = "failed",
    claim_state: ClaimState | None = None,
) -> Path:
    """Seed a run directory with a state, launch copy, and optional claim.

    A seeded ``claim_state`` writes a claim file with a fixed host/PID/start
    time. The caller supplies a :class:`RunClaimStore` configured for
    :data:`HOST` so ``LIVE_FOREIGN`` (live PID), ``STALE`` (dead PID), or
    ``OWNED`` (matching owner) is observed.
    """
    run_dir = write_run(root, run_id, status=status, current_step_id=current_step_id)
    write_launch_copy(root, run_id, workflow)
    if claim_state is not None:
        owner_id = "me" if claim_state is ClaimState.OWNED else "foreign"
        claim = OwnershipClaim(
            run_id=run_id,
            owner_id=owner_id,
            host=HOST,
            pid=LIVE_PID,
            pgid=LIVE_PID,
            process_start=PROCESS_START,
            created_at="2026-09-24T00:00:00+00:00",
        )
        (run_dir / CLAIM_FILE).write_text(json.dumps(claim.to_dict()), encoding="utf-8")
    return run_dir
