"""Git reads: HEAD/branch/dirty detection and Worktree Changes review."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .review import (
    GIT_STATUS_KINDS,
    KIND_ORDER,
    ChangedFile,
    ChangeKind,
    ReviewDocument,
    ReviewSnapshot,
)

Runner = Callable[[Sequence[str], Path], "subprocess.CompletedProcess[str]"]

SPECIFY_PREFIX = ".specify"
DEFAULT_PREVIEW_BYTES = 200_000
_BINARY_SAMPLE_BYTES = 8_000


class GitError(Exception):
    """Raised for unexpected Git failures (not for a missing repository)."""


def is_specify_path(path: str) -> bool:
    """True when a project-relative path lives under the engine's ``.specify/``."""
    return path == SPECIFY_PREFIX or path.startswith(f"{SPECIFY_PREFIX}/")


def is_binary_bytes(data: bytes) -> bool:
    return b"\x00" in data[:_BINARY_SAMPLE_BYTES]


def parse_name_status(raw: str) -> list[ChangedFile]:
    """Parse ``git diff --name-status -z`` output.

    Records are NUL separated: ``<status>\\0<path>\\0`` for ordinary changes,
    and ``R100\\0<old>\\0<new>\\0`` for renames/copies. Unknown codes are
    skipped rather than crashing the review.
    """
    tokens = raw.split("\0")
    files: list[ChangedFile] = []
    index = 0
    while index < len(tokens):
        status = tokens[index].strip()
        index += 1
        if not status:
            continue
        code = status[:1]
        kind = GIT_STATUS_KINDS.get(code)
        if kind is None:
            continue
        if code in ("R", "C"):
            if index + 1 >= len(tokens):
                break
            old_path, new_path = tokens[index], tokens[index + 1]
            index += 2
            if new_path:
                files.append(ChangedFile(path=new_path, kind=kind, old_path=old_path or None))
        else:
            if index >= len(tokens):
                break
            path = tokens[index]
            index += 1
            if path:
                files.append(ChangedFile(path=path, kind=kind))
    return files


