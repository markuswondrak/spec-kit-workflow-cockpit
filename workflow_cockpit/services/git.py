"""Git reads: HEAD/branch/dirty detection for one project worktree."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

Runner = Callable[[Sequence[str], Path], "subprocess.CompletedProcess[str]"]


class GitError(Exception):
    """Raised for unexpected Git failures (not for a missing repository)."""


@dataclass(frozen=True)
class GitState:
    head: str | None
    branch: str | None
    dirty: bool


def _default_runner(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


class GitService:
    def __init__(self, project_root: Path, runner: Runner | None = None) -> None:
        self.project_root = Path(project_root)
        self._runner = runner or _default_runner

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return self._runner(["git", *args], self.project_root)

    def is_worktree(self) -> bool:
        result = self._git("rev-parse", "--is-inside-work-tree")
        return result.returncode == 0 and result.stdout.strip() == "true"

    def head(self) -> str | None:
        result = self._git("rev-parse", "HEAD")
        if result.returncode != 0:
            return None
        value = result.stdout.strip()
        return value or None

    def branch(self) -> str | None:
        result = self._git("rev-parse", "--abbrev-ref", "HEAD")
        if result.returncode != 0:
            return None
        value = result.stdout.strip()
        if not value or value == "HEAD":
            return None
        return value

    def is_dirty(self) -> bool:
        result = self._git("status", "--porcelain")
        if result.returncode != 0:
            return False
        return bool(result.stdout.strip())

    def state(self) -> GitState:
        return GitState(head=self.head(), branch=self.branch(), dirty=self.is_dirty())
