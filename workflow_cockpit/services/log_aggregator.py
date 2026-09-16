"""Incrementally aggregate timing data from an append-only engine log."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .graph import resolve_declared_id

#: Bytes read from the log per ``update`` so a growing file cannot stall a poll.
MAX_READ_BYTES = 256 * 1024


@dataclass(frozen=True)
class StepTiming:
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str | None = None


class RunLogAggregator:
    """Keep bounded per-step timing aggregates while accepting partial writes.

    Each incremental read is capped, and the unread offset plus the trailing
    partial record are retained so the next call resumes where the previous one
    stopped. A complete, newline-delimited malformed event increments a
    diagnostic counter but never discards prior timing data. A private lock
    covers the bounded I/O and the cache update.
    """

    def __init__(
        self, declared_ids: frozenset[str], *, max_read_bytes: int = MAX_READ_BYTES
    ) -> None:
        self._declared_ids = declared_ids
        self._max_read_bytes = max_read_bytes
        self._lock = threading.RLock()
        self._signature: tuple[int, int] | None = None
        self._offset = 0
        self._partial = b""
        self._timings: dict[str, StepTiming] = {}
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

    def update(self, path: Path) -> dict[str, StepTiming]:
        with self._lock:
            try:
                stat = path.stat()
            except OSError:
                return dict(self._timings)
            signature = (stat.st_ino, stat.st_dev)
            if self._signature != signature or stat.st_size < self._offset:
                self._reset(signature)
            try:
                with path.open("rb") as handle:
                    handle.seek(self._offset)
                    chunk = handle.read(self._max_read_bytes)
            except OSError:
                return dict(self._timings)
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
            return dict(self._timings)

    def _record(self, event: dict[str, object]) -> None:
        event_type = event.get("event")
        runtime_id = event.get("step_id")
        declared_id = resolve_declared_id(runtime_id if isinstance(runtime_id, str) else None, self._declared_ids)
        if declared_id is None:
            return
        previous = self._timings.get(declared_id, StepTiming())
        timestamp = self._timestamp(event.get("timestamp"))
        if event_type == "step_started":
            self._timings[declared_id] = StepTiming(
                attempts=previous.attempts + 1,
                started_at=timestamp,
                status="running",
            )
        elif event_type in ("step_completed", "step_failed"):
            status = event.get("status")
            self._timings[declared_id] = StepTiming(
                attempts=previous.attempts,
                started_at=previous.started_at,
                finished_at=timestamp,
                status=str(status) if isinstance(status, str) else "failed" if event_type == "step_failed" else None,
            )
