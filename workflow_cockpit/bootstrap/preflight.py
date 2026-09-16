"""Preflight validation with actionable diagnostics."""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..services.git import GitService
from .compatibility import Compatibility, CompatibilityError, CompatibilityResult
from .discovery import ProjectInfo


def _is_supported_platform(
    platform_name: str | None = None, release: str | None = None
) -> tuple[bool, str]:
    """Classify the host platform; native Windows is explicitly unsupported."""
    name = sys.platform if platform_name is None else platform_name
    kernel = platform.release() if release is None else release
    if name.startswith("linux"):
        if "microsoft" in kernel.lower():
            return True, "WSL"
        return True, "Linux"
    if name == "darwin":
        return True, "macOS"
    return False, f"{name} (use Linux, macOS, or WSL)"


@dataclass(frozen=True)
class CheckResult:
    key: str
    label: str
    ok: bool
    detail: str = ""
    repair: str = ""


@dataclass(frozen=True)
class PreflightReport:
    project: ProjectInfo
    checks: tuple[CheckResult, ...]
    compatibility: CompatibilityResult | None = None

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(check for check in self.checks if not check.ok)


@dataclass
class Preflight:
    """Validate platform, Git, project init, and executable compatibility."""

    project: ProjectInfo
    compatibility: Compatibility
    git: GitService
    explicit_executable: str | Path | None = None
    _result: CompatibilityResult | None = field(default=None, init=False)

    def run(self) -> PreflightReport:
        checks: list[CheckResult] = []
        compatible: CompatibilityResult | None = None

        supported, platform_label = _is_supported_platform()
        checks.append(
            CheckResult(
                key="platform",
                label="Platform",
                ok=supported,
                detail=platform_label,
                repair="Run on Linux, macOS, or WSL." if not supported else "",
            )
        )

        head = self.git.head()
        is_worktree = self.git.is_worktree()
        git_ok = is_worktree and bool(head)
        checks.append(
            CheckResult(
                key="git",
                label="Git worktree with a valid HEAD",
                ok=git_ok,
                detail=head[:12] if head else ("not a git worktree" if not is_worktree else "no commits"),
                repair="" if git_ok else "Initialize Git and create an initial commit.",
            )
        )

        project_ok = self.project.specify_dir.is_dir()
        checks.append(
            CheckResult(
                key="project",
                label="Spec Kit project initialized",
                ok=project_ok,
                detail=str(self.project.root),
                repair="" if project_ok else "Run 'specify init' in this project.",
            )
        )

        try:
            executable = self.compatibility.resolve_executable(self.explicit_executable)
            compatible = self.compatibility.check(executable)
            self.compatibility.probe(executable)
            checks.append(
                CheckResult(
                    key="specify",
                    label="Compatible specify executable",
                    ok=True,
                    detail=f"{compatible.executable} ({compatible.version})",
                )
            )
        except CompatibilityError as exc:
            checks.append(
                CheckResult(
                    key="specify",
                    label="Compatible specify executable",
                    ok=False,
                    detail=str(exc),
                    repair=(
                        "Install a specify version in the tested range "
                        f"{self.compatibility.tested_range}."
                    ),
                )
            )

        return PreflightReport(
            project=self.project,
            checks=tuple(checks),
            compatibility=compatible,
        )