def _clean_error(result: subprocess.CompletedProcess) -> str:
    detail = (result.stderr or result.stdout or "").strip()
    return detail.splitlines()[-1] if detail else "git failed"


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

    def worktree_changes(self, baseline: str | None) -> ReviewSnapshot:
        """List baseline-to-worktree changes, excluding ``.specify/`` and ignored files."""
        if not baseline:
            return ReviewSnapshot(baseline=baseline)
        result = self._git(
            "diff", "--no-ext-diff", "--find-renames", "--name-status", "-z", baseline
        )
        if result.returncode not in (0, 1):
            return ReviewSnapshot(baseline=baseline, status="error", error=_clean_error(result))
        collected: dict[str, ChangedFile] = {}
        for changed in parse_name_status(result.stdout):
            if not is_specify_path(changed.path):
                collected[changed.path] = changed
        others = self._git("ls-files", "--others", "--exclude-standard", "-z")
        if others.returncode != 0:
            return ReviewSnapshot(baseline=baseline, status="error", error=_clean_error(others))
        for path in others.stdout.split("\0"):
            if path and not is_specify_path(path) and path not in collected:
                collected[path] = ChangedFile(path=path, kind=ChangeKind.ADDED)
        files = tuple(
            sorted(collected.values(), key=lambda item: (KIND_ORDER.get(item.kind, 9), item.path))
        )
        return ReviewSnapshot(baseline=baseline, files=files)

    def resolve_path(self, path: str) -> Path | None:
        """Resolve a project-relative path that stays inside the project root."""
        if not path or "\x00" in path or Path(path).is_absolute():
            return None
        root = self.project_root.resolve()
        candidate = (root / path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate

    def document(
        self,
        changed: ChangedFile | str,
        view: str = "diff",
        *,
        full: bool = False,
        baseline: str | None = None,
    ) -> ReviewDocument:
        """Render one change as a unified diff or rendered/current content."""
        if isinstance(changed, str):
            changed = ChangedFile(path=changed, kind=ChangeKind.MODIFIED)
        path = changed.path
        if not path or is_specify_path(path):
            return ReviewDocument(path=path, view=view, kind=changed.kind, error="This path is not reviewable.")
        limit = None if full else DEFAULT_PREVIEW_BYTES
        data, source_truncated, source_size = self._source_bytes(changed, baseline, limit)
        if data is None:
            return ReviewDocument(
                path=path, view=view, kind=changed.kind, error="The file is unavailable in the worktree."
            )
        if is_binary_bytes(data):
            return ReviewDocument(
                path=path,
                view=view,
                kind=changed.kind,
                binary=True,
                total_bytes=source_size,
                note=f"Binary file · {changed.kind.value} · {source_size} bytes",
            )
        if view == "diff":
            text, truncated = self._diff_text(changed, baseline, limit)
            if text is None:
                text = synthesize_added_diff(path, data)
                truncated = source_truncated
        elif view == "rendered":
            text = data.decode("utf-8", errors="replace")
            truncated = source_truncated
        else:
            return ReviewDocument(path=path, view=view, kind=changed.kind, error=f"Unknown view {view!r}.")
        return ReviewDocument(
            path=path,
            view=view,
            kind=changed.kind,
            text=text,
            truncated=truncated,
            limit_bytes=DEFAULT_PREVIEW_BYTES if truncated else None,
            total_bytes=source_size if view == "rendered" else None,
        )

    def _source_bytes(
        self, changed: ChangedFile, baseline: str | None, limit: int | None
    ) -> tuple[bytes | None, bool, int | None]:
        if changed.kind is ChangeKind.DELETED:
            return self._show_blob(baseline, changed.path, limit)
        path = self.resolve_path(changed.path)
        if path is None or not path.is_file():
            return None, False, None
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                data = handle.read() if limit is None else handle.read(limit + 1)
        except OSError:
            return None, False, None
        truncated = limit is not None and len(data) > limit
        return data[:limit] if truncated else data, truncated, size

    def _diff_text(
        self, changed: ChangedFile, baseline: str | None, limit: int | None
    ) -> tuple[str | None, bool]:
        if not baseline:
            return None, False
        args = ["diff", "--no-ext-diff", "--find-renames", "--no-color", baseline, "--", changed.path]
        if limit is None:
            result = self._git(*args)
            if result.returncode not in (0, 1) or (not result.stdout and changed.kind is ChangeKind.ADDED):
                return None, False
            return result.stdout, False
        output, truncated, code = self._limited_git_output(args, limit)
        if code not in (0, 1) or (not output and changed.kind is ChangeKind.ADDED):
            return None, False
        return output.decode("utf-8", errors="replace"), truncated

    def _show_blob(
        self, baseline: str | None, path: str, limit: int | None
    ) -> tuple[bytes | None, bool, int | None]:
        if not baseline:
            return None, False, None
        size = self._blob_size(baseline, path)
        if size is None:
            return None, False, None
        args = ["show", f"{baseline}:{path}"]
        try:
            if limit is None:
                result = subprocess.run(
                    ["git", *args], cwd=str(self.project_root), capture_output=True, check=False, timeout=30
                )
                return (result.stdout, False, size) if result.returncode == 0 else (None, False, None)
            output, truncated, code = self._limited_git_output(args, limit)
        except (OSError, subprocess.SubprocessError):
            return None, False, None
        return (output, truncated, size) if code == 0 else (None, False, None)

    def _blob_size(self, baseline: str, path: str) -> int | None:
        result = self._git("cat-file", "-s", f"{baseline}:{path}")
        if result.returncode != 0:
            return None
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None

    def _limited_git_output(self, args: Sequence[str], limit: int) -> tuple[bytes, bool, int]:
        """Read at most ``limit`` bytes from a Git child before stopping it."""
        process = subprocess.Popen(
            ["git", *args],
            cwd=str(self.project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert process.stdout is not None
        with process.stdout:
            output = process.stdout.read(limit + 1)
        truncated = len(output) > limit
        if truncated:
            process.kill()
        process.wait(timeout=30)
        return output[:limit], truncated, 0 if truncated else process.returncode


def truncate_utf8(text: str, limit: int) -> str:
    """Truncate to at most ``limit`` UTF-8 bytes without splitting a character."""
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", errors="ignore")


def synthesize_added_diff(path: str, data: bytes) -> str:
    """Build a unified diff for an untracked file that ``git diff`` omits."""
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    body = [f"+{line}" for line in lines]
    header = [
        f"diff --git a/{path} b/{path}",
        "new file mode 100644",
        "--- /dev/null",
        f"+++ b/{path}",
        f"@@ -0,0 +1,{len(lines)} @@",
    ]
    return "\n".join([*header, *body]) + "\n"
