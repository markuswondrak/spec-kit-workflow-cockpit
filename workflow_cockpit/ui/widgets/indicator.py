"""Loading indicator whose bright dot travels right, then back left."""

from __future__ import annotations

from time import time
from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual.color import Gradient
from textual.widgets import LoadingIndicator

if TYPE_CHECKING:
    from textual.app import RenderResult


class BounceIndicator(LoadingIndicator):
    """Ping-pong variant of the stock indicator: no wrap-around jump."""

    RATE = 4.0
    """Triangle-wave units per second; one full left-to-right sweep per 1/rate * SPAN."""

    SPAN = 4.0
    """Distance the bright dot travels from the first to the last dot."""

    @classmethod
    def _blends(cls, elapsed: float) -> list[float]:
        """Dot intensities for a position that sweeps 0 -> SPAN -> 0."""
        cycle = (elapsed * cls.RATE) % (2 * cls.SPAN)
        position = cls.SPAN - abs(cycle - cls.SPAN)
        return [min(1.0, abs(position - dot) / cls.SPAN) for dot in range(5)]

    def render(self) -> RenderResult:
        if self.app.animation_level == "none":
            return Text("Loading...")

        elapsed = time() - self._start_time
        dot = "\u25cf"
        _, _, background, color = self.colors

        gradient = Gradient(
            (0.0, background.blend(color, 0.1)),
            (0.7, color),
            (1.0, color.lighten(0.1)),
        )

        dots = [
            (
                f"{dot} ",
                Style.from_color(gradient.get_color((1 - blend) ** 2).rich_color),
            )
            for blend in self._blends(elapsed)
        ]
        indicator = Text.assemble(*dots)
        indicator.rstrip()
        return indicator
