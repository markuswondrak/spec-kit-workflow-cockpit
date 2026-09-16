"""Contextual help for the implemented Cockpit controls."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ...services.context_index import CONTEXT_INDEX_RELATIVE, SKILL_NAME
from ..palette import palette

#: Platform and cleanup boundary shown in the Help overlay and asserted by tests.
RESILIENCE_GUIDANCE = (
    "PLATFORMS\n"
    "Linux, macOS, and WSL are supported. Native Windows is unsupported; use WSL.\n"
    "Below the minimum size a resize message replaces the layout without exiting.\n\n"
    "SIGNALS AND GUARANTEES\n"
    "Catchable SIGINT, SIGHUP, and SIGTERM abort and clean up the engine group without"
    " confirmation.\n"
    "There is no cleanup guarantee for SIGKILL, host loss, power loss, or interpreter"
    " failure.\n"
    "Background read failures keep the last good state and mark it STALE.\n"
)


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape,question_mark", "close", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-sheet"):
            yield Static("FIELD GUIDE", classes="eyebrow")
            yield Static("One run. Your control.", id="confirm-heading")
            yield Static(
                Text.assemble(
                    ("NAVIGATE\n", palette.hold),
                    "j / k or arrows  Move in the Runway or review list\n",
                    "Tab  Move between Runway and Focus\n",
                    "s  Show state     g  Show paused gate     c  Show Feature Files\n",
                    "l  Cycle Engine Output at a gate (tail / split / full)\n",
                    "e  Collapse Engine Output        End  Output tail\n",
                    "f  Full file\n",
                    "/  Filter feature paths     o  Open selected file in $EDITOR\n\n",
                    ("DECIDE\n", palette.hold),
                    "1..9  Select a declared gate option\n",
                    "enter  Confirm the highlighted gate option\n",
                    "esc    Go back\n",
                    "x / q  Confirm abort while a run is active\n\n",
                    ("GATES\n", palette.cold),
                    "Feature Files lists the files under the declared feature directory.\n",
                    "A confirmed gate choice is submitted once.\n",
                    "Persisted engine state is authoritative; Cockpit waits for it to advance.\n",
                    "If state does not advance the choice cannot be resent; only Abort remains.\n",
                    "A gate Cockpit cannot decide is read-only and never writes.\n\n",
                    (RESILIENCE_GUIDANCE + "\n", palette.cold),
                    ("EXTERNAL AGENT\n", palette.hold),
                    f"Invoke the {SKILL_NAME} skill in your own agent with the context path\n"
                    f"({CONTEXT_INDEX_RELATIVE.as_posix()}).\n"
                    "Cockpit alone starts, decides, and aborts the run.\n"
                    "Check live engine state before editing files; edit only at a gate.\n\n",
                    ("STYLE\n", palette.hold),
                    "The active template is chosen from .specify/integration.json and named in the header.\n",
                    "Pass --style NAME at launch to override it (for example --style claude).\n",
                    "Add a template as data in .specify/cockpit/templates/*.json; no code change needed.\n",
                    "An unknown style falls back to the neutral cockpit template with a notice.\n",
                )
            )
            yield Button("Back to cockpit  [esc]", id="close-help")

    def on_button_pressed(self) -> None:
        self.dismiss()

    def action_close(self) -> None:
        self.dismiss()
