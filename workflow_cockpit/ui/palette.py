"""Mutable render-time palette fed by the active styling template.

Consumers read ``palette.<role>`` at render time so a template installed at
startup is reflected everywhere; importing a value at module load would bind the
previous neutral value and miss the active template.
"""

from __future__ import annotations

from ..styling.tokens import ACCENT_TOKENS, StylingTemplate, default_template


class Palette:
    """The ten semantic roles plus the three accent roles, as hex strings."""

    def __init__(self) -> None:
        self.install(default_template())

    def install(self, template: StylingTemplate) -> None:
        for token, value in template.tokens.items():
            setattr(self, token, value)
        for token in ACCENT_TOKENS:
            setattr(self, token, template.accent(token))


#: Process-wide palette singleton; installed once per app at startup.
palette = Palette()
