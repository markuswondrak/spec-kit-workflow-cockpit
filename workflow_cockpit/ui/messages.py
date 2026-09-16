"""Textual messages published across the cockpit's worker/render boundary."""

from __future__ import annotations

from textual.message import Message

from ..services.snapshot import RunSnapshot


class SnapshotPublished(Message):
    """An immutable state snapshot produced off the render path."""

    def __init__(self, snapshot: RunSnapshot | None, error: str = "") -> None:
        self.snapshot = snapshot
        self.error = error
        super().__init__()
