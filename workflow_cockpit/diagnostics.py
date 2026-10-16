"""Opt-in diagnostics for UI stalls and lost terminal input.

Set ``WORKFLOW_COCKPIT_DEBUG_LOG`` to a file path to enable. Nothing is written to
stdout or stderr, because the terminal belongs to the TUI. With the variable unset,
nothing is logged and no timer is started.

Send ``SIGUSR1`` to the process (``kill -USR1 <pid>``) to append a stack dump of
every thread to the same file. The process keeps running.

Keystroke text and pasted content are never logged; only event types and lengths.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import signal
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Final, TextIO

ENV_VAR: Final = "WORKFLOW_COCKPIT_DEBUG_LOG"
LOGGER_NAME: Final = "workflow_cockpit"
#: A gap between two heartbeat ticks at least this long means the loop was blocked.
STALL_SECONDS: Final = 0.5
#: Interval between input summaries in the log.
SUMMARY_SECONDS: Final = 30.0

_LOG = logging.getLogger(LOGGER_NAME)
_handler: logging.Handler | None = None
_stream: TextIO | None = None
_previous_excepthook: Callable[..., Any] | None = None
_previous_thread_excepthook: Callable[..., Any] | None = None


def enabled() -> bool:
    return _handler is not None


def configure(environ: Mapping[str, str] | None = None) -> str | None:
    """Enable the file log when ``WORKFLOW_COCKPIT_DEBUG_LOG`` is set.

    Returns the log path when diagnostics are active. A path that cannot be opened
    leaves diagnostics disabled, so the run itself is never affected.
    """
    global _handler, _stream, _previous_excepthook, _previous_thread_excepthook
    source = os.environ if environ is None else environ
    path = source.get(ENV_VAR, "").strip()
    if not path:
        return None
    if _handler is not None:
        return path
    try:
        stream = open(path, "a", encoding="utf-8", buffering=1)
    except OSError:
        return None

    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s.%(msecs)03d %(levelname)s %(threadName)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    _LOG.addHandler(handler)
    _LOG.setLevel(logging.DEBUG)
    _handler, _stream = handler, stream

    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, file=stream, all_threads=True, chain=False)
    _previous_excepthook = sys.excepthook
    sys.excepthook = _log_uncaught
    _previous_thread_excepthook = threading.excepthook
    threading.excepthook = _log_thread_uncaught

    _LOG.info("diagnostics enabled pid=%d python=%s", os.getpid(), sys.version.split()[0])
    return path


def reset() -> None:
    """Disable diagnostics and restore the process hooks. Used by tests."""
    global _handler, _stream, _previous_excepthook, _previous_thread_excepthook
    if _handler is None:
        return
    _LOG.removeHandler(_handler)
    _handler.close()
    if _stream is not None:
        _stream.close()
    if hasattr(signal, "SIGUSR1"):
        faulthandler.unregister(signal.SIGUSR1)
    if _previous_excepthook is not None:
        sys.excepthook = _previous_excepthook
    if _previous_thread_excepthook is not None:
        threading.excepthook = _previous_thread_excepthook
    _handler = _stream = None
    _previous_excepthook = _previous_thread_excepthook = None
    _LOG.setLevel(logging.NOTSET)


def _log_uncaught(exc_type, exc, tb) -> None:
    _LOG.critical("uncaught exception", exc_info=(exc_type, exc, tb))
    if _previous_excepthook is not None:
        _previous_excepthook(exc_type, exc, tb)


def _log_thread_uncaught(args) -> None:
    name = args.thread.name if args.thread is not None else "unknown"
    _LOG.critical(
        "uncaught exception in thread %s",
        name,
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )
    if _previous_thread_excepthook is not None:
        _previous_thread_excepthook(args)


@contextmanager
def timed(label: str, *, warn_ms: float = 100.0) -> Iterator[None]:
    """Log ``label`` at WARNING when the block takes at least ``warn_ms``."""
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if elapsed_ms >= warn_ms:
            _LOG.warning("slow %s: %.0f ms", label, elapsed_ms)


class InputMonitor:
    """Detect event-loop stalls and count terminal input per summary interval.

    ``tick`` runs on a short timer on the UI loop. A large gap between ticks means
    the loop was blocked for that long. The counters show whether keys and mouse
    events still reach the application, which separates a blocked loop from input
    that never arrives.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last_tick = clock()
        self._last_summary = self._last_tick
        self._counts: Counter[str] = Counter()

    def note_input(self, kind: str) -> None:
        self._counts[kind] += 1

    def tick(self) -> None:
        now = self._clock()
        gap = now - self._last_tick
        self._last_tick = now
        if gap >= STALL_SECONDS:
            _LOG.warning("ui stall: event loop did not run for %.2f s", gap)
        if now - self._last_summary >= SUMMARY_SECONDS:
            summary = ", ".join(f"{kind}={count}" for kind, count in sorted(self._counts.items()))
            _LOG.info("input in last %.0f s: %s", now - self._last_summary, summary or "none")
            self._counts.clear()
            self._last_summary = now
