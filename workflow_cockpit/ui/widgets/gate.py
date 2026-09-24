"""Gate decision affordance: equal-weight buttons or one compact select.

The bar owns the presentation choice (from ``gate_affordance``) and the tracked
selection. It never submits: activating a choice posts ``ChoiceActivated`` and
the screen runs the existing confirmation flow. The selected choice is tracked
by its opaque value so it survives refreshes and mode switches.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Select

from ..view_model import GATE_BUTTON_LIMIT


class GateDecisionBar(Horizontal):
    """Render declared choices as buttons (1-3) or a select box (4+)."""

    BINDINGS = [
        Binding("left", "move_choice(-1)", show=False),
        Binding("right", "move_choice(1)", show=False),
        Binding("j", "move_choice(1)", show=False),
        Binding("k", "move_choice(-1)", show=False),
    ]

    class ChoiceActivated(Message):
        """Posted when the operator activates one declared choice."""

        def __init__(self, choice: str) -> None:
            super().__init__()
            self.choice = choice

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._options: tuple[str, ...] = ()
        self._selected: str | None = None
        self._selectable = True
        self._affordance = "none"
        self._expected_value: str | None = None
        self._choice_by_slot: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        for slot in range(GATE_BUTTON_LIMIT):
            button = Button("", id=f"gate-choice-{slot}")
            button.can_focus = False
            yield button
        yield Select((("", ""),), id="gate-select", allow_blank=False)

    # -- state ---------------------------------------------------------

    def update_options(
        self,
        options: tuple[str, ...] | list[str],
        *,
        selectable: bool = True,
        affordance: str,
    ) -> None:
        self._options = tuple(options)
        self._selectable = bool(selectable)
        self._affordance = affordance
        if self._selected not in self._options:
            self._selected = self._options[0] if self._options else None
        if affordance == "buttons":
            self._render_buttons()
        elif affordance == "select":
            self._render_select()
        else:
            self._render_none()

    def selected_option(self) -> str | None:
        return self._selected

    def select(self, choice: str | None) -> None:
        """Set the tracked selection and reflect it in the active control."""
        if choice is None:
            return
        self._selected = choice
        if self._affordance == "buttons":
            self._mark_button_selection()
        elif self._affordance == "select":
            self._set_select_value(choice)

    def action_move_choice(self, delta) -> None:
        step = int(delta)
        if self._affordance != "buttons" or not self._selectable or not self._options:
            return
        try:
            index = self._options.index(self._selected)
        except ValueError:
            index = 0
        self.select(self._options[(index + step) % len(self._options)])

    # -- rendering -----------------------------------------------------

    def _render_buttons(self) -> None:
        self._choice_by_slot = {}
        self.query_one("#gate-select", Select).display = False
        for slot in range(GATE_BUTTON_LIMIT):
            button = self.query_one(f"#gate-choice-{slot}", Button)
            if slot < len(self._options):
                choice = self._options[slot]
                self._choice_by_slot[str(button.id)] = choice
                button.label = choice
                button.display = True
                button.disabled = not self._selectable
            else:
                button.display = False
                button.disabled = True
        self.can_focus = self._selectable and bool(self._options)
        self._mark_button_selection()

    def _mark_button_selection(self) -> None:
        for slot in range(GATE_BUTTON_LIMIT):
            button = self.query_one(f"#gate-choice-{slot}", Button)
            choice = self._choice_by_slot.get(str(button.id))
            button.set_class(choice is not None and choice == self._selected, "selected")

    def _render_select(self) -> None:
        self._choice_by_slot = {}
        for slot in range(GATE_BUTTON_LIMIT):
            button = self.query_one(f"#gate-choice-{slot}", Button)
            button.display = False
            button.disabled = True
        select = self.query_one("#gate-select", Select)
        with select.prevent(Select.Changed):
            select.set_options([(choice, choice) for choice in self._options])
            if self._selected is not None:
                self._expected_value = self._selected
                select.value = self._selected
        select.disabled = not self._selectable
        select.display = True
        self.can_focus = False

    def _set_select_value(self, choice: str) -> None:
        select = self.query_one("#gate-select", Select)
        if select.value != choice:
            with select.prevent(Select.Changed):
                self._expected_value = choice
                select.value = choice

    def _render_none(self) -> None:
        self._choice_by_slot = {}
        for slot in range(GATE_BUTTON_LIMIT):
            button = self.query_one(f"#gate-choice-{slot}", Button)
            button.display = False
            button.disabled = True
        select = self.query_one("#gate-select", Select)
        select.display = False
        select.disabled = True
        self.can_focus = False

    # -- interaction ---------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        choice = self._choice_by_slot.get(str(event.button.id))
        if choice is None or not self._selectable:
            return
        event.stop()
        self.post_message(self.ChoiceActivated(choice))

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()
        if self._affordance != "select" or not self._selectable:
            return
        if event.value is Select.BLANK:
            return
        value = str(event.value)
        if value == self._expected_value or value == self._selected:
            self._expected_value = None
            return
        self.post_message(self.ChoiceActivated(value))
