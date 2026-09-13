"""Locate the nearest Spec Kit project root (or validate an explicit path)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ProjectDiscoveryError(Exception):
    """Raised when no initialized Spec Kit project can be located."""


@dataclass(frozen=True)
class ProjectInfo:
    """A validated Spec Kit project root."""

    root: Path
    specify_dir: Path

    @property
    def workflows_dir(self) -> Path:
        return self.specify_dir / "workflows"

    @property
    def runs_dir(self) -> Path:
        return self.workflows_dir / "runs"


class ProjectDiscovery:
    """Walk upward for ``.specify/`` or validate an explicit project path."""

    def __init__(self, start: str | Path | None = None) -> None:
        self.start = Path(start if start is not None else os.getcwd()).expanduser()

    def discover(self, explicit: str | Path | None = None) -> ProjectInfo:
        if explicit is not None:
            root = Path(explicit).expanduser()
            if not root.exists():
                raise ProjectDiscoveryError(f"Project path does not exist: {root}")
            if not root.is_dir():
                raise ProjectDiscoveryError(f"Project path is not a directory: {root}")
            return self._validate(root)

        current = self.start if self.start.is_dir() else self.start.parent
        for candidate in (current, *current.parents):
            if (candidate / ".specify").is_dir():
                return self._validate(candidate)
        raise ProjectDiscoveryError(
            "No initialized Spec Kit project found. Run this inside a project with a "
            "'.specify/' directory, or pass --project PATH."
        )

    @staticmethod
    def _validate(root: Path) -> ProjectInfo:
        canonical = root.resolve()
        specify_dir = canonical / ".specify"
        if not specify_dir.is_dir():
            raise ProjectDiscoveryError(
                f"{canonical} is not an initialized Spec Kit project: '.specify/' is missing."
            )
        return ProjectInfo(root=canonical, specify_dir=specify_dir)
