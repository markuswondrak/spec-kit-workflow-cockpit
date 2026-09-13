"""Incrementally aggregate timing data from an append-only engine log."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .graph import resolve_declared_id


@dataclass(frozen=True)
class StepTiming:
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str | None = None


class RunLogAggregator:
    """Keep bounded per-step timing aggregates while accepting partial writes."""

    def __init__(self, declared_ids: frozenset[str]) -> None:
        self._declared_ids = declared_ids
        self._signature: tuple[int, int] | None = None
        self._offset = 0
        self._partial = b""
        self._timings: dict[str, StepTiming] = {}

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

    def update(self, path: Path) -> dict[str, StepTiming]:
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
                chunk = handle.read()
        except OSError:
            return dict(self._timings)
        self._offset += len(chunk)
        data = self._partial + chunk
        lines = data.split(b"\n")
        self._partial = lines.pop()
        for line in lines:
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
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
