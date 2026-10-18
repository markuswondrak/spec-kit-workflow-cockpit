"""The single install/update surface for every frontend artifact (US2).

One UI-free service installs the artifacts a frontend needs, keyed on the
project's Spec Kit integration. Each artifact declares a policy:

``user_editable``
    Installed once and then owned by the user. An existing file is never
    overwritten, whatever its content.
``managed``
    Owned by the package. It carries a version marker and is replaced atomically
    (temp file plus ``os.replace``) when the packaged version differs, so no
    reader ever observes a partially written artifact.

Targets are pluggable: a caller may pass its own mapping of integration key to
artifacts. The shipped target is the run-context skill (ADR-0008), which keeps its
per-integration directory table and its neutral open-standard fallback, so its
behavior is unchanged. The installer is never fatal: a per-artifact failure is
reported and the remaining artifacts still run.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Protocol

from ..styling.integration import read_default_integration

_LOG = logging.getLogger(__name__)

#: Artifact policies (FR-010).
USER_EDITABLE = "user_editable"
MANAGED = "managed"

#: Per-artifact outcomes (data-model.md ``IntegrationArtifact``).
INSTALLED = "installed"
UPDATED = "updated"
SKIPPED_PRESENT = "skipped_present"
SKIPPED_CURRENT = "skipped_current"
SKIPPED_UNREGISTERED = "skipped_unregistered"
FAILED = "failed"

#: Name of the shipped skill, matching its package directory and front matter.
SKILL_NAME = "cockpit-run-context"

#: The single file that makes up the shipped skill.
SKILL_FILENAME = "SKILL.md"

#: Version marker for a managed Markdown artifact.
MARKER_TEMPLATE = "<!-- workflow-cockpit-artifact: {name} {version} -->"

#: Sidecar file carrying the marker for a non-Markdown managed artifact.
SIDECAR_SUFFIX = ".workflow-cockpit-artifact"

_MARKER_RE = re.compile(
    r"<!--\s*workflow-cockpit-artifact:\s*(?P<name>\S+)\s+(?P<version>\S+)\s*-->"
)

#: Project-relative skills base per integration, plus the neutral open-standard fallback.
_INTEGRATION_SKILL_DIRS = {
    "claude": Path(".claude") / "skills",
    "claude-code": Path(".claude") / "skills",
    "github-copilot": Path(".github") / "skills",
    "copilot": Path(".github") / "skills",
    "opencode": Path(".opencode") / "skills",
}
_FALLBACK_SKILL_DIR = Path(".agents") / "skills"

_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})

#: Bounded read for a version marker.
MAX_MARKER_BYTES = 8 * 1024


class Source(Protocol):
    """An artifact body: a packaged resource or a file on disk."""

    def read(self) -> str:  # pragma: no cover - protocol
        ...


@dataclass(frozen=True)
class PackageSource:
    """An artifact shipped inside the installed package."""

    package: str
    resource: str

    def read(self) -> str:
        source = resources.files(self.package) / self.resource
        return source.read_text(encoding="utf-8")


@dataclass(frozen=True)
class FileSource:
    """An artifact read from a file on disk (used by callers and tests)."""

    path: Path | str

    def read(self) -> str:
        return Path(self.path).read_text(encoding="utf-8")


@dataclass(frozen=True)
class Artifact:
    """One installable artifact and the policy that governs it."""

    name: str
    policy: str
    source: Source
    relative_path: str
    version: str = ""

    @property
    def managed(self) -> bool:
        return self.policy == MANAGED


@dataclass(frozen=True)
class ArtifactOutcome:
    """Result of processing one artifact."""

    artifact: str
    outcome: str
    relative: str
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome != FAILED


@dataclass(frozen=True)
class InstallReport:
    """Result of one install run; never raises, always reports."""

    integration: str | None
    outcomes: tuple[ArtifactOutcome, ...] = ()
    ok: bool = True

    @property
    def failures(self) -> tuple[ArtifactOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if not outcome.ok)

    def lines(self) -> tuple[str, ...]:
        """One line per artifact: ``<outcome> <relative-path> [reason]``."""
        rendered = []
        for outcome in self.outcomes:
            line = f"{outcome.outcome} {outcome.relative}".rstrip()
            if outcome.reason:
                line = f"{line} {outcome.reason}"
            rendered.append(line)
        return tuple(rendered)


def _normalize_integration(integration: str | None) -> str:
    if not integration:
        return ""
    return integration.strip().lower().replace("_", "-").replace(" ", "-")


def _is_markdown(relative_path: str) -> bool:
    return Path(relative_path).suffix.lower() in _MARKDOWN_SUFFIXES


def _skill_source() -> PackageSource:
    return PackageSource("workflow_cockpit.skills", f"{SKILL_NAME}/{SKILL_FILENAME}")


def _skill_artifacts(base: Path) -> tuple[Artifact, ...]:
    return (
        Artifact(
            name=SKILL_NAME,
            policy=USER_EDITABLE,
            source=_skill_source(),
            relative_path=(base / SKILL_NAME / SKILL_FILENAME).as_posix(),
        ),
    )


def default_targets() -> dict[str, tuple[Artifact, ...]]:
    """The shipped targets: the run-context skill, keyed on the integration."""
    return {key: _skill_artifacts(base) for key, base in _INTEGRATION_SKILL_DIRS.items()}


def default_fallback() -> tuple[Artifact, ...]:
    """The neutral open-standard target used for an unknown integration."""
    return _skill_artifacts(_FALLBACK_SKILL_DIR)


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".artifact-",
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


def _marker(artifact: Artifact) -> str:
    return MARKER_TEMPLATE.format(name=artifact.name, version=artifact.version)


def _read_marker_text(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as handle:
            return handle.read(MAX_MARKER_BYTES)
    except (OSError, UnicodeDecodeError):
        return ""


def _installed_version(target: Path, relative_path: str) -> str | None:
    """The version marker of an installed managed artifact, or ``None``."""
    if _is_markdown(relative_path):
        match = _MARKER_RE.search(_read_marker_text(target))
        return match.group("version") if match else None
    sidecar = target.with_name(target.name + SIDECAR_SUFFIX)
    match = _MARKER_RE.search(_read_marker_text(sidecar))
    return match.group("version") if match else None


class IntegrationInstaller:
    """Install every artifact registered for one project's integration."""

    def __init__(
        self,
        project_root: Path | str,
        *,
        targets: Mapping[str, tuple[Artifact, ...]] | None = None,
        fallback: tuple[Artifact, ...] | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.targets = dict(targets) if targets is not None else default_targets()
        self.fallback = default_fallback() if fallback is None else fallback

    @property
    def specify_dir(self) -> Path:
        return self.project_root / ".specify"

    def integration(self) -> str | None:
        return read_default_integration(self.specify_dir).value

    def artifacts_for(self, integration: str | None) -> tuple[Artifact, ...]:
        """The artifacts registered for ``integration``, else the fallback."""
        key = _normalize_integration(integration)
        if key in self.targets:
            return self.targets[key]
        return self.fallback

    def install(self) -> InstallReport:
        """Process every artifact; never raise, always report (FR-013)."""
        if not self.specify_dir.is_dir():
            return InstallReport(
                integration=None,
                outcomes=(
                    ArtifactOutcome(
                        artifact="(none)",
                        outcome=SKIPPED_UNREGISTERED,
                        relative="",
                        reason="no initialized Spec Kit project",
                    ),
                ),
            )
        integration = self.integration()
        artifacts = self.artifacts_for(integration)
        if not artifacts:
            return InstallReport(
                integration=integration,
                outcomes=(
                    ArtifactOutcome(
                        artifact=integration or "(none)",
                        outcome=SKIPPED_UNREGISTERED,
                        relative="",
                        reason="no artifacts are registered for this integration",
                    ),
                ),
            )
        outcomes = [self._process(artifact) for artifact in artifacts]
        return InstallReport(integration=integration, outcomes=tuple(outcomes))

    def _process(self, artifact: Artifact) -> ArtifactOutcome:
        relative = artifact.relative_path
        target = self.project_root / relative
        try:
            if artifact.policy == USER_EDITABLE:
                return self._process_user_editable(artifact, target)
            if artifact.managed:
                return self._process_managed(artifact, target)
            return ArtifactOutcome(
                artifact=artifact.name,
                outcome=FAILED,
                relative=relative,
                reason=f"unknown artifact policy {artifact.policy!r}",
            )
        except Exception as exc:  # noqa: BLE001 - one artifact must never stop the run
            _LOG.warning("artifact %s could not be installed: %s", artifact.name, exc)
            return ArtifactOutcome(
                artifact=artifact.name,
                outcome=FAILED,
                relative=relative,
                reason=str(exc),
            )

    def _process_user_editable(self, artifact: Artifact, target: Path) -> ArtifactOutcome:
        if target.exists():
            return ArtifactOutcome(
                artifact=artifact.name,
                outcome=SKIPPED_PRESENT,
                relative=artifact.relative_path,
                reason="already present; user-editable artifacts are never overwritten",
            )
        _write_atomic(target, artifact.source.read())
        return ArtifactOutcome(
            artifact=artifact.name, outcome=INSTALLED, relative=artifact.relative_path
        )

    def _process_managed(self, artifact: Artifact, target: Path) -> ArtifactOutcome:
        if target.exists():
            installed = _installed_version(target, artifact.relative_path)
            if installed is not None and installed == artifact.version:
                return ArtifactOutcome(
                    artifact=artifact.name,
                    outcome=SKIPPED_CURRENT,
                    relative=artifact.relative_path,
                    reason=f"managed artifact is current at version {artifact.version}",
                )
            _write_managed(artifact, target)
            return ArtifactOutcome(
                artifact=artifact.name, outcome=UPDATED, relative=artifact.relative_path
            )
        _write_managed(artifact, target)
        return ArtifactOutcome(
            artifact=artifact.name, outcome=INSTALLED, relative=artifact.relative_path
        )


def _write_managed(artifact: Artifact, target: Path) -> None:
    content = artifact.source.read()
    if _is_markdown(artifact.relative_path):
        _write_atomic(target, f"{_marker(artifact)}\n{content}")
        return
    _write_atomic(target, content)
    _write_atomic(target.with_name(target.name + SIDECAR_SUFFIX), _marker(artifact) + "\n")
