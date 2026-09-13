"""Reusable Cockpit widgets sharing the flight-recorder visual vocabulary."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from ...services.snapshot import RunSnapshot
from ..view_model import state_grammar

INK = "#101312"
DECK = "#171C19"
RAISED = "#202821"
RAIL = "#303B34"
FOG = "#94A399"
PAPER = "#E5E9DF"
SIGNAL = "#9CD6AD"
HOLD = "#E8BD79"
FAULT = "#EF9387"
COLD = "#A1BFCE"

STATUS_STYLES = {
    "running": SIGNAL,
    "gate": HOLD,
    "done": SIGNAL,
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


class StepRail(OptionList):
    """Low-fidelity step list replaced by the S02 Runway."""

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
    ]

    def update_steps(self, rows, current: int | None) -> None:
        options: list[Option] = []
        for row in rows:
            tone = STATUS_STYLES.get(row.status, FOG)
            label_style = PAPER if row.status != "pending" else FOG
            options.append(
                Option(_text((f"{row.marker} ", tone), (row.label, label_style)), id=row.label)
            )
        self.clear_options()
        self.add_options(options)
        if options:
            if current is not None and 0 <= current < len(options):
                self.highlighted = current
            elif self.highlighted is None:
                self.highlighted = 0


class EngineOutput(Vertical):
    """Read-only bounded RichLog fed from the supervisor's normalizer."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="output-heading"):
            yield Static(id="output-title")
            yield Static("[e] collapse  [l] tail  [end] tail", id="output-hint")
        yield RichLog(id="engine", highlight=False, markup=False, wrap=True, max_lines=2000)

    def set_state(self, status: str, expanded: bool) -> None:
        if status == "running" or status == "initializing":
            label, tone = "LIVE [>]", SIGNAL
        elif status == "paused":
            label, tone = "PAUSED [!]", HOLD
        else:
            label, tone = "STOPPED", FOG
        self.query_one("#output-title", Static).update(
            _text(("ENGINE OUTPUT", FOG), (f"  /  {label}", tone))
        )
        self.set_class(expanded, "expanded")

    def log(self) -> RichLog:
        return self.query_one("#engine", RichLog)

    def append_lines(self, lines: list[str], reset: bool = False) -> None:
        log = self.log()
        if reset:
            log.clear()
        for line in lines:
            log.write(Text(line, style=FOG))
        if lines:
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
