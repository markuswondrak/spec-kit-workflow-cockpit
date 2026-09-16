"""Polling loop that publishes immutable snapshots on a monotonic schedule.

The cadence and clock are the only scheduling concern here. Snapshot
production is a separate call so a UI can run ``produce`` in a worker thread
while ``begin`` suppresses an overlapping request. A failing snapshot keeps the
last good one and records the error instead of raising into the event loop.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from ..services.snapshot import RunSnapshot


class PollingLoop:
    """Tick the session within the 500 ms product bound."""

    def __init__(
        self,
        session,
        interval: float = 0.25,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session
        self.interval = interval
        self._clock = clock
        self._last_tick: float | None = None
        self._snapshot: RunSnapshot | None = None
        self._pending = False
        self._error = ""

    @property
    def last_snapshot(self) -> RunSnapshot | None:
        return self._snapshot

    @property
    def last_error(self) -> str:
        return self._error

    @property
    def pending(self) -> bool:
        return self._pending

    def due(self, now: float | None = None) -> bool:
        moment = self._clock() if now is None else now
        return self._last_tick is None or (moment - self._last_tick) >= self.interval

    def begin(self, *, force: bool = False) -> bool:
        """Claim a poll when one is due and none is already in flight."""
        if self._pending or (not force and not self.due()):
            return False
        self._pending = True
        return True

    def produce(self) -> RunSnapshot | None:
        """Produce one snapshot without ever raising into the event loop."""
        self._last_tick = self._clock()
        try:
            self._snapshot = self.session.snapshot()
            self._error = ""
        except Exception as exc:  # noqa: BLE001 - polling must not raise into the loop
            self._error = f"State refresh failed: {exc}"
        finally:
            self._pending = False
        return self._snapshot

    def tick(self) -> RunSnapshot | None:
        """Refresh and return the current snapshot unconditionally."""
        self._pending = True
        return self.produce()
