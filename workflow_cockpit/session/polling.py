"""Polling loop that publishes immutable snapshots on a monotonic schedule."""

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

    @property
    def last_snapshot(self) -> RunSnapshot | None:
        return self._snapshot

    def due(self, now: float | None = None) -> bool:
        moment = self._clock() if now is None else now
        return self._last_tick is None or (moment - self._last_tick) >= self.interval

    def tick(self) -> RunSnapshot:
        """Refresh and return the current snapshot unconditionally."""
        self._last_tick = self._clock()
        self._snapshot = self.session.snapshot()
        return self._snapshot
