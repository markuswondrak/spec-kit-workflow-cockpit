"""Incrementally aggregate timing data from an append-only engine log.

Timings are keyed by scope occurrence: ``(workflow_id, execution_path,
step_id)``. The engine writes ``workflow_id`` and ``execution_path`` only for
events from a called scope, so an event without them belongs to the run's root
scope and is keyed by its qualified step id alone (which already distinguishes
loop iterations, e.g. ``notes-loop:notes-call:1``). Treating ``execution_path``
as an opaque tuple keeps a root ``review`` and a child ``review``, and the same
child called twice, from ever merging.

Legacy callers that pass a declared-id set keep the old lookup by bare id: the
index answers both the scoped key and, for root-scope events, the declared id.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .graph import resolve_declared_id

#: Bytes read from the log per ``update`` so a growing file cannot stall a poll.
MAX_READ_BYTES = 256 * 1024

#: Key prefix shared by every event logged from the run's root scope.
ROOT_TIMING_PREFIX: tuple[str, tuple] = ("", ())


@dataclass(frozen=True)
class StepTiming:
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str | None = None


class TimingIndex(dict):
    """Scoped timing index that also answers a bare declared step id.

    ``index[("", (), "verify")]`` and ``index["verify"]`` are the same entry, so
    legacy consumers (and flat-run tests) keep working while composed runs use
    the full scoped key.
    """

    def __getitem__(self, key: Any) -> StepTiming:
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        if isinstance(key, str):
            return dict.__getitem__(self, (*ROOT_TIMING_PREFIX, key))
        raise KeyError(key)

    def get(self, key: Any, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default


class RunLogAggregator:
    """Keep bounded per-scope timing aggregates while accepting partial writes.

    Each incremental read is capped, and the unread offset plus the trailing
    partial record are retained so the next call resumes where the previous one
    stopped. A complete, newline-delimited malformed event increments a
    diagnostic counter but never discards prior timing data. A private lock
    covers the bounded I/O and the cache update.
    """

    def __init__(
        self,
        declared_ids: frozenset[str] | None,
        *,
        max_read_bytes: int = MAX_READ_BYTES,
    ) -> None:
        self._declared_ids = declared_ids
        self._max_read_bytes = max_read_bytes
        self._lock = threading.RLock()
        self._signature: tuple[int, int] | None = None
        self._offset = 0
        self._partial = b""
        self._timings: dict[tuple, StepTiming] = {}
        self._malformed = 0

    @property
    def diagnostic(self) -> str:
        with self._lock:
            if not self._malformed:
                return ""
            return (
                f"log.jsonl contains {self._malformed} malformed event(s); "
                "showing the last good timings."
            )

    @staticmethod
    def _timestamp(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _reset(self, signature: tuple[int, int]) -> None:
        self._signature = signature
        self._offset = 0
        self._partial = b""
        self._timings = {}
        self._malformed = 0

    def update(self, path: Path) -> TimingIndex:
        with self._lock:
            try:
                stat = path.stat()
            except OSError:
                return TimingIndex(self._timings)
            signature = (stat.st_ino, stat.st_dev)
            if self._signature != signature or stat.st_size < self._offset:
                self._reset(signature)
            try:
                with path.open("rb") as handle:
                    handle.seek(self._offset)
                    chunk = handle.read(self._max_read_bytes)
            except OSError:
                return TimingIndex(self._timings)
            self._offset += len(chunk)
            data = self._partial + chunk
            lines = data.split(b"\n")
            self._partial = lines.pop()
            for line in lines:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._malformed += 1
                    continue
                if isinstance(event, dict):
                    self._record(event)
            return TimingIndex(self._timings)

    def _key(self, event: dict[str, object]) -> tuple | None:
        step_id = event.get("step_id")
        if not isinstance(step_id, str) or not step_id:
            return None
        if self._declared_ids is not None:
            # Legacy mode: root-scope events only, normalized to a declared id.
            declared = resolve_declared_id(step_id, self._declared_ids)
            return (*ROOT_TIMING_PREFIX, declared) if declared is not None else None
        workflow_id = event.get("workflow_id")
        if isinstance(workflow_id, str) and workflow_id:
            raw_path = event.get("execution_path")
            path = tuple(raw_path) if isinstance(raw_path, list) else ()
            return (workflow_id, path, step_id)
        return (*ROOT_TIMING_PREFIX, step_id)

    def _record(self, event: dict[str, object]) -> None:
        key = self._key(event)
        if key is None:
            return
        event_type = event.get("event")
        previous = self._timings.get(key, StepTiming())
        timestamp = self._timestamp(event.get("timestamp"))
        if event_type == "step_started":
            self._timings[key] = StepTiming(
                attempts=previous.attempts + 1,
                started_at=timestamp,
                status="running",
            )
        elif event_type in ("step_completed", "step_failed"):
            status = event.get("status")
            self._timings[key] = StepTiming(
                attempts=previous.attempts,
                started_at=previous.started_at,
                finished_at=timestamp,
                status=(
                    str(status)
                    if isinstance(status, str)
                    else "failed"
                    if event_type == "step_failed"
                    else None
                ),
            )
