"""Feature Files review: list the declared feature directory and read its files."""

from __future__ import annotations

import json
from pathlib import Path

from .review import FeatureFile, ReviewDocument, ReviewSnapshot

FEATURE_JSON = Path(".specify") / "feature.json"
DEFAULT_PREVIEW_BYTES = 200_000
_BINARY_SAMPLE_BYTES = 8_000


def is_binary_bytes(data: bytes) -> bool:
    return b"\x00" in data[:_BINARY_SAMPLE_BYTES]


def resolve_feature_directory(project_root: Path) -> str | None:
    """Return the ``feature_directory`` declared in ``.specify/feature.json``.

    The value is normalized to a project-relative POSIX path. Missing,
    malformed, escaping, or non-directory values yield ``None``.
    """
    root = Path(project_root).resolve()
    try:
        data = json.loads((root / FEATURE_JSON).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    declared = data.get("feature_directory")
    if not isinstance(declared, str) or not declared.strip():
        return None
    candidate = Path(declared)
    if candidate.is_absolute():
        return None
    resolved = (root / candidate).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return None
    if not resolved.is_dir():
        return None
    return relative.as_posix() or None


class FeatureReviewService:
    """List and render the files under the declared feature directory."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)

    def refresh(self) -> ReviewSnapshot:
        feature_dir = resolve_feature_directory(self.project_root)
        if feature_dir is None:
            return ReviewSnapshot(
                status="error",
                error="No feature directory is declared in .specify/feature.json.",
            )
        base = self.project_root.resolve()
        root = (base / feature_dir).resolve()
        files: list[FeatureFile] = []
        try:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    relative = path.relative_to(base).as_posix()
                except ValueError:
                    continue
                files.append(FeatureFile(path=relative))
        except OSError as exc:
            return ReviewSnapshot(feature_dir=feature_dir, status="error", error=str(exc))
        files.sort(key=lambda item: item.path)
        return ReviewSnapshot(feature_dir=feature_dir, files=tuple(files))

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

    def document(self, path: str, *, full: bool = False) -> ReviewDocument:
        """Render one feature file as current text or binary metadata."""
        resolved = self.resolve_path(path)
        if resolved is None or not resolved.is_file():
            return ReviewDocument(path=path, error="The file is unavailable in the worktree.")
        limit = None if full else DEFAULT_PREVIEW_BYTES
        try:
            size = resolved.stat().st_size
            with resolved.open("rb") as handle:
                data = handle.read() if limit is None else handle.read(limit + 1)
        except OSError:
            return ReviewDocument(path=path, error="The file is unavailable in the worktree.")
        truncated = limit is not None and len(data) > limit
        data = data[:limit] if truncated else data
        if is_binary_bytes(data):
            return ReviewDocument(
                path=path,
                binary=True,
                total_bytes=size,
                note=f"Binary file · {size} bytes",
            )
        return ReviewDocument(
            path=path,
            text=data.decode("utf-8", errors="replace"),
            truncated=truncated,
            limit_bytes=DEFAULT_PREVIEW_BYTES if truncated else None,
            total_bytes=size,
        )
