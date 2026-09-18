"""Run and owner identity allocation for one Cockpit session."""

from __future__ import annotations

import secrets
import uuid
from pathlib import Path


class IdentityError(Exception):
    """Raised when a unique run identity cannot be allocated."""


def generate_run_id(runs_dir: Path) -> str:
    """Return a collision-resistant run ID whose directory does not exist."""
    for _ in range(100):
        candidate = f"cockpit-{secrets.token_hex(6)}"
        if not (runs_dir / candidate).exists():
            return candidate
    raise IdentityError("Could not allocate a unique run ID.")


def owner_id() -> str:
    """Return a fresh opaque owner identity, held stable for one session."""
    return uuid.uuid4().hex
