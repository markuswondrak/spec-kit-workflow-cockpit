"""Semantic token set, the ``StylingTemplate`` model, and template validation.

Templates are data only: a named set of the ten required UI_DESIGN palette roles
plus optional accent roles. This module imports no Textual so it is unit-testable
headlessly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: The ten semantic palette roles every template must define (`UI_DESIGN.md` 2).
REQUIRED_TOKENS: tuple[str, ...] = (
    "ink",
    "deck",
    "raised",
    "rail",
    "fog",
    "paper",
    "signal",
    "hold",
    "fault",
    "cold",
)

#: Optional accent roles; a template may omit them and inherit the defaults.
ACCENT_TOKENS: tuple[str, ...] = ("selection", "focus", "hover")

#: The exact neutral baseline: the Cockpit's shipped appearance before S07.
NEUTRAL_TOKENS: dict[str, str] = {
    "ink": "#101312",
    "deck": "#171C19",
    "raised": "#202821",
    "rail": "#303B34",
    "fog": "#94A399",
    "paper": "#E5E9DF",
    "signal": "#9CD6AD",
    "hold": "#E8BD79",
    "fault": "#EF9387",
    "cold": "#A1BFCE",
}

#: The three currently hardcoded non-token colors in ``styles.tcss``.
DEFAULT_ACCENTS: dict[str, str] = {
    "selection": "#2B3D32",
    "focus": "#34463D",
    "hover": "#354238",
}

#: Upper bound for a name shown in the header; longer names are middle-truncated.
DISPLAY_NAME_LIMIT = 32

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$")
_NAME_SEPARATORS = re.compile(r"[\s_\-]+")
_UNSAFE_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class TemplateValidationError(ValueError):
    """A template definition that cannot be applied as a whole."""

    def __init__(self, name: str, reason: str, missing: tuple[str, ...] = ()) -> None:
        self.name = name
        self.reason = reason
        self.missing = missing
        super().__init__(f"template {name!r} rejected: {reason}")


@dataclass(frozen=True)
class StylingTemplate:
    """An immutable, validated set of visual token values."""

    name: str
    label: str
    tokens: dict[str, str]
    aliases: tuple[str, ...] = ()
    accents: dict[str, str] = field(default_factory=dict)

    def role(self, token: str) -> str:
        return self.tokens[token]

    def accent(self, token: str) -> str:
        return self.accents.get(token, DEFAULT_ACCENTS[token])

    def all_token_values(self) -> dict[str, str]:
        values = dict(self.tokens)
        for token in ACCENT_TOKENS:
            values[token] = self.accent(token)
        return values

    def display_name(self) -> str:
        return sanitize_display_name(self.label or self.name)


def normalize_name(value: Any) -> str:
    """Case-insensitive, separator-collapsing key for name/alias matching."""
    if value is None:
        return ""
    collapsed = _NAME_SEPARATORS.sub(" ", str(value).strip().lower())
    return collapsed.strip()


def sanitize_display_name(value: Any, *, limit: int = DISPLAY_NAME_LIMIT) -> str:
    """Strip control characters, collapse whitespace, and middle-truncate."""
    if value is None:
        return ""
    cleaned = _UNSAFE_NAME_CHARS.sub(" ", str(value))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    keep = max(1, limit - 1)
    head = (keep + 1) // 2
    tail = keep - head
    suffix = cleaned[-tail:] if tail else ""
    return f"{cleaned[:head]}…{suffix}"


def validate_template(data: Any) -> StylingTemplate:
    """Return a validated :class:`StylingTemplate`.

    Rejects the whole definition (never partially applies) and reports the exact
    required tokens that are missing. Extra tokens are ignored.
    """
    if not isinstance(data, dict):
        raise TemplateValidationError("<unknown>", "definition is not a JSON object")

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise TemplateValidationError("<unnamed>", "definition has no non-empty name")
    name = name.strip()

    raw_tokens = data.get("tokens", data.get("colors"))
    if not isinstance(raw_tokens, dict):
        raise TemplateValidationError(name, "definition has no tokens object", REQUIRED_TOKENS)

    missing = tuple(token for token in REQUIRED_TOKENS if not _is_color(raw_tokens.get(token)))
    if missing:
        raise TemplateValidationError(name, f"missing or invalid tokens: {', '.join(missing)}", missing)

    tokens = {token: str(raw_tokens[token]).strip() for token in REQUIRED_TOKENS}
    accents = _parse_accents(name, data.get("accents"))
    aliases = _parse_aliases(data.get("aliases"))
    label = data.get("label")
    return StylingTemplate(
        name=name,
        label=label.strip() if isinstance(label, str) and label.strip() else name,
        tokens=tokens,
        aliases=aliases,
        accents=accents,
    )


def default_template() -> StylingTemplate:
    """The guaranteed neutral ``cockpit`` template, independent of packaged data."""
    return StylingTemplate(
        name="cockpit",
        label="Cockpit",
        tokens=dict(NEUTRAL_TOKENS),
        aliases=("cockpit", "default", "neutral"),
        accents=dict(DEFAULT_ACCENTS),
    )


def _parse_accents(name: str, raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TemplateValidationError(name, "accents must be an object")
    accents: dict[str, str] = {}
    for token in ACCENT_TOKENS:
        value = raw.get(token)
        if value is None:
            continue
        if not _is_color(value):
            raise TemplateValidationError(name, f"accent {token!r} is not a color")
        accents[token] = str(value).strip()
    return accents


def _parse_aliases(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _is_color(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX_COLOR.match(value.strip()))
