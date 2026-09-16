"""Immutable value objects for the Feature Files review surface at a paused gate."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureFile:
    """One file discovered under the declared feature directory."""

    path: str
    binary: bool = False
    size: int | None = None

    @property
    def label(self) -> str:
        return self.path


@dataclass(frozen=True)
class ReviewDocument:
    """One selected feature file rendered for review.

    ``text`` carries the current file content. Binary files carry only metadata;
    ``truncated`` marks a bounded preview of a large file.
    """

    path: str
    binary: bool = False
    text: str = ""
    truncated: bool = False
    limit_bytes: int | None = None
    total_bytes: int | None = None
    note: str = ""
    error: str = ""
    markdown: bool = False


@dataclass(frozen=True)
class ReviewSnapshot:
    """The current Feature Files set plus refresh status.

    A failed or in-progress refresh keeps the last completed ``files`` so the
    review surface never blanks out mid-refresh.
    """

    feature_dir: str | None = None
    files: tuple[FeatureFile, ...] = ()
    status: str = "ready"
    error: str = ""
    revision: int = 0

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def empty(self) -> bool:
        return not self.files
