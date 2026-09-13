"""Keyboard-accessible evidence browser, backed only by fixture content."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Markdown, Static
from textual.widgets.option_list import Option

import mock_data as data
from components import COLD, FAULT, FOG, HOLD, PAPER, SIGNAL, NavList, text, truncate


class ReviewPane(Vertical):
    BINDINGS = [Binding("d", "content('diff')", show=False),
                Binding("r", "content('rendered')", show=False),
                Binding("slash", "filter", show=False),
                Binding("escape", "clear_filter", show=False),
                Binding("o", "editor", show=False)]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.selected = 2
        self.content_mode = "rendered"
        self.paused = True

    def compose(self) -> ComposeResult:
        with Horizontal(id="review-heading"):
            yield Static(text(("WORKTREE CHANGES", FOG), (" / 5 files", PAPER)), id="changes-label")
            yield Static(text(("+113", SIGNAL), (" / -53", FAULT), (f" / vs {data.BASE}", FOG)), id="change-stats")
        with Horizontal(id="evidence"):
            with Vertical(id="file-index"):
                yield Input(placeholder="Filter paths...", id="file-filter")
                yield NavList(id="files")
                yield Static("/ filter   enter inspect", id="file-hint")
            with Vertical(id="document"):
                yield Static(id="document-path", markup=False)
                with Horizontal(id="document-tools"):
                    yield Button("d  Diff", id="show-diff", classes="content-tab")
                    yield Button("r  Read", id="show-rendered", classes="content-tab")
                    yield Static(id="file-meta")
                with VerticalScroll(id="document-scroll"):
                    yield Static(id="diff", markup=False)
                    yield Markdown(id="rendered")
                yield Static(id="document-note")

    def on_mount(self) -> None:
        self.query_one("#file-filter").display = False
        self.fill_files()
        self.show_file()

    def fill_files(self, query: str = "") -> None:
        listing = self.query_one("#files", NavList)
        options = []
        for i, file in enumerate(data.FILES):
            if query.lower() not in file["path"].lower():
                continue
            color = {"+": SIGNAL, "M": HOLD, "-": FAULT, "R": COLD}[file["status"]]
            name = file["path"].rsplit("/", 1)[-1]
            parent = file["path"].rsplit("/", 1)[0] if "/" in file["path"] else "project root"
            options.append(Option(text((file["status"] + " ", color), (truncate(name, 21), PAPER),
                                       ("\n  " + truncate(parent, 21) + "\n", FOG)), id=str(i)))
        listing.clear_options().add_options(options)
        matches = [int(option.id) for option in options]
        if matches:
            self.selected = self.selected if self.selected in matches else matches[0]
            listing.highlighted = matches.index(self.selected)
        else:
            listing.add_option(Option("No matching paths", disabled=True))
        self.query_one("#document").display = bool(matches)

    def on_option_list_option_highlighted(self, event: NavList.OptionHighlighted) -> None:
        if event.option_list.id == "files" and event.option.id is not None:
            index = int(event.option.id)
            changed = index != self.selected
            self.selected = index
            if changed:
                self.content_mode = "rendered" if data.FILES[index]["status"] == "+" else "diff"
            self.show_file()
            event.stop()

    def on_option_list_option_selected(self, event: NavList.OptionSelected) -> None:
        if event.option_list.id == "files":
            self.query_one("#document-scroll").focus()
            event.stop()

    def show_file(self) -> None:
        file = data.FILES[self.selected]
        self.query_one("#document-path", Static).update(file["path"])
        self.query_one("#file-meta", Static).update(text((f"+{file['added']}", SIGNAL), (f" -{file['removed']}", FAULT)))
        diff = text()
        for kind, line in file["diff"]:
            color = {"hunk": COLD, "add": SIGNAL, "del": FAULT, "ctx": FOG}[kind]
            diff.append(line + "\n", style=color)
        self.query_one("#diff", Static).update(diff)
        self.query_one("#rendered", Markdown).update(file["content"])
        self.query_one("#diff").display = self.content_mode == "diff"
        self.query_one("#rendered").display = self.content_mode == "rendered"
        self.query_one("#show-diff").set_class(self.content_mode == "diff", "selected-content")
        self.query_one("#show-rendered").set_class(self.content_mode == "rendered", "selected-content")
        note = "DELETED / prior content; editor unavailable" if file["status"] == "-" else "RENAMED / from " + file["previous"] if file["status"] == "R" else "FIXTURE EXCERPT / scroll to inspect"
        self.query_one("#document-note", Static).update(note)
        self.query_one("#document-scroll").scroll_home(animate=False)

    def action_content(self, mode: str) -> None:
        self.content_mode = mode
        self.show_file()

    def action_filter(self) -> None:
        field = self.query_one("#file-filter", Input)
        field.display = True
        field.focus()

    def action_clear_filter(self) -> None:
        field = self.query_one("#file-filter", Input)
        field.value = ""
        field.display = False
        self.query_one("#files").focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "file-filter":
            self.fill_files(event.value)
            self.show_file()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "file-filter":
            self.query_one("#files").focus()

    def action_editor(self) -> None:
        if not self.paused or data.FILES[self.selected]["status"] == "-":
            self.notify("Editor unavailable: requires an existing file and a paused gate.", severity="warning")
            return
        self.notify("Design preview: $EDITOR would open this file. No file is opened.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in ("show-diff", "show-rendered"):
            self.action_content("diff" if event.button.id == "show-diff" else "rendered")
            event.stop()
