"""Run-scoped host lifetime and the catchable-death abort hook (FR-026/027).

The host lives exactly as long as its run needs an owner (research R4):

``starting -> serving(run: none|running|paused|terminal) -> releasing -> exited``

It transitions to ``releasing`` when the run is terminal, or when the run is
paused at a gate and no client has been connected for a grace window. It never
releases while a step runs, and a reconnecting client resets the grace window so
a frontend reload is not raced. Releasing frees the claim and exits, leaving the
run adoptable by any frontend.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

#: Default grace window before an unattended paused host releases (research R4).
GRACE_SECONDS = 2.0

STARTING = "starting"
SERVING = "serving"
RELEASING = "releasing"
EXITED = "exited"

RUN_NONE = "none"
RUN_RUNNING = "running"
RUN_PAUSED = "paused"
RUN_TERMINAL = "terminal"

#: Persisted or outcome statuses that mean the run is over.
TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "aborted", "success", "failure", "abort"}
)

#: Persisted statuses that mean a step is (or may be) executing.
RUNNING_STATUSES = frozenset({"initializing", "running", "created", "awaiting", "aborting"})


def run_state_for(status: str | None) -> str:
    """Map a persisted status onto the lifetime's run sub-state."""
    if not status or status in ("idle", "none"):
        return RUN_NONE
    if status in TERMINAL_STATUSES:
        return RUN_TERMINAL
    if status == "paused":
        return RUN_PAUSED
    if status in RUNNING_STATUSES:
        return RUN_RUNNING
    return RUN_RUNNING


@dataclass
class HostLifetime:
    """Evaluate the run-scoped exit rule on every observed event."""

    grace_seconds: float = GRACE_SECONDS
    state: str = STARTING
    run_state: str = RUN_NONE
    _unattended_since: float | None = field(default=None, repr=False)

    @property
    def serving(self) -> bool:
        return self.state == SERVING

    @property
    def released(self) -> bool:
        return self.state in (RELEASING, EXITED)

    def observe(self, *, run_status: str | None, clients: int, now: float) -> str:
        """Advance the state machine; return the new state."""
        if self.state in (RELEASING, EXITED):
            return self.state
        self.state = SERVING
        self.run_state = run_state_for(run_status)

        if self.run_state == RUN_TERMINAL:
            self.state = RELEASING
            return self.state

        if self.run_state == RUN_PAUSED and clients <= 0:
            if self._unattended_since is None:
                self._unattended_since = now
            elif now - self._unattended_since >= self.grace_seconds:
                self.state = RELEASING
            return self.state

        # A running step, a live client, or no run at all keeps the host alive.
        self._unattended_since = None
        return self.state

    def exit(self) -> None:
        self.state = EXITED

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "run": self.run_state,
            "grace_seconds": self.grace_seconds,
            "pid": os.getpid(),
        }


def catchable_death_abort(session: Any) -> dict[str, Any]:
    """Run the same bounded best-effort abort as the TUI when the host dies.

    Only the existing session/supervisor path is used, so a signal is sent only
    to a verified live process group (ADR-0006). The result is reported rather
    than raised: the process is on its way out.
    """
    result = None
    try:
        session.abort()
        result = getattr(session, "last_abort_result", None)
    except Exception as exc:  # noqa: BLE001 - a dying host must not raise again
        return {"aborted": False, "reason": str(exc)}
    if result is None:
        return {"aborted": True, "signalled": False, "reaped": False, "escalation": None}
    return {
        "aborted": bool(getattr(result, "ok", True)),
        "signalled": bool(getattr(result, "signalled", False)),
        "reaped": bool(getattr(result, "reaped", False)),
        "escalation": getattr(result, "escalation", None),
    }
