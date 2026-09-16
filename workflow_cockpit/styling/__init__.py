"""Data-only styling templates: discovery, validation, and resolution."""

from __future__ import annotations

from .loader import TemplateRepository, builtin_dir
from .resolver import ResolvedStyle, resolve_style
from .tokens import (
    ACCENT_TOKENS,
    DEFAULT_ACCENTS,
    NEUTRAL_TOKENS,
    REQUIRED_TOKENS,
    StylingTemplate,
    TemplateValidationError,
    default_template,
    normalize_name,
    sanitize_display_name,
    validate_template,
)

__all__ = [
    "ACCENT_TOKENS",
    "DEFAULT_ACCENTS",
    "NEUTRAL_TOKENS",
    "REQUIRED_TOKENS",
    "ResolvedStyle",
    "StylingTemplate",
    "TemplateRepository",
    "TemplateValidationError",
    "builtin_dir",
    "default_template",
    "normalize_name",
    "resolve_style",
    "sanitize_display_name",
    "validate_template",
]
