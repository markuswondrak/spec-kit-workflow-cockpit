"""Blocking sheet shown while a confirmed Abort waits for the process group."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from ..widgets import BounceIndicator


class AbortingScreen(ModalScreen[None]):
    """Non-dismissable sheet shown until the engine is fully reaped."""

    def compose(self) -> ComposeResult:
        with Vertical(id="abort-sheet"):
            yield Static("LIFECYCLE / ABORT", classes="eyebrow")
            yield Static("Aborting run...", id="abort-heading")
            yield BounceIndicator(id="abort-activity")
            yield Static("Interrupting the engine process group. This cannot resume.", classes="muted")
