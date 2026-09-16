"""Git reads: HEAD/branch/dirty detection for one project worktree."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

Runner = Callable[..., "subprocess.CompletedProcess[str]"]

#: Branch refresh runs off the render path, so its probe must be quick.
BRANCH_TIMEOUT_SECONDS = 2.0


class GitError(Exception):
    """Raised for unexpected Git failures (not for a missing repository)."""


@dataclass(frozen=True)
class GitState:
    head: str | None
    branch: str | None
    dirty: bool


@dataclass(frozen=True)
class BranchRead:
    """Typed, classified branch probe result.

    ``ok`` is false only for an execution failure (timeout or ``OSError``); a
    missing repository or detached HEAD is a normal ``value=None``. A caller can
    therefore keep the last good branch on ``ok=False`` without confusing it
    with a legitimate "no branch".
    """

    value: str | None
    ok: bool = True
    error: str = ""


def _default_runner(
    argv: Sequence[str], cwd: Path, *, timeout: float = 30.0
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


class GitService:
    def __init__(
        self,
        project_root: Path,
        runner: Runner | None = None,
        *,
        branch_timeout: float = BRANCH_TIMEOUT_SECONDS,
    ) -> None:
        self.project_root = Path(project_root)
        self._runner = runner or _default_runner
        self.branch_timeout = branch_timeout

    def _git(self, *args: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
        return self._runner(["git", *args], self.project_root, timeout=timeout)

    def is_worktree(self) -> bool:
        result = self._git("rev-parse", "--is-inside-work-tree")
        return result.returncode == 0 and result.stdout.strip() == "true"

    def head(self) -> str | None:
        result = self._git("rev-parse", "HEAD")
        if result.returncode != 0:
            return None
        value = result.stdout.strip()
        return value or None

    def branch_result(self) -> BranchRead:
        """Read the branch without raising; classify timeout/OSError failures."""
        try:
            result = self._git(
                "rev-parse", "--abbrev-ref", "HEAD", timeout=self.branch_timeout
            )
        except subprocess.TimeoutExpired:
            return BranchRead(
                value=None,
                ok=False,
                error="Git branch lookup timed out; showing the last known branch.",
            )
        except OSError as exc:
            return BranchRead(
                value=None,
                ok=False,
                error=f"Git branch lookup failed: {exc}",
            )
        if result.returncode != 0:
            return BranchRead(value=None)
        value = result.stdout.strip()
        if not value or value == "HEAD":
            return BranchRead(value=None)
        return BranchRead(value=value)

    def branch(self) -> str | None:
        return self.branch_result().value

    def is_dirty(self) -> bool:
        result = self._git("status", "--porcelain")
        if result.returncode != 0:
            return False
        return bool(result.stdout.strip())

    def state(self) -> GitState:
        return GitState(head=self.head(), branch=self.branch(), is_dirty=self.is_dirty())
