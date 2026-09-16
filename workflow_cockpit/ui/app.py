"""Textual application and screen routing."""

from __future__ import annotations

from textual.app import App

from ..session.signals import SignalHandler
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
        self.signal_handler: SignalHandler | None = None

    def on_mount(self) -> None:
        # The session is created later by preflight, so the handler receives a
        # provider rather than a session value. Signals are installed once the
        # loop is running and removed on teardown.
        try:
            self.signal_handler = SignalHandler(lambda: self.session, self).register()
        except (NotImplementedError, RuntimeError, ValueError):
            self.signal_handler = None
        self.push_screen(PreflightScreen(self.preflight, self.session_factory))

    def on_unmount(self) -> None:
        if self.signal_handler is not None:
            self.signal_handler.close()
            self.signal_handler = None
