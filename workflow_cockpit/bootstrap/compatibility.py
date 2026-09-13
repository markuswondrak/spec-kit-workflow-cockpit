"""Resolve one ``specify`` executable and enforce the tested compatibility range."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

SUPPORTED_RANGE = ">=1.0,<2.0"
SPECIFY_ENV_VAR = "WORKFLOW_COCKPIT_SPECIFY"
REQUIRED_SUBCOMMANDS = ("run", "resume", "status", "list")
REQUIRED_RUN_OPTIONS = ("--input", "--json")
_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?(?:[.\-+][0-9A-Za-z][0-9A-Za-z.\-+]*)?)")


class CompatibilityError(Exception):
    """Raised when no compatible ``specify`` executable can be used."""


@dataclass(frozen=True)
class CompatibilityResult:
    executable: Path
    version: Version
    raw: str
    prerelease: bool
    tested_range: str


Runner = Callable[[Sequence[str], Path | None], "subprocess.CompletedProcess[str]"]


def _default_runner(argv: Sequence[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def parse_version(raw: str) -> Version | None:
    """Extract the first PEP 440-looking version token from ``raw``."""
    match = _VERSION_RE.search(raw or "")
    if not match:
        return None
    try:
        return Version(match.group(1))
    except InvalidVersion:
        return None


def in_supported_range(version: Version, specifier: SpecifierSet) -> bool:
    """Return whether ``version`` is in range, accepting prereleases in range.

    Nightly/dev builds of a supported release (for example ``1.0.6.dev0``) are
    accepted because their release segment is inside the bounded range; a
    prerelease of an out-of-range release is refused.
    """
    if version in specifier:
        return True
    if version.is_prerelease:
        base = Version(".".join(str(part) for part in version.release))
        return base in specifier
    return False


class Compatibility:
    """Resolve and retain one executable for preflight and every child."""

    def __init__(
        self,
        specifier: str = SUPPORTED_RANGE,
        runner: Runner | None = None,
    ) -> None:
        self.specifier = SpecifierSet(specifier)
        self.tested_range = specifier
        self._runner = runner or _default_runner

    def resolve_executable(self, explicit: str | Path | None = None) -> Path:
        """Resolve the executable to use: explicit, environment, then PATH."""
        candidate = explicit or os.environ.get(SPECIFY_ENV_VAR)
        if candidate:
            path = Path(candidate).expanduser()
            if not path.exists():
                raise CompatibilityError(f"specify executable not found: {path}")
            if path.is_dir() or not os.access(path, os.X_OK):
                raise CompatibilityError(f"path is not an executable file: {path}")
            return path.resolve()
        found = shutil.which("specify")
        if not found:
            raise CompatibilityError(
                "No 'specify' executable found on PATH. Set "
                f"{SPECIFY_ENV_VAR} or install Spec Kit."
            )
        return Path(found).resolve()

    def check(self, executable: Path) -> CompatibilityResult:
        """Read ``specify --version`` and verify the tested range."""
        result = self._runner([str(executable), "--version"], None)
        raw = (result.stdout or "").strip() or (result.stderr or "").strip()
        if result.returncode != 0:
            raise CompatibilityError(f"'{executable} --version' failed: {raw}")
        version = parse_version(raw)
        if version is None:
            raise CompatibilityError(f"Could not parse specify version from: {raw!r}")
        if not in_supported_range(version, self.specifier):
            raise CompatibilityError(
                f"specify {version} is outside the tested range {self.tested_range}. "
                "Install a compatible version before running the Cockpit."
            )
        return CompatibilityResult(
            executable=executable,
            version=version,
            raw=raw,
            prerelease=version.is_prerelease,
            tested_range=self.tested_range,
        )

    def probe(self, executable: Path) -> None:
        """Run non-mutating capability probes required by S01."""
        help_result = self._runner([str(executable), "workflow", "--help"], None)
        if help_result.returncode != 0:
            raise CompatibilityError(
                f"'{executable} workflow --help' failed; the workflow engine is unavailable."
            )
        help_text = f"{help_result.stdout}\n{help_result.stderr}"
        missing = [name for name in REQUIRED_SUBCOMMANDS if name not in help_text]
        if missing:
            raise CompatibilityError(
                "specify workflow is missing required command(s): " + ", ".join(missing)
            )
        run_result = self._runner([str(executable), "workflow", "run", "--help"], None)
        if run_result.returncode != 0:
            raise CompatibilityError(f"'{executable} workflow run --help' failed.")
        run_text = f"{run_result.stdout}\n{run_result.stderr}"
        missing_options = [name for name in REQUIRED_RUN_OPTIONS if name not in run_text]
        if missing_options:
            raise CompatibilityError(
                "specify workflow run is missing required option(s): "
                + ", ".join(missing_options)
            )

    def resolve_and_check(self, explicit: str | Path | None = None) -> CompatibilityResult:
        executable = self.resolve_executable(explicit)
        result = self.check(executable)
        self.probe(executable)
        return result
