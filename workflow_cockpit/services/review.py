"""Immutable value objects for Worktree Changes review at a paused gate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ChangeKind(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    CONFLICTED = "conflicted"

    @property
    def marker(self) -> str:
        return _KIND_MARKERS[self]


_KIND_MARKERS: dict[ChangeKind, str] = {
    ChangeKind.ADDED: "+",
    ChangeKind.MODIFIED: "M",
    ChangeKind.DELETED: "-",
    ChangeKind.RENAMED: "R",
    ChangeKind.CONFLICTED: "!",
}

#: Presentation order: conflicts, modified, added, renamed, deleted.
KIND_ORDER: dict[ChangeKind, int] = {
    ChangeKind.CONFLICTED: 0,
    ChangeKind.MODIFIED: 1,
    ChangeKind.ADDED: 2,
    ChangeKind.RENAMED: 3,
    ChangeKind.DELETED: 4,
}

#: Git ``--name-status`` codes mapped to the presented change kind.
GIT_STATUS_KINDS: dict[str, ChangeKind] = {
    "A": ChangeKind.ADDED,
    "M": ChangeKind.MODIFIED,
    "D": ChangeKind.DELETED,
    "R": ChangeKind.RENAMED,
    "C": ChangeKind.ADDED,
    "U": ChangeKind.CONFLICTED,
    "T": ChangeKind.MODIFIED,
}


@dataclass(frozen=True)
class ChangedFile:
    path: str
    kind: ChangeKind
    old_path: str | None = None
    binary: bool = False

    @property
    def label(self) -> str:
        if self.kind is ChangeKind.RENAMED and self.old_path:
            return f"{self.old_path} -> {self.path}"
        return self.path


@dataclass(frozen=True)
class ReviewDocument:
    """One selected file rendered for review.

    ``text`` carries the unified diff or rendered content. Binary files carry
    only metadata; ``truncated`` marks a bounded preview of a large file.
    """

    path: str
    view: str
    kind: ChangeKind
    binary: bool = False
    text: str = ""
    truncated: bool = False
    limit_bytes: int | None = None
    total_bytes: int | None = None
    note: str = ""
    error: str = ""


@dataclass(frozen=True)
class ReviewSnapshot:
    """The current Worktree Changes set plus refresh status.

    A failed or in-progress refresh keeps the last completed ``files`` so the
    review surface never blanks out mid-refresh.
    """

    baseline: str | None = None
    files: tuple[ChangedFile, ...] = ()
    status: str = "ready"
    error: str = ""
    revision: int = 0

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def empty(self) -> bool:
        return not self.files
