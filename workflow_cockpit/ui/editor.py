"""Launch the user's ``$EDITOR`` for one reviewed worktree file."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path


def resolve_editor_command(editor: str | None, path: Path) -> list[str] | None:
    """Split ``$EDITOR`` and append the file; ``None`` when unusable."""
    if not editor or not editor.strip():
        return None
    try:
        parts = shlex.split(editor)
    except ValueError:
        return None
    if not parts:
        return None
    return [*parts, str(path)]


def default_editor_launcher(argv: Sequence[str], cwd: Path) -> int:
    result = subprocess.run(list(argv), cwd=str(cwd), check=False)
    return result.returncode


def editor_environment() -> str | None:
    import os

    return os.environ.get("EDITOR")


EditorLauncher = Callable[[Sequence[str], Path], int]
