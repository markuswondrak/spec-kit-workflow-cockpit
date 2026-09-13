"""Shared adaptive screen with the in-app resize guard."""

from __future__ import annotations

from textual import events
from textual.css.query import NoMatches
from textual.screen import Screen

MIN_WIDTH = 88
MIN_HEIGHT = 36


class AdaptiveScreen(Screen):
    """Screen that blocks interaction below the minimum terminal size."""

    def on_mount(self) -> None:
        self.apply_size(self.size.width, self.size.height)

    def on_resize(self, event: events.Resize) -> None:
        self.apply_size(event.size.width, event.size.height)

    def is_small(self) -> bool:
        return self.size.width < MIN_WIDTH or self.size.height < MIN_HEIGHT

    def apply_size(self, width: int, height: int) -> None:
        self.set_class(width < 112, "compact")
        self.set_class(height < 38, "short")
        small = width < MIN_WIDTH or height < MIN_HEIGHT
        try:
            shell = self.query_one("#shell")
        except NoMatches:
            shell = None
        try:
            guard = self.query_one("#resize-guard")
        except NoMatches:
            guard = None
        if shell is not None:
            shell.display = not small
        if guard is not None:
            guard.display = small
            guard.render_size(width, height)

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if self.is_small():
            return action == "quit"
        return True
