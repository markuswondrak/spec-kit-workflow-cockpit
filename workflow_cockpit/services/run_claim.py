"""Ownership claim value objects and durable claim store for one run.

The claim is a Cockpit-owned JSON file inside the run directory. It never
signals a process: it records owner identity and enough liveness evidence
(host, PID/PGID, process start time) to detect a live foreign owner, a reused
PID, or a stale claim left by a crash.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

#: Bumped when the on-disk claim shape changes incompatibly.
CLAIM_SCHEMA_VERSION = 1

#: Bounded read for the claim file.
MAX_CLAIM_BYTES = 64 * 1024

#: Claim file name inside the run directory.
CLAIM_FILE = ".cockpit-owner.json"


class ClaimState(str, Enum):
    """How a run's ownership claim relates to the asking owner."""

    NONE = "none"
    OWNED = "owned"
    LIVE_FOREIGN = "live_foreign"
    STALE = "stale"


class ClaimOutcome(str, Enum):
    """Result of one acquire attempt."""

    ACQUIRED = "acquired"
    HELD_BY_LIVE_FOREIGN = "held_by_live_foreign"
    FAILED = "failed"


@dataclass(frozen=True)
class OwnershipClaim:
    """The durable record naming the single Cockpit owner of a run."""

    run_id: str
    owner_id: str
    host: str
    pid: int
    pgid: int
    process_start: str | None
    created_at: str
    branch: str | None = None
    schema_version: int = CLAIM_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "owner_id": self.owner_id,
            "host": self.host,
            "pid": self.pid,
            "pgid": self.pgid,
            "process_start": self.process_start,
            "created_at": self.created_at,
            "branch": self.branch,
        }

    @classmethod
    def from_dict(cls, data: Any) -> OwnershipClaim | None:
        """Return a claim when ``data`` has the required shape, else ``None``."""
        if not isinstance(data, dict):
            return None
        run_id = data.get("run_id")
        owner_id = data.get("owner_id")
        if not isinstance(run_id, str) or not run_id:
            return None
        if not isinstance(owner_id, str) or not owner_id:
            return None
        host = data.get("host")
        if not isinstance(host, str) or not host:
            return None
        pid = data.get("pid")
        pgid = data.get("pgid")
        if not isinstance(pid, int) or isinstance(pid, bool):
            return None
        if not isinstance(pgid, int) or isinstance(pgid, bool):
            return None
        process_start = data.get("process_start")
        if process_start is not None and not isinstance(process_start, str):
            return None
        created_at = data.get("created_at")
        if not isinstance(created_at, str):
            return None
        branch = data.get("branch")
        if branch is not None and not isinstance(branch, str):
            branch = None
        schema_version = data.get("schema_version", CLAIM_SCHEMA_VERSION)
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            schema_version = CLAIM_SCHEMA_VERSION
        return cls(
            run_id=run_id,
            owner_id=owner_id,
            host=host,
            pid=pid,
            pgid=pgid,
            process_start=process_start,
            created_at=created_at,
            branch=branch,
            schema_version=schema_version,
        )


def process_start_time(pid: int) -> str | None:
    """Return the recorded start time (``/proc/<pid>/stat`` field 22), if any."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_bytes()
    except OSError:
        return None
    try:
        # ``comm`` may contain spaces and parentheses; split on the final ')'.
        fields = raw[raw.rindex(b")") + 2 :].split()
        return fields[19].decode("ascii")
    except (ValueError, IndexError, UnicodeDecodeError):
        return None


def pid_alive(pid: int) -> bool:
    """Best-effort liveness without signalling the process."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def current_claim(
    run_id: str,
    owner_id: str,
    *,
    host: str | None = None,
    pid: int | None = None,
    pgid: int | None = None,
    branch: str | None = None,
    now: Callable[[], datetime] | None = None,
) -> OwnershipClaim:
    """Build the claim describing this process for ``run_id``."""
    process_id = os.getpid() if pid is None else pid
    try:
        process_group = os.getpgid(0) if pgid is None else pgid
    except OSError:
        process_group = process_id
    created = (now or (lambda: datetime.now(timezone.utc)))()
    return OwnershipClaim(
        run_id=run_id,
        owner_id=owner_id,
        host=host or socket.gethostname(),
        pid=process_id,
        pgid=process_group,
        process_start=process_start_time(process_id),
        created_at=created.isoformat(),
        branch=branch,
    )


class RunClaimStore:
    """Read, acquire, and release the single ownership claim of a run."""

    def __init__(
        self,
        project_root: Path,
        *,
        host: str | None = None,
        max_bytes: int = MAX_CLAIM_BYTES,
        pid_alive: Callable[[int], bool] = pid_alive,
        start_time: Callable[[int], str | None] = process_start_time,
    ) -> None:
        self.project_root = Path(project_root)
        self.runs_dir = self.project_root / ".specify" / "workflows" / "runs"
        self.host = host or socket.gethostname()
        self.max_bytes = max_bytes
        self._pid_alive = pid_alive
        self._start_time = start_time

    def claim_path(self, run_id: str) -> Path:
        return self.runs_dir / run_id / CLAIM_FILE

    def read(self, run_id: str) -> OwnershipClaim | None:
        path = self.claim_path(run_id)
        try:
            if not path.is_file() or path.stat().st_size > self.max_bytes:
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return OwnershipClaim.from_dict(data)

    def claim_state(self, run_id: str, owner_id: str | None) -> ClaimState:
        claim = self.read(run_id)
        if claim is None:
            return ClaimState.NONE
        if owner_id is not None and claim.owner_id == owner_id:
            return ClaimState.OWNED
        if self._is_live(claim):
            return ClaimState.LIVE_FOREIGN
        return ClaimState.STALE

    def acquire(self, run_id: str, claim: OwnershipClaim) -> ClaimOutcome:
        run_dir = self.runs_dir / run_id
        if not run_dir.is_dir():
            return ClaimOutcome.FAILED
        existing = self.read(run_id)
        if existing is not None and existing.owner_id != claim.owner_id and self._is_live(existing):
            return ClaimOutcome.HELD_BY_LIVE_FOREIGN
        if not self._write(run_dir, claim):
            return ClaimOutcome.FAILED
        return ClaimOutcome.ACQUIRED

    def release(self, run_id: str, owner_id: str) -> None:
        """Delete the claim only when this owner wrote it."""
        claim = self.read(run_id)
        if claim is None or claim.owner_id != owner_id:
            return
        try:
            self.claim_path(run_id).unlink()
        except OSError:
            return

    def _is_live(self, claim: OwnershipClaim) -> bool:
        """Conservative liveness: cross-host or unverifiable claims stay live."""
        if claim.host != self.host:
            return True
        if not self._pid_alive(claim.pid):
            return False
        current = self._start_time(claim.pid)
        if claim.process_start is None or current is None:
            # No start-time evidence: prefer not to steal a live PID.
            return True
        # A changed start time means the PID was reused; the claim is stale.
        return current == claim.process_start

    def _write(self, run_dir: Path, claim: OwnershipClaim) -> bool:
        payload = json.dumps(claim.to_dict(), indent=2)
        try:
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=run_dir,
                prefix=".cockpit-owner-",
                suffix=".tmp",
                delete=False,
            )
            temp_path = Path(handle.name)
            try:
                with handle:
                    handle.write(payload)
                os.replace(temp_path, self.claim_path(claim.run_id))
            except OSError:
                temp_path.unlink(missing_ok=True)
                return False
        except OSError:
            return False
        return True
