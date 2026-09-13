"""Workflow selection and in-place schema-driven configuration."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import Button, Checkbox, Input, OptionList, Select, Static
from textual.widgets.option_list import Option

from ...services.definition import InputSpec
from ...services.registry import RegistryError
from ..widgets import ResizeGuard
from .base import AdaptiveScreen
from .confirm import ConfirmScreen

FOG = "#94A399"
PAPER = "#E5E9DF"
SIGNAL = "#9CD6AD"
FAULT = "#EF9387"
COLD = "#A1BFCE"
HOLD = "#E8BD79"

LAUNCH_LOGO = r"""  ____ ___   ____ _  ______ ___ _____
 / ___/ _ \ / ___| |/ /  _ \_ _|_   _|
| |  | | | | |   | ' /| |_) | |  | |
| |__| |_| | |___| . \|  __/| |  | |
 \____\___/ \____|_|\_\_|  |___| |_|"""


class WorkflowList(OptionList):
    """Workflow chooser with terminal-native navigation."""

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
    ]


class LaunchScreen(AdaptiveScreen):
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "back", "Workflows"),
    ]

    def __init__(self, session, report=None) -> None:
        super().__init__()
        self.session = session
        self.report = report
        self.selected = 0
        self.configuring = False
        self._dirty_confirmed = False
        self._definition = None
        try:
            self._entries = session.list_workflows()
            self._registry_error = ""
        except RegistryError as exc:
            self._entries = ()
            self._registry_error = str(exc)

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            with Horizontal(id="masthead"):
                wordmark = Text.assemble((" C / ", f"bold {HOLD}"), ("WORKFLOW COCKPIT", f"bold {PAPER}"))
                yield Static(wordmark, id="wordmark")
                yield Static(id="run-status")
            yield Static(id="identity")
            with VerticalScroll(id="launch-content"):
                yield Static("W O R K F L O W   /   S T A Y   I N   C O N T R O L", id="launch-eyebrow")
                yield Static(Text(LAUNCH_LOGO, style=f"bold {PAPER}"), id="launch-logo")
                yield Static(
                    "Choose the workflow this cockpit will own.",
                    id="launch-intro",
                )
                with Vertical(id="workflow-picker"):
                    yield Static("01 / SELECT A WORKFLOW TO RUN", classes="section-label")
                    yield Static(
                        "Use the arrow keys or j/k to choose. Each workflow describes the work it performs.",
                        id="picker-help",
                    )
                    yield WorkflowList(id="workflows")
                    yield Static(id="catalog-note")
                yield Static(id="workflow-empty")
                with Vertical(id="launch-detail"):
                    yield Static("02 / CONFIGURE RUN", id="detail-label", classes="section-label")
                    yield Static(id="detail-name")
                    yield Static(id="detail-description")
                    yield Static(id="detail-flow")
                    yield Vertical(id="config-form")
                    yield Static(id="launch-state")
                    yield Static("", id="validation")
                    yield Button("START RUN  [enter]", id="start", variant="primary")
                    yield Static(
                        "Baseline commit is captured at Start. Nothing runs until you decide.",
                        id="start-note",
                    )
            yield Static(id="launch-commands")
        yield ResizeGuard(id="resize-guard")

    async def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#run-status", Static).update(Text.assemble(("[x] PROJECT READY", SIGNAL)))
        root = getattr(getattr(self.session, "project_root", None), "__str__", lambda: "")()
        self.query_one("#identity", Static).update(Text.assemble(("  ", FOG), (root, PAPER)))
        listing = self.query_one("#workflows", OptionList)
        if self._registry_error:
            self._show_empty_state(
                "NO WORKFLOWS AVAILABLE",
                self._registry_error,
                "Repair the workflow registry, then restart the cockpit.",
            )
            return
        options = []
        for index, entry in enumerate(self._entries):
            options.append(
                Option(
                    Text.assemble(
                        ("\n", FOG),
                        (f"{index + 1:02d}  ", HOLD),
                        (f"{entry.name}\n", f"bold {PAPER}"),
                        ("    ", FOG),
                        (entry.description or "No description provided.", FOG),
                        ("\n    Enter to configure\n", COLD),
                    ),
                    id=entry.id,
                )
            )
        listing.add_options(options)
        if options:
            listing.highlighted = 0
            listing.focus()
            await self.update_selection()
            self.query_one("#catalog-note", Static).update(
                Text.assemble((f"{len(options)} workflow{'s' if len(options) != 1 else ''} available", FOG))
            )
        else:
            self._show_empty_state(
                "NO WORKFLOWS AVAILABLE",
                "This project has no enabled workflows to run.",
                "Install one with:  specify workflow add <id>",
            )

    def _show_empty_state(self, heading: str, detail: str, repair: str) -> None:
        self._definition = None
        self.query_one("#workflow-picker").display = False
        self.query_one("#launch-detail").display = False
        self.query_one("#workflow-empty", Static).update(
            Text.assemble(
                (f"[!]  {heading}\n\n", f"bold {HOLD}"),
                (f"{detail}\n\n", PAPER),
                (repair, COLD),
            )
        )
        self.query_one("#workflow-empty").display = True
        self._render_commands()

    def _entry(self):
        if not self._entries:
            return None
        return self._entries[self.selected]

    async def update_selection(self) -> None:
        entry = self._entry()
        if entry is None:
            return
        try:
            self._definition = self.session.select(entry.id)
        except Exception as exc:
            self._definition = None
            self.query_one("#detail-name", Static).update(Text.assemble((entry.name, PAPER)))
            self.query_one("#detail-description", Static).update(Text.assemble((str(exc), FAULT)))
            self.query_one("#detail-flow", Static).update("")
            self.query_one("#start", Button).display = False
            return
        definition = self._definition
        self.query_one("#detail-name", Static).update(Text.assemble((definition.name, PAPER)))
        self.query_one("#detail-description", Static).update(Text.assemble((definition.description, FOG)))
        flow = " -> ".join(step.id for step in definition.steps)
        self.query_one("#detail-flow", Static).update(Text.assemble((flow, COLD)))
        self.query_one("#workflow-picker").display = not self.configuring
        self.query_one("#launch-detail").display = self.configuring
        self.query_one("#launch-content").set_class(self.configuring, "configuring")
        await self._build_form(definition.inputs)
        self._render_state()
        self._render_commands()

    def _render_state(self) -> None:
        branch = self.session.git.branch() or "unknown"
        dirty = self.session.git.is_dirty()
        detail = "dirty - confirmation required" if dirty else "clean"
        tone = HOLD if dirty else SIGNAL
        self.query_one("#launch-state", Static).update(
            Text.assemble(("  BRANCH ", FOG), (branch, PAPER), ("   /   WORKTREE ", FOG), (detail, tone))
        )

    async def _build_form(self, inputs: tuple[InputSpec, ...]) -> None:
        form = self.query_one("#config-form", Vertical)
        await form.remove_children()
        if not inputs:
            await form.mount(Static(Text.assemble(("This workflow declares no inputs.", FOG))))
            return
        widgets = []
        for spec in inputs:
            label = spec.label + (" *" if spec.required else "")
            widgets.append(Static(label, classes="field-label"))
            widget_id = f"input-{spec.name}"
            if spec.type == "boolean":
                widgets.append(Checkbox(spec.name, value=bool(spec.default), id=widget_id))
            elif spec.enum:
                choices = [(str(choice), str(choice)) for choice in spec.enum]
                initial = str(spec.default) if spec.has_default else choices[0][1]
                widgets.append(Select(choices, value=initial, allow_blank=False, id=widget_id))
            else:
                value = "" if not spec.has_default else str(spec.default)
                widgets.append(Input(value=value, id=widget_id))
        await form.mount(*widgets)

    def _collect_values(self) -> dict:
        values: dict = {}
        definition = self._definition
        if definition is None:
            return values
        form = self.query_one("#config-form", Vertical)
        for spec in definition.inputs:
            try:
                widget = form.query_one(f"#input-{spec.name}")
            except NoMatches:
                continue
            if isinstance(widget, Checkbox):
                values[spec.name] = widget.value
            elif isinstance(widget, Select):
                values[spec.name] = "" if widget.value is Select.BLANK else widget.value
            else:
                values[spec.name] = widget.value
        return values

    async def configure(self) -> None:
        if self._definition is None:
            return
        self.configuring = True
        await self.update_selection()
        self._first_field_focus()

    def _render_commands(self) -> None:
        commands = self.query_one("#launch-commands", Static)
        if self.configuring:
            commands.update(" Tab / Shift+Tab  move     Enter  activate     Esc  workflows     q  quit")
        elif self._entries and not self._registry_error:
            commands.update(" Up/Down or j/k  choose workflow     Enter  configure     q  quit")
        else:
            commands.update(" q  quit")

    def _first_field_focus(self) -> None:
        form = self.query_one("#config-form", Vertical)
        for spec in self._definition.inputs if self._definition else ():
            try:
                form.query_one(f"#input-{spec.name}").focus()
                return
            except NoMatches:
                continue
        try:
            self.query_one("#start", Button).focus()
        except NoMatches:
            pass

    def start(self) -> None:
        if self._definition is None:
            return
        values = self._collect_values()
        _resolved, errors = self.session.validate(values)
        if errors:
            self.query_one("#validation", Static).update(
                Text.assemble((errors[next(iter(errors))], FAULT))
            )
            self._first_field_focus()
            return
        self.query_one("#validation", Static).update("")
        if self.session.git.is_dirty() and not self._dirty_confirmed:
            self.app.push_screen(
                ConfirmScreen(
                    "Start on a dirty worktree?",
                    "The worktree has uncommitted changes. They are allowed and become part of "
                    "the review baseline.",
                    confirm_label="Start anyway",
                    note="Start is not blocked. One confirmation only.",
                ),
                self._after_dirty,
            )
            return
        self._do_start(values)

    def _after_dirty(self, confirmed: bool | None) -> None:
        if confirmed:
            self._dirty_confirmed = True
            self._do_start(self._collect_values())

    def _do_start(self, values: dict) -> None:
        resolved, errors = self.session.validate(values)
        if errors:
            self.query_one("#validation", Static).update(
                Text.assemble((errors[next(iter(errors))], FAULT))
            )
            return
        try:
            self.session.start(resolved)
        except Exception as exc:
            self.query_one("#validation", Static).update(Text.assemble((str(exc), FAULT)))
            return
        from .cockpit import CockpitScreen

        self.app.switch_screen(CockpitScreen(self.session))

    async def action_back(self) -> None:
        if not self.configuring:
            return
        self.configuring = False
        self.query_one("#validation", Static).update("")
        await self.update_selection()
        self.query_one("#workflows", OptionList).focus()

    def action_quit(self) -> None:
        self.app.exit()

    async def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id != "workflows":
            return
        self.selected = event.option_index
        self.configuring = False
        await self.update_selection()

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "workflows":
            await self.configure()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            self.start()
