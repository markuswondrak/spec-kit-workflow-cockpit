"""Contextual help for the implemented Cockpit controls."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

HOLD = "#E8BD79"
COLD = "#A1BFCE"


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape,question_mark", "close", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-sheet"):
            yield Static("FIELD GUIDE", classes="eyebrow")
            yield Static("One run. Your control.", id="confirm-heading")
            yield Static(
                Text.assemble(
                    ("NAVIGATE\n", HOLD),
                    "j / k or arrows  Move in the Runway\n",
                    "Tab  Move between Runway and Focus\n",
                    "s  Show state     g  Show paused gate\n",
                    "l  Expand Engine Output / return to live tail\n",
                    "e  Collapse Engine Output        End  Output tail\n\n",
                    ("ACT\n", HOLD),
                    "enter  Configure, start, or acknowledge an outcome\n",
                    "esc    Go back\n",
                    "x / q  Confirm abort while a run is active\n\n",
                    ("S02 SCOPE\n", COLD),
                    "Runway status, attempts, and per-step timing are live.\n",
                    "Gate decisions, Worktree Changes, and the Cockpit skill\n",
                    "arrive in later stories.\n\n",
                    ("EXTERNAL AGENT\n", HOLD),
                    "Cockpit alone starts, decides, and aborts the run.\n"
                    "Check live engine state before editing files.\n",
                )
            )
            yield Button("Back to cockpit  [esc]", id="close-help")

    def on_button_pressed(self) -> None:
        self.dismiss()

    def action_close(self) -> None:
        self.dismiss()
