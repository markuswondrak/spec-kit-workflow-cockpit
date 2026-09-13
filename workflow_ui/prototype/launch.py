"""Workflow selection and configuration use the same editorial frame as review."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, Input, Select, Static
from textual.widgets.option_list import Option

import mock_data as data
from components import AdaptiveScreen, COLD, FOG, HOLD, PAPER, SIGNAL, NavList, text


LAUNCH_LOGO = r"""  ____ ___   ____ _  ______ ___ _____
 / ___/ _ \ / ___| |/ /  _ \_ _|_   _|
| |  | | | | |   | ' /| |_) | |  | |
| |__| |_| | |___| . \|  __/| |  | |
 \____\___/ \____|_|\_\_|  |___| |_|"""


class LaunchScreen(AdaptiveScreen):
    BINDINGS = [Binding("q", "quit", "Quit"),
                Binding("escape", "back", "Workflows")]

    def __init__(self) -> None:
        super().__init__()
        self.selected = 0
        self.configuring = False

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            with Horizontal(id="masthead"):
                yield Static(text((" C / ", f"bold {HOLD}"), ("WORKFLOW COCKPIT", f"bold {PAPER}")), id="wordmark")
                yield Static(text(("[x] PROJECT READY", SIGNAL)), id="run-status")
            yield Static("  " + data.PROJECT_PATH, id="identity")
            with VerticalScroll(id="launch-content"):
                yield Static("W O R K F L O W   /   STAY IN CONTROL", id="launch-eyebrow")
                yield Static(text((LAUNCH_LOGO, f"bold {PAPER}")), id="launch-logo")
                yield Static("One workflow. One worktree. Every decision in context.", id="launch-intro")
                with Horizontal(id="launch-columns"):
                    with Vertical(id="catalog"):
                        yield Static("01 / SELECT WORKFLOW", classes="section-label")
                        yield NavList(*[Option(text((f"0{i + 1}  ", FOG), (wf["name"], PAPER),
                                                    (f"\n    {len(wf['nodes'])} steps / {wf['gates']} gates\n", FOG)), id=str(i))
                                        for i, wf in enumerate(data.WORKFLOWS)], id="workflows")
                        yield Static("Installed in this project.\nNo catalog or history to manage.", classes="muted", id="catalog-note")
                    with Vertical(id="launch-detail"):
                        yield Static("02 / WORKFLOW BRIEF", id="detail-label", classes="section-label")
                        yield Static(id="detail-name")
                        yield Static(id="detail-description")
                        yield Static(id="detail-flow")
                        with Vertical(id="config-form"):
                            yield Static(id="input-label", classes="field-label")
                            yield Input(id="description")
                            yield Static("Test profile", classes="field-label")
                            yield Select([("Standard", "standard"), ("Extended", "extended")], value="standard", allow_blank=False, id="profile")
                            yield Checkbox("Publish branch", value=True, id="publish")
                            yield Static("", id="validation")
                        yield Static(text(("BRANCH  ", FOG), ("main", PAPER), (" / WORKTREE ", FOG), ("[x] clean", SIGNAL)), id="launch-state")
                        yield Button("Configure workflow  [enter]", id="configure", variant="primary")
                        yield Button("Start run", id="start", variant="primary")
                        yield Static("Baseline captured at start. Nothing runs until you decide.", id="start-note")
            yield Static(" Tab  focus     j/k  select     enter  configure     q  quit", id="launch-commands")
            yield Static("DESIGN PREVIEW   /   Fixture data only. No commands, files or engine processes.", id="preview-rail")
        yield Static(id="resize-guard")

    def on_mount(self) -> None:
        self.query_one("#workflows", NavList).highlighted = 0
        self.update_selection()
        self.query_one("#workflows").focus()
        self.apply_size(self.size.width, self.size.height)

    def update_selection(self) -> None:
        wf = data.WORKFLOWS[self.selected]
        self.query_one("#detail-name", Static).update(wf["name"])
        self.query_one("#detail-description", Static).update(wf["description"])
        self.query_one("#detail-flow", Static).update(text((" -> ".join(wf["nodes"]), COLD)))
        self.query_one("#input-label", Static).update(wf["input"] + " *")
        self.query_one("#description", Input).value = wf["value"]
        self.query_one("#config-form").display = self.configuring
        self.query_one("#start").display = self.configuring
        self.query_one("#configure").display = not self.configuring
        self.query_one("#detail-flow").display = not self.configuring
        self.query_one("#detail-label", Static).update("02 / CONFIGURE RUN" if self.configuring else "02 / WORKFLOW BRIEF")
        self.query_one("#launch-content").set_class(self.configuring, "configuring")

    def on_option_list_option_highlighted(self, event: NavList.OptionHighlighted) -> None:
        if event.option_list.id == "workflows":
            self.selected = int(event.option.id)
            self.configuring = False
            self.update_selection()

    def on_option_list_option_selected(self, event: NavList.OptionSelected) -> None:
        if event.option_list.id == "workflows":
            self.configure()

    def configure(self) -> None:
        self.configuring = True
        self.update_selection()
        self.query_one("#description").focus()

    def start(self) -> None:
        if not self.query_one("#description", Input).value.strip():
            self.query_one("#validation", Static).update("Enter a value before starting the run.")
            self.query_one("#description").focus()
            return
        from app import CockpitScreen
        self.app.switch_screen(CockpitScreen(data.WORKFLOWS[self.selected], scene="running"))

    def on_input_submitted(self) -> None:
        self.query_one("#start").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "configure":
            self.configure()
        elif event.button.id == "start":
            self.start()

    def action_back(self) -> None:
        self.configuring = False
        self.update_selection()
        self.query_one("#workflows").focus()

    def action_quit(self) -> None:
        self.app.exit()
