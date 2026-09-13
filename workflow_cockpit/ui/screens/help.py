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
                    "j / k or arrows  Move in the Runway or review list\n",
                    "Tab  Move between Runway and Focus\n",
                    "s  Show state     g  Show paused gate     c  Show Feature Files\n",
                    "l  Cycle Engine Output at a gate (tail / split / full)\n",
                    "e  Collapse Engine Output        End  Output tail\n",
                    "f  Full file\n",
                    "/  Filter feature paths     o  Open selected file in $EDITOR\n\n",
                    ("DECIDE\n", HOLD),
                    "1..9  Select a declared gate option\n",
                    "enter  Confirm the highlighted gate option\n",
                    "esc    Go back\n",
                    "x / q  Confirm abort while a run is active\n\n",
                    ("S03 SCOPE\n", COLD),
                    "Feature Files lists the files under the declared feature directory.\n",
                    "Structured gates resume with the declared verdict_input.\n",
                    "Interactive PTY gates and the Cockpit skill arrive later.\n\n",
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
