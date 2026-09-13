"""Textual application and screen routing."""

from __future__ import annotations

from textual.app import App

from .screens.preflight import PreflightScreen


class CockpitApp(App):
    CSS_PATH = "styles.tcss"
    ENABLE_COMMAND_PALETTE = False
    TITLE = "Workflow Cockpit"

    def __init__(self, preflight, session_factory, **kwargs) -> None:
        super().__init__(**kwargs)
        self.preflight = preflight
        self.session_factory = session_factory
        self.session = None

    def on_mount(self) -> None:
        self.push_screen(PreflightScreen(self.preflight, self.session_factory))
