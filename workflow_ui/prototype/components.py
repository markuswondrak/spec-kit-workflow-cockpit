"""Small visual building blocks shared by the prototype screens."""

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, OptionList, Static

INK = "#101312"
DECK = "#171C19"
RAIL = "#303B34"
FOG = "#94A399"
PAPER = "#E5E9DF"
SIGNAL = "#9CD6AD"
HOLD = "#E8BD79"
FAULT = "#EF9387"
COLD = "#A1BFCE"

STATUS = {
    "pending": ("[ ]", FOG), "running": ("[>]", SIGNAL),
    "gate": ("[!]", HOLD), "done": ("[x]", SIGNAL),
    "failed": ("[X]", FAULT), "aborted": ("[/]", FAULT),
}


def text(*parts: str | tuple) -> Text:
    return Text.assemble(*parts)


def truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    left = (width - 3) // 2
    return value[:left] + "..." + value[-(width - 3 - left):]


class NavList(OptionList):
    BINDINGS = [Binding("j", "cursor_down", show=False),
                Binding("k", "cursor_up", show=False)]


class AdaptiveScreen(Screen):
    """The resize guard blocks interaction, not just the visible content."""

    def on_resize(self, event: events.Resize) -> None:
        self.apply_size(event.size.width, event.size.height)

    def apply_size(self, width: int, height: int) -> None:
        self.set_class(width < 112, "compact")
        self.set_class(height < 38, "short")
        small = width < 88 or height < 36
        self.query_one("#shell").disabled = small
        self.query_one("#shell").display = not small
        guard = self.query_one("#resize-guard", Static)
        guard.display = small
        guard.update(text(("MORE ROOM TO WORK\n\n", f"bold {HOLD}"),
                          (f"Terminal  {width} x {height}\n", PAPER),
                          ("Required  88 x 36\n\n", FOG),
                          ("Resize to continue. Your place is preserved.\n[q] exit", PAPER)))

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if self.size.width < 88 or self.size.height < 36:
            return action == "quit"
        return True


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", show=False),
                Binding("enter", "confirm", show=False, priority=True)]

    def __init__(self, choice: str, effect: str, destructive: bool = False) -> None:
        super().__init__()
        self.choice, self.effect, self.destructive = choice, effect, destructive

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-sheet", classes="danger" if self.destructive else ""):
            yield Static("LIFECYCLE / ABORT" if self.destructive else "GATE / CONFIRM DECISION", classes="eyebrow")
            yield Static("Abort this run?" if self.destructive else f'Submit "{self.choice}"?', id="confirm-heading")
            yield Static(self.effect, id="confirm-effect", markup=False)
            yield Static("Worktree changes are preserved." if self.destructive else
                         "The declared workflow choice will be sent once.", classes="muted")
            with Horizontal(classes="sheet-actions"):
                yield Button("Abort run" if self.destructive else "Confirm decision", id="confirm", variant="error" if self.destructive else "warning")
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


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape,question_mark", "close", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-sheet"):
            yield Static("FIELD GUIDE", classes="eyebrow")
            yield Static("One run. Your control.", id="confirm-heading")
            yield Static(text(
                ("NAVIGATE\n", HOLD),
                "Tab / Shift+Tab  Move between controls\n",
                "j / k or arrows  Move in workflow and file lists\n",
                "s  Overview      c  Changes       g  Gate\n\n",
                ("INSPECT\n", HOLD),
                "d  Diff          r  Read file     /  Filter paths\n",
                "l  Expand output / return to tail\n",
                "e  Collapse output               End  Output tail\n\n",
                ("ACT\n", HOLD),
                "1 / 2 / 3  Gate choice, always confirmed\n",
                "x / q      Confirm abort while active\n\n",
                ("DESIGN PREVIEW ONLY\n", COLD),
                "F2  Running   F3  Gate   F4  Complete   F5  Failed\n",
                "These shortcuts load fixtures, not engine actions.\n",
                "No commands run. Editor access is simulated.\n\n",
                ("EXTERNAL AGENT\n", HOLD),
                "Use the Cockpit skill with the displayed context path.\n",
                "Check live state first; edit only while paused.\n",
                "Cockpit alone controls the workflow lifecycle."))
            yield Button("Back to cockpit  [esc]", id="close-help")

    def on_button_pressed(self) -> None:
        self.dismiss()

    def action_close(self) -> None:
        self.dismiss()
