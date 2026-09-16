"""Install the bundled run-context skill into the project's integration.

Cockpit ships the ``cockpit-run-context`` skill inside its package. At TUI start
it copies that skill into the project-local skills directory of the integration
declared in ``.specify/integration.json`` so a user-chosen external agent can
discover it. The destination is outside ``.specify/`` and is never run state. An
already-present skill directory is left untouched and every failure is reported,
never fatal.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from ..styling.integration import read_default_integration

_LOG = logging.getLogger(__name__)

#: Name of the shipped skill, matching its package directory and front matter.
SKILL_NAME = "cockpit-run-context"

#: The single file that makes up the shipped skill.
SKILL_FILENAME = "SKILL.md"

#: Project-relative skills base per integration, plus the neutral open-standard fallback.
_INTEGRATION_SKILL_DIRS = {
    "claude": Path(".claude") / "skills",
    "claude-code": Path(".claude") / "skills",
    "github-copilot": Path(".github") / "skills",
    "copilot": Path(".github") / "skills",
    "opencode": Path(".opencode") / "skills",
}
_FALLBACK_SKILL_DIR = Path(".agents") / "skills"

#: Result actions returned by :meth:`SkillInstaller.install`.
INSTALLED = "installed"
SKIPPED = "skipped"
FAILED = "failed"


@dataclass(frozen=True)
class SkillInstall:
    """Outcome of one skill-installation attempt."""

    action: str
    relative: str = ""
    integration: str | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.action != FAILED


def _normalize_integration(integration: str | None) -> str:
    if not integration:
        return ""
    return integration.strip().lower().replace("_", "-").replace(" ", "-")


def _skill_dir_for(integration: str | None) -> Path:
    return _INTEGRATION_SKILL_DIRS.get(_normalize_integration(integration), _FALLBACK_SKILL_DIR)


def _read_source() -> str:
    source = resources.files("workflow_cockpit.skills") / SKILL_NAME / SKILL_FILENAME
    return source.read_text(encoding="utf-8")


def _write_atomic(path: Path, content: str) -> None:
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".SKILL-",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(content)
        os.replace(temp_path, path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise


def _remove_empty_dir(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


class SkillInstaller:
    """Copy the bundled ``cockpit-run-context`` skill into the integration."""

    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root)

    def install(self) -> SkillInstall:
        """Install the skill once; never raise, always report the outcome."""
        specify_dir = self.project_root / ".specify"
        if not specify_dir.is_dir():
            return SkillInstall(action=SKIPPED, reason="no initialized Spec Kit project")

        integration = read_default_integration(specify_dir).value
        relative_dir = _skill_dir_for(integration) / SKILL_NAME
        target_dir = self.project_root / relative_dir
        if target_dir.exists():
            return SkillInstall(
                action=SKIPPED,
                relative=relative_dir.as_posix(),
                integration=integration,
                reason="skill directory already present",
            )

        try:
            content = _read_source()
            target_dir.mkdir(parents=True, exist_ok=True)
            try:
                _write_atomic(target_dir / SKILL_FILENAME, content)
            except OSError:
                _remove_empty_dir(target_dir)
                raise
        except OSError as exc:
            _LOG.warning("could not install the %s skill: %s", SKILL_NAME, exc)
            return SkillInstall(
                action=FAILED,
                relative=relative_dir.as_posix(),
                integration=integration,
                reason=str(exc),
            )
        return SkillInstall(action=INSTALLED, relative=relative_dir.as_posix(), integration=integration)
