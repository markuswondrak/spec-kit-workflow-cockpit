"""Modal confirmation sheet used for dirty-start and abort."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from .help import HelpScreen


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("enter", "confirm", show=False, priority=True),
        Binding("question_mark", "help", "Help", show=False),
    ]

    def __init__(
        self,
        heading: str,
        effect: str,
        *,
        confirm_label: str = "Confirm",
        note: str = "",
        destructive: bool = False,
    ) -> None:
        super().__init__()
        self.heading = heading
        self.effect = effect
        self.confirm_label = confirm_label
        self.note = note
        self.destructive = destructive

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-sheet", classes="danger" if self.destructive else ""):
            yield Static("LIFECYCLE / ABORT" if self.destructive else "CONFIRM", classes="eyebrow")
            yield Static(self.heading, id="confirm-heading")
            yield Static(self.effect, id="confirm-effect", markup=False)
            yield Static(self.note, classes="muted")
            with Horizontal(classes="sheet-actions"):
                yield Button(self.confirm_label, id="confirm", variant="error" if self.destructive else "warning")
                yield Button("Go back", id="cancel")
            yield Static("enter  confirm     esc  go back", classes="muted")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())
