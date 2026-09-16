"""Deterministic, data-only discovery of styling templates.

Discovery precedence (fixed and documented):

1. Built-in packaged templates in ``workflow_cockpit/styling/templates``.
2. Project-local templates in ``<project>/.specify/cockpit/templates``.

Within a directory, files are read in sorted filename order. The first
definition loaded for a normalized name wins; later duplicates are logged and
ignored. The neutral ``cockpit`` template can never be shadowed by a
project-local file, protecting the guaranteed fallback target.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .tokens import (
    StylingTemplate,
    TemplateValidationError,
    default_template,
    normalize_name,
    validate_template,
)

_LOG = logging.getLogger(__name__)

#: Packaged discovery location for the shipped neutral and agent templates.
BUILTIN_TEMPLATE_DIR = Path(__file__).with_name("templates")

#: Documented project-local discovery location (read-only for the Cockpit).
PROJECT_TEMPLATE_RELPATH = Path(".specify") / "cockpit" / "templates"

#: The neutral template name that no project-local file may replace.
RESERVED_DEFAULT_NAME = "cockpit"


def builtin_dir() -> Path:
    return BUILTIN_TEMPLATE_DIR


class TemplateRepository:
    """A loaded, indexed, and validated set of styling templates."""

    def __init__(self) -> None:
        self._by_name: dict[str, StylingTemplate] = {}
        self._index: dict[str, StylingTemplate] = {}

    @classmethod
    def load(cls, project: Path | str | None = None) -> TemplateRepository:
        repository = cls()
        repository._load_directory(BUILTIN_TEMPLATE_DIR, builtin=True)
        if project is not None:
            repository._load_directory(Path(project) / PROJECT_TEMPLATE_RELPATH, builtin=False)
        repository._ensure_default()
        return repository

    # -- queries -------------------------------------------------------

    def resolve(self, name: str | None) -> StylingTemplate | None:
        key = normalize_name(name)
        return self._index.get(key) if key else None

    def default_style(self) -> StylingTemplate:
        return self._by_name.get(RESERVED_DEFAULT_NAME, default_template())

    @property
    def templates(self) -> tuple[StylingTemplate, ...]:
        return tuple(self._by_name[key] for key in sorted(self._by_name))

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_name))

    # -- loading -------------------------------------------------------

    def _load_directory(self, directory: Path, *, builtin: bool) -> None:
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("*.json")):
            self._load_file(path, builtin=builtin)

    def _load_file(self, path: Path, *, builtin: bool) -> None:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            _LOG.warning("styling template %s is unreadable: %s", path, exc)
            return
        try:
            data = json.loads(raw)
        except (ValueError, TypeError) as exc:
            _LOG.warning("styling template %s is malformed: %s", path, exc)
            return
        try:
            template = validate_template(data)
        except TemplateValidationError as exc:
            missing = f" missing={','.join(exc.missing)}" if exc.missing else ""
            _LOG.warning("styling template %s rejected: %s%s", exc.name, exc.reason, missing)
            return
        self._register(template, path, builtin=builtin)

    def _register(self, template: StylingTemplate, path: Path, *, builtin: bool) -> None:
        key = normalize_name(template.name)
        if not key:
            return
        if key == RESERVED_DEFAULT_NAME and not builtin:
            _LOG.warning("reserved template %r in %s ignored", RESERVED_DEFAULT_NAME, path)
            return
        if key in self._by_name:
            _LOG.warning("duplicate styling template %r in %s ignored", template.name, path)
            return
        self._by_name[key] = template
        for alias_key in (key, *(normalize_name(alias) for alias in template.aliases)):
            if alias_key and alias_key not in self._index:
                self._index[alias_key] = template

    def _ensure_default(self) -> None:
        if RESERVED_DEFAULT_NAME not in self._by_name:
            _LOG.warning("built-in %r template unavailable; using synthesized neutral", RESERVED_DEFAULT_NAME)
            self._register(default_template(), BUILTIN_TEMPLATE_DIR, builtin=True)
