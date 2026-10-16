"""Textual application and screen routing."""

from __future__ import annotations

import logging

from textual import events
from textual.app import App

from .. import diagnostics
from ..session.signals import SignalHandler
from ..styling.resolver import ResolvedStyle
from ..styling.tokens import default_template
from .screens.preflight import PreflightScreen
from .theme import install_style

_LOG = logging.getLogger(__name__)
#: Raw terminal input counted by the diagnostic heartbeat (never its content).
_INPUT_EVENTS = (events.Key, events.MouseEvent, events.Paste, events.AppFocus, events.AppBlur)
#: Heartbeat period; stalls are measured as gaps between ticks.
_HEARTBEAT_SECONDS = 0.25


def _window_title_sequence(title: str) -> str:
    """Return the OSC 0 sequence that sets a terminal window/tab title."""
    return f"\x1b]0;{title}\x07"


class CockpitApp(App):
    CSS_PATH = "styles.tcss"
    ENABLE_COMMAND_PALETTE = False
    TITLE = "Workflow Cockpit"

    def __init__(self, preflight, session_factory, style: ResolvedStyle | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.preflight = preflight
        self.session_factory = session_factory
        self.session = None
        self.signal_handler: SignalHandler | None = None
        self._input_monitor: diagnostics.InputMonitor | None = None
        self.style = style or ResolvedStyle(template=default_template(), source="default")
        install_style(self, self.style)

    async def on_event(self, event: events.Event) -> None:
        # Raw input reaches the app before it is forwarded to the focused widget.
        # Counting here shows whether input arrives even when widgets do not react.
        if self._input_monitor is not None and not event.is_forwarded:
            if isinstance(event, _INPUT_EVENTS):
                self._input_monitor.note_input(type(event).__name__)
            if isinstance(event, events.Paste):
                _LOG.info("paste received chars=%d", len(event.text))
        await super().on_event(event)

    def _set_window_title(self, title: str) -> None:
        # Terminal I/O is best effort: emulators may ignore OSC 0 and the driver
        # may be absent in tests, so a failure must never surface to the user.
        driver = getattr(self, "_driver", None)
        if driver is None:
            return
        try:
            driver.write(_window_title_sequence(title))
        except Exception:
            return

    def on_mount(self) -> None:
        self._set_window_title(self.TITLE)
        if diagnostics.enabled() and self._input_monitor is None:
            self._input_monitor = diagnostics.InputMonitor()
            self.set_interval(_HEARTBEAT_SECONDS, self._input_monitor.tick)
        # The session is created later by preflight, so the handler receives a
        # provider rather than a session value. Signals are installed once the
        # loop is running and removed on teardown.
        try:
            self.signal_handler = SignalHandler(lambda: self.session, self).register()
        except (NotImplementedError, RuntimeError, ValueError):
            self.signal_handler = None
        self.push_screen(PreflightScreen(self.preflight, self.session_factory))

    def on_unmount(self) -> None:
        self._set_window_title("")
        if self.signal_handler is not None:
            self.signal_handler.close()
            self.signal_handler = None
