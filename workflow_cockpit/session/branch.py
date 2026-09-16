"""Cached, guarded Git branch tracking that never blocks a poll."""

from __future__ import annotations

import threading


class BranchTracker:
    """Keep the last good branch and record a classified failure.

    A Git probe can time out or fail; the tracker retains the previous value and
    exposes an actionable diagnostic until a later probe succeeds, so a poll
    never raises or blocks on Git.
    """

    def __init__(self, git) -> None:
        self._git = git
        self._lock = threading.RLock()
        self._value: str | None = None
        self._error = ""

    @property
    def value(self) -> str | None:
        with self._lock:
            return self._value

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    def refresh(self) -> str | None:
        try:
            value, error = self._read()
        except Exception as exc:  # noqa: BLE001 - a Git failure must not stop polling
            value, error = None, f"Git branch lookup failed: {exc}"
        with self._lock:
            if value is not None:
                self._value = value
            self._error = error
            return self._value

    def _read(self) -> tuple[str | None, str]:
        result = getattr(self._git, "branch_result", None)
        if callable(result):
            read = result()
            return read.value, ("" if read.ok else read.error)
        return self._git.branch(), ""
