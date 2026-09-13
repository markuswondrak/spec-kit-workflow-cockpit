"""Reusable Cockpit widgets sharing the flight-recorder visual vocabulary."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, LoadingIndicator, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from ...services.snapshot import RunSnapshot
from ..palette import FAULT, FOG, HOLD, PAPER, SIGNAL
from ..view_model import render_runway, state_grammar
from .review import ChangedFileList, GateOptions, ReviewDocumentView

__all__ = [
    "TRUNCATION_MARKER",
    "ChangedFileList",
    "CommandRail",
    "EngineOutput",
    "GateOptions",
    "HeaderRail",
    "ResizeGuard",
    "ReviewDocumentView",
    "Runway",
]

STATUS_STYLES = {
    "running": SIGNAL,
    "paused": HOLD,
    "completed": SIGNAL,
    "skipped": FOG,
    "aborted": FAULT,
    "failed": FAULT,
    "pending": FOG,
}

TRUNCATION_MARKER = "... earlier output truncated ..."


def _text(*parts) -> Text:
    return Text.assemble(*parts)


class HeaderRail(Vertical):
    """Product identity, run state, branch, baseline, elapsed, run ID."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="masthead"):
            yield Static(_text((" C / ", f"bold {HOLD}"), ("WORKFLOW COCKPIT", f"bold {PAPER}")), id="wordmark")
            yield Static(id="run-status")
            yield Static("?  help", id="help-hint")
        yield Static(id="identity")

    def update_snapshot(self, snapshot: RunSnapshot) -> None:
        symbol, word = state_grammar(snapshot.status)
        tone = SELF_TONE.get(snapshot.status, PAPER)
        self.query_one("#run-status", Static).update(_text((f"{symbol} {word}", f"bold {tone}")))
        branch = snapshot.branch or "unknown"
        baseline = (snapshot.baseline_commit or "")[:7] or "unknown"
        elapsed = _elapsed(snapshot)
        run = snapshot.abbreviated_run_id or "—"
        self.query_one("#identity", Static).update(
            _text(
                ("  BRANCH ", FOG),
                (branch, PAPER),
                ("   /   BASE ", FOG),
                (baseline, PAPER),
                ("   /   ELAPSED ", FOG),
                (elapsed, PAPER),
                ("   /   RUN ", FOG),
                (run, FOG),
            )
        )


SELF_TONE = {
    "running": SIGNAL,
    "initializing": SIGNAL,
    "paused": HOLD,
    "aborting": FAULT,
    "completed": SIGNAL,
    "success": SIGNAL,
    "failed": FAULT,
    "failure": FAULT,
    "aborted": FAULT,
    "abort": FAULT,
}


def _elapsed(snapshot: RunSnapshot) -> str:
    seconds = int(snapshot.elapsed_seconds)
    minutes, secs = divmod(seconds, 60)
    return f"{minutes:02d}:{secs:02d}"


class Runway(OptionList):
    """Scrollable declared graph that retains node selection across refreshes."""

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.selected_node_id: str | None = None

    def update_projection(self, projection, selected_id: str | None = None) -> None:
        scroll_y = self.scroll_y
        # Capture the live highlight before rebuilding; a rebuild must not
        # discard a selection the user just made, even if the highlight event
        # has not been processed yet.
        live = self.highlighted_option
        live_id = str(live.id) if live is not None and live.id is not None else None
        rows = render_runway(projection, width=max(12, self.size.width or 29))
        options: list[Option] = []
        for row in rows:
            tone = STATUS_STYLES.get(row.status, FOG)
            label_style = PAPER if row.status != "pending" else FOG
            options.append(Option(_text((row.text, tone if row.active else label_style)), id=row.id))
        self.clear_options()
        self.add_options(options)
        if options:
            index_by_id = {str(option.id): index for index, option in enumerate(options)}
            current = projection.current_node_id if projection is not None else None
            preferred = live_id or selected_id or self.selected_node_id or current
            self.highlighted = index_by_id.get(preferred or "", 0)
            option = options[self.highlighted]
            self.selected_node_id = str(option.id)
            self.scroll_to(y=scroll_y, animate=False)


class EngineOutput(Vertical):
    """Read-only bounded RichLog fed from the supervisor's normalizer."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="output-heading"):
            yield Static(id="output-title")
            yield LoadingIndicator(id="activity")
            yield Static("[e] collapse  [l] tail  [end] tail", id="output-hint")
        yield RichLog(id="engine", highlight=False, markup=False, wrap=True, max_lines=2000)

    def set_state(self, status: str, expanded: bool) -> None:
        if status == "running" or status == "initializing":
            label, tone = "LIVE [>]", SIGNAL
        elif status == "paused":
            label, tone = "PAUSED [!]", HOLD
        else:
            label, tone = "STOPPED", FOG
        self.query_one("#output-title", Static).update(_text(("ENGINE OUTPUT", FOG), (f"  /  {label}", tone)))
        active = status in ("running", "initializing", "aborting")
        self.query_one("#activity", LoadingIndicator).display = active
        self.set_class(expanded, "expanded")

    def log(self) -> RichLog:
        return self.query_one("#engine", RichLog)

    def append_lines(self, lines: list[str], reset: bool = False) -> None:
        log = self.log()
        at_tail = log.scroll_y >= max(0, log.virtual_size.height - log.size.height)
        if reset:
            log.clear()
        # RichLog.write auto-scrolls by default; suppress it so a reader who has
        # scrolled up keeps their place, then follow the tail explicitly.
        for line in lines:
            log.write(Text(line, style=FOG), scroll_end=False)
        if lines and at_tail:
            log.scroll_end(animate=False)


class CommandRail(Horizontal):
    """Bottom actions; destructive actions are always labeled."""

    def compose(self) -> ComposeResult:
        yield Static(id="commands")
        yield Button("x  Abort run", id="abort")

    def set_actions(self, commands: str, abort_label: str | None, abort_variant: str = "error") -> None:
        self.query_one("#commands", Static).update(Text.from_markup(commands))
        button = self.query_one("#abort", Button)
        if abort_label is None:
            button.display = False
        else:
            button.display = True
            button.label = abort_label
            button.variant = abort_variant


class ResizeGuard(Static):
    """Blocking resize instruction shown below the minimum terminal size."""

    def render_size(self, width: int, height: int) -> None:
        self.update(
            _text(
                ("MORE ROOM TO WORK\n\n", f"bold {HOLD}"),
                (f"Terminal  {width} x {height}\n", PAPER),
                ("Required  88 x 36\n\n", FOG),
                ("Resize to continue. Your place is preserved.\n[q] exit", PAPER),
            )
        )
