"""Tolerant reads of engine run files, skipping unchanged content.

Every JSON source is stat'd before and after its read. An atomic replacement or
an in-progress write is detected by a changed signature and retried on the next
poll; a source that is stably missing, unreadable, undecodable, or invalid
after a previously valid read keeps its last good value, marks the run stale,
and carries a diagnostic. A source that has never produced a valid value
remains ``initializing`` without a stale marker, and an incomplete trailing
JSONL record is a normal pending write rather than corruption.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_UNSET = object()

#: Bytes read from the end of ``log.jsonl`` for the displayed tail.
LOG_WINDOW_BYTES = 256 * 1024


class Freshness(str, Enum):
    """Freshness of one source after a read attempt."""

    OK = "ok"
    PENDING = "pending"
    UNSTABLE = "unstable"
    STALE = "stale"


@dataclass(frozen=True)
class RunStateData:
    status: str = "initializing"
    current_step_id: str | None = None
    current_step_index: int = 0
    step_results: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    updated_at: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    log_tail: tuple[dict[str, Any], ...] = ()
    complete: bool = False
    stale: bool = False
    diagnostic: str = ""
    state_freshness: Freshness = Freshness.PENDING
    log_freshness: Freshness = Freshness.PENDING

    def current_result(self) -> dict[str, Any] | None:
        """The recorded result mapping for the current runtime step, if any."""
        if not self.current_step_id:
            return None
        result = self.step_results.get(self.current_step_id)
        return result if isinstance(result, dict) else None


@dataclass
class _CacheEntry:
    signature: tuple[int, int, int] | None
    value: Any


def _combine(*messages: str) -> str:
    seen: list[str] = []
    for message in messages:
        if message and message not in seen:
            seen.append(message)
    return " ".join(seen)


class RunStateReader:
    """Read ``state.json``/``inputs.json``/``log.jsonl`` with a tolerant cache.

    Files are considered unchanged when inode, size, and mtime are stable, so an
    atomic replacement with identical content is still detected via the inode.
    A private lock covers the bounded I/O and the cache update so a decision and
    a poll cannot race the same cache.
    """

    def __init__(
        self,
        project_root: Path,
        run_id: str,
        log_tail: int = 80,
        *,
        log_window_bytes: int = LOG_WINDOW_BYTES,
    ) -> None:
        self.run_dir = Path(project_root) / ".specify" / "workflows" / "runs" / run_id
        self.log_tail = log_tail
        self.log_window_bytes = log_window_bytes
        self._lock = threading.RLock()
        self._state_cache: _CacheEntry | None = None
        self._inputs_cache: _CacheEntry | None = None
        self._log_signature: tuple[int, int, int] | None = None
        self._log_tail: tuple[dict[str, Any], ...] = ()
        self._log_diagnostic = ""

    @staticmethod
    def _signature(path: Path) -> tuple[int, int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return (stat.st_ino, stat.st_size, stat.st_mtime_ns)

    @staticmethod
    def _has_value(cache: _CacheEntry | None) -> bool:
        return cache is not None and cache.value is not _UNSET

    def _read_json(
        self,
        path: Path,
        cache: _CacheEntry | None,
        valid: Callable[[Any], bool],
    ) -> tuple[Any, _CacheEntry, Freshness, str]:
        name = path.name
        before = self._signature(path)
        if before is None:
            if self._has_value(cache):
                return cache.value, cache, Freshness.STALE, f"{name} is missing; showing the last good value."
            return _UNSET, _CacheEntry(None, _UNSET), Freshness.PENDING, ""
        if cache is not None and cache.signature == before and self._has_value(cache):
            return cache.value, cache, Freshness.OK, ""

        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            value = json.loads(text)
            if not valid(value):
                raise ValueError("invalid JSON shape")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            after = self._signature(path)
            if after != before:
                # An in-progress replacement: retain the prior value and retry.
                return self._retain(cache)
            if self._has_value(cache):
                return (
                    cache.value,
                    _CacheEntry(after, cache.value),
                    Freshness.STALE,
                    f"{name} could not be read; showing the last good value.",
                )
            return _UNSET, _CacheEntry(after, _UNSET), Freshness.PENDING, ""

        after = self._signature(path)
        if after != before:
            # The source changed during the read: treat as an in-progress write.
            return self._retain(cache)
        return value, _CacheEntry(after, value), Freshness.OK, ""

    @staticmethod
    def _retain(cache: _CacheEntry | None):
        # Do not cache a signature for a read that raced a write: the next poll
        # must re-read rather than treat the retained value as fresh.
        value = cache.value if cache is not None else _UNSET
        return value, _CacheEntry(None, value), Freshness.UNSTABLE, ""

    def _read_log(self) -> tuple[tuple[dict[str, Any], ...], Freshness, str]:
        path = self.run_dir / "log.jsonl"
        signature = self._signature(path)
        if signature is None:
            if self._log_signature is not None:
                return (
                    self._log_tail,
                    Freshness.STALE,
                    "log.jsonl is missing; showing the last good tail.",
                )
            return (), Freshness.PENDING, ""
        if self._log_signature == signature:
            return self._log_tail, Freshness.OK, self._log_diagnostic

        try:
            size = path.stat().st_size
            start = max(0, size - self.log_window_bytes)
            with open(path, "rb") as handle:
                handle.seek(start)
                raw = handle.read(self.log_window_bytes)
        except OSError:
            if self._log_tail:
                return (
                    self._log_tail,
                    Freshness.STALE,
                    "log.jsonl could not be read; showing the last good tail.",
                )
            return (), Freshness.PENDING, ""

        text = raw.decode("utf-8", errors="replace")
        lines = text.split("\n")
        if start > 0:
            lines = lines[1:]
        if text and not text.endswith("\n"):
            # An incomplete trailing record is a normal pending write.
            lines = lines[:-1]

        entries: list[dict[str, Any]] = []
        malformed = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(record, dict):
                entries.append(record)

        self._log_signature = signature
        self._log_tail = tuple(entries[-self.log_tail :])
        self._log_diagnostic = (
            f"log.jsonl contains {malformed} malformed event(s); showing the last good tail."
            if malformed
            else ""
        )
        return self._log_tail, Freshness.OK, self._log_diagnostic

    def read(self) -> RunStateData | None:
        if not self.run_dir.is_dir():
            return None
        with self._lock:
            state, self._state_cache, state_fresh, state_diag = self._read_json(
                self.run_dir / "state.json",
                self._state_cache,
                lambda value: isinstance(value, dict)
                and isinstance(value.get("status"), str)
                and bool(value["status"]),
            )
            inputs, self._inputs_cache, inputs_fresh, inputs_diag = self._read_json(
                self.run_dir / "inputs.json",
                self._inputs_cache,
                lambda value: isinstance(value, dict) and isinstance(value.get("inputs", {}), dict),
            )
            log_tail, log_fresh, log_diag = self._read_log()

        stale = Freshness.STALE in (state_fresh, inputs_fresh, log_fresh)
        diagnostic = _combine(state_diag, inputs_diag, log_diag)
        inputs_map = inputs.get("inputs", {}) if isinstance(inputs, dict) else {}

        if state is _UNSET or not isinstance(state, dict):
            return RunStateData(
                inputs=inputs_map,
                log_tail=log_tail,
                complete=False,
                stale=stale,
                diagnostic=diagnostic,
                state_freshness=state_fresh,
                log_freshness=log_fresh,
            )

        status = state.get("status")
        step_results = state.get("step_results")
        return RunStateData(
            status=str(status) if isinstance(status, str) and status else "initializing",
            current_step_id=(
                state.get("current_step_id")
                if isinstance(state.get("current_step_id"), str)
                else None
            ),
            current_step_index=(
                state.get("current_step_index")
                if isinstance(state.get("current_step_index"), int)
                else 0
            ),
            step_results=step_results if isinstance(step_results, dict) else {},
            error=state.get("error") if isinstance(state.get("error"), str) else None,
            updated_at=state.get("updated_at") if isinstance(state.get("updated_at"), str) else None,
            inputs=inputs_map,
            log_tail=log_tail,
            complete=state_fresh is Freshness.OK,
            stale=stale,
            diagnostic=diagnostic,
            state_freshness=state_fresh,
            log_freshness=log_fresh,
        )
