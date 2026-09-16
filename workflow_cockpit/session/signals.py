"""Catchable-signal shutdown for the one owned engine group.

``SIGINT``, ``SIGHUP``, and ``SIGTERM`` delivered to the Cockpit process must
abort and clean up the recorded engine group without a confirmation prompt.
The handler is constructed with a session *provider* because preflight creates
the session after the app starts. It registers on the running asyncio loop,
overrides the app's normal ``SIGINT`` exit path while mounted, schedules at most
one shutdown task, and only exits once the bounded cleanup attempt reports its
explicit result. Unsupported signal APIs (non-POSIX) retain default behavior.
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable, Iterable

#: Signals that trigger bounded best-effort cleanup. Built by name so importing
#: the package still works on platforms that lack ``SIGHUP``; registration is
#: unsupported there and ``SIGKILL`` is uncatchable by design.
CATCHABLE_SIGNALS = tuple(
    sig
    for name in ("SIGINT", "SIGHUP", "SIGTERM")
    if (sig := getattr(signal, name, None)) is not None
)


class SignalHandler:
    """Abort the active run on a catchable signal, then exit the app."""

    def __init__(
        self,
        session_provider: Callable[[], object | None],
        app,
        *,
        signals: Iterable[signal.Signals] | None = None,
    ) -> None:
        self._session_provider = session_provider
        self._app = app
        self._signals = tuple(signals) if signals is not None else CATCHABLE_SIGNALS
        self._loop: asyncio.AbstractEventLoop | None = None
        self._registered: list[signal.Signals] = []
        self._shutting_down = False
        self._task: asyncio.Task | None = None
        self.last_result = None

    @property
    def shutting_down(self) -> bool:
        return self._shutting_down

    @property
    def registered(self) -> tuple[signal.Signals, ...]:
        return tuple(self._registered)

    def register(self, loop: asyncio.AbstractEventLoop | None = None) -> SignalHandler:
        """Install the catchable handlers on the running loop."""
        loop = loop or asyncio.get_running_loop()
        self._loop = loop
        for sig in self._signals:
            try:
                loop.add_signal_handler(sig, self._on_signal)
            except (NotImplementedError, RuntimeError, ValueError):
                continue
            self._registered.append(sig)
        return self

    def close(self) -> None:
        """Remove every installed handler; safe to call more than once."""
        loop = self._loop
        if loop is not None:
            for sig in self._registered:
                try:
                    loop.remove_signal_handler(sig)
                except (NotImplementedError, RuntimeError, ValueError):
                    pass
        self._registered.clear()

    def _on_signal(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        if self._loop is not None:
            self._task = self._loop.create_task(self.shutdown())

    async def shutdown(self) -> None:
        """Run one bounded cleanup attempt, then exit the app."""
        session = self._session_provider()
        if session is not None and self._has_active_run(session):
            self.last_result = await asyncio.to_thread(self._abort, session)
        self._exit_app()

    @staticmethod
    def _has_active_run(session) -> bool:
        if getattr(session, "run_id", None) is None:
            return False
        try:
            snapshot = session.snapshot()
        except Exception:  # noqa: BLE001 - failed reads must not skip cleanup
            # A failed read model cannot prove that the supervisor is inactive.
            # Attempting Abort is safe for a reaped run and required for a live one.
            return True
        return snapshot is not None and not snapshot.terminal

    @staticmethod
    def _abort(session):
        try:
            session.abort()
        except Exception:  # noqa: BLE001 - best-effort cleanup must still exit
            return None
        return getattr(session, "last_abort_result", None)

    def _exit_app(self) -> None:
        try:
            self._app.exit()
        except Exception:  # noqa: BLE001 - exit must never raise during shutdown
            pass
