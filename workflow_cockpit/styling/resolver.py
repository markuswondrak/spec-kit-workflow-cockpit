"""Resolve the active styling template from override, integration, or default.

Selection precedence is: explicit launch override, then the project's
``default_integration``, then the neutral ``cockpit`` default. Every
non-resolvable input yields exactly one ``cockpit`` fallback plus a non-fatal
notice and a logged reason; resolution never raises.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .integration import read_default_integration
from .loader import TemplateRepository
from .tokens import StylingTemplate

_LOG = logging.getLogger(__name__)

SOURCE_OVERRIDE = "override"
SOURCE_INTEGRATION = "integration"
SOURCE_DEFAULT = "default"


@dataclass(frozen=True)
class ResolvedStyle:
    """The template actually applied, with its provenance and any fallback."""

    template: StylingTemplate
    source: str
    requested: str | None = None
    fallback_reason: str = ""
    notice: str = ""

    @property
    def name(self) -> str:
        return self.template.name

    @property
    def display_name(self) -> str:
        return self.template.display_name()

    @property
    def is_fallback(self) -> bool:
        return bool(self.notice)


def resolve_style(
    project: Path | str | None = None,
    override: str | None = None,
    *,
    repository: TemplateRepository | None = None,
) -> ResolvedStyle:
    repo = repository or TemplateRepository.load(project)
    default = repo.default_style()

    requested_override = override.strip() if isinstance(override, str) else ""
    if requested_override:
        template = repo.resolve(requested_override)
        if template is not None:
            return ResolvedStyle(template=template, source=SOURCE_OVERRIDE, requested=requested_override)
        return _fallback(
            default,
            requested=requested_override,
            reason=f"no template matches override {requested_override!r}",
        )

    if project is None:
        return ResolvedStyle(template=default, source=SOURCE_DEFAULT)

    descriptor = read_default_integration(Path(project) / ".specify")
    if not descriptor.declared:
        return _fallback(default, requested=None, reason=descriptor.reason)

    requested = descriptor.value
    template = repo.resolve(requested)
    if template is not None:
        return ResolvedStyle(template=template, source=SOURCE_INTEGRATION, requested=requested)
    return _fallback(default, requested=requested, reason=f"no template matches integration {requested!r}")


def _fallback(default: StylingTemplate, *, requested: str | None, reason: str) -> ResolvedStyle:
    _LOG.warning("styling fallback: %s; using %r", reason, default.name)
    line = f"{reason}; using {default.name!r}" if reason else f"using {default.name!r}"
    return ResolvedStyle(
        template=default,
        source=SOURCE_DEFAULT,
        requested=requested,
        fallback_reason=reason,
        notice=line,
    )
