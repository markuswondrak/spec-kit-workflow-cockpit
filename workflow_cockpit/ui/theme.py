"""Textual bridge for the resolved styling template.

Maps a :class:`~workflow_cockpit.styling.StylingTemplate` to a registered
Textual ``Theme`` whose variables drive the ``styles.tcss`` tokens, and exposes
the applied :class:`~workflow_cockpit.styling.ResolvedStyle` for header and
notice widgets. This is the only module in ``ui/`` that imports Textual theming.
"""

from __future__ import annotations

from textual.theme import Theme

from ..styling.resolver import ResolvedStyle
from ..styling.tokens import ACCENT_TOKENS, StylingTemplate, default_template
from .palette import palette

_ACTIVE = ResolvedStyle(template=default_template(), source="default")


def active_style() -> ResolvedStyle:
    """The style actually applied for this process (defaults to neutral)."""
    return _ACTIVE


def build_theme(template: StylingTemplate) -> Theme:
    tokens = template.tokens
    variables = dict(tokens)
    for token in ACCENT_TOKENS:
        variables[token] = template.accent(token)
    return Theme(
        name=f"cockpit-{template.name}",
        primary=tokens["signal"],
        secondary=tokens["cold"],
        accent=tokens["hold"],
        foreground=tokens["paper"],
        background=tokens["ink"],
        success=tokens["signal"],
        warning=tokens["hold"],
        error=tokens["fault"],
        surface=tokens["deck"],
        panel=tokens["raised"],
        dark=True,
        variables=variables,
    )


def install_style(app, resolved: ResolvedStyle) -> None:
    """Install the palette and register/activate the template's Textual theme."""
    global _ACTIVE
    _ACTIVE = resolved
    palette.install(resolved.template)
    theme = build_theme(resolved.template)
    app.register_theme(theme)
    app.theme = theme.name
