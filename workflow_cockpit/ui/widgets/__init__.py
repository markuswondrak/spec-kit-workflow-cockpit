"""Reusable Cockpit widgets sharing the flight-recorder visual vocabulary."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from ...services.snapshot import RunSnapshot
from ..palette import palette
from ..theme import active_style
from ..view_model import render_runway, state_grammar
from .indicator import BounceIndicator
from .review import FeatureFileList, GateOptions, MarkdownDocumentView, ReviewDocumentView

__all__ = [
    "TRUNCATION_MARKER",
    "BounceIndicator",
    "CommandRail",
    "EngineOutput",
    "ErrorStrip",
    "FeatureFileList",
    "GateOptions",
    "HeaderRail",
    "MarkdownDocumentView",
    "ResizeGuard",
    "ReviewDocumentView",
    "Runway",
]

def status_tone(status: str) -> str:
    """Runway tone for a node status, read from the active palette."""
    return {
        "running": palette.signal,
        "paused": palette.hold,
        "completed": palette.signal,
        "skipped": palette.fog,
        "aborted": palette.fault,
        "failed": palette.fault,
        "pending": palette.fog,
    }.get(status, palette.fog)


TRUNCATION_MARKER = "... earlier output truncated ..."


def _text(*parts) -> Text:
    return Text.assemble(*parts)


class HeaderRail(Vertical):
    """Product identity, run state, branch, elapsed, run ID."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="masthead"):
            yield Static(
                _text((" C / ", f"bold {palette.hold}"), ("WORKFLOW COCKPIT", f"bold {palette.paper}")),
                id="wordmark",
            )
            yield Static(id="style-field")
            yield Static(id="run-status")
            yield Static("?  help", id="help-hint")
        yield Static(id="identity")

    def update_snapshot(self, snapshot: RunSnapshot) -> None:
        symbol, word = state_grammar(snapshot.status)
        tone = self_tone(snapshot.status)
        if snapshot.stale:
            word = f"{word} / STALE"
            tone = palette.hold
        self.query_one("#run-status", Static).update(_text((f"{symbol} {word}", f"bold {tone}")))
        branch = snapshot.branch or "unknown"
        elapsed = _elapsed(snapshot)
        run = snapshot.abbreviated_run_id or "—"
        parts = [
            ("  BRANCH ", palette.fog),
            (branch, palette.paper),
            ("   /   ELAPSED ", palette.fog),
            (elapsed, palette.paper),
            ("   /   RUN ", palette.fog),
            (run, palette.fog),
        ]
        if snapshot.adopted:
            parts.extend([("   /   ", palette.fog), ("ADOPTED", f"bold {palette.hold}")])
        elif snapshot.read_only:
            parts.extend([("   /   ", palette.fog), ("VIEW ONLY", f"bold {palette.cold}")])
        self.query_one("#identity", Static).update(_text(*parts))

    def on_mount(self) -> None:
        self.update_style()

    def update_style(self) -> None:
        """Show the resolved template name, marking a fallback non-fatally."""
        style = active_style()
        label = style.display_name or style.name
        if style.is_fallback:
            self.query_one("#style-field", Static).update(
                _text(("STYLE ", palette.fog), (f"{label} / FALLBACK", palette.hold))
            )
        else:
            self.query_one("#style-field", Static).update(
                _text(("STYLE ", palette.fog), (label, palette.paper))
            )


def self_tone(status: str) -> str:
    """Header run-state tone, read from the active palette."""
    return {
        "running": palette.signal,
        "initializing": palette.signal,
        "paused": palette.hold,
        "aborting": palette.fault,
        "completed": palette.signal,
        "success": palette.signal,
        "failed": palette.fault,
        "failure": palette.fault,
        "aborted": palette.fault,
        "abort": palette.fault,
    }.get(status, palette.paper)


def _elapsed(snapshot: RunSnapshot) -> str:
    seconds = int(snapshot.elapsed_seconds)
    minutes, secs = divmod(seconds, 60)
    return f"{minutes:02d}:{secs:02d}"


class Runway(OptionList):
    """Read-only declared graph; the current node is emphasized in place.

    Labels that do not fit the sidebar are tail-truncated, never middle-cut, and
    hovering a row reveals its complete declared label as a tooltip. Textual 8
    exposes tooltips per widget rather than per ``Option``, so the hover target
    is resolved in the widget layer against the full labels held as plain data.
    """

    can_focus = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._full_labels: dict[str, str] = {}

    def update_projection(self, projection) -> None:
        scroll_y = self.scroll_y
        rows = render_runway(projection, width=max(12, self.size.width or 36))
        self._full_labels = {str(row.id): row.full_label for row in rows}
        current = projection.current_node_id if projection is not None else None
        options: list[Option] = []
        for row in rows:
            tone = status_tone(row.status)
            if str(row.id) == current:
                options.append(Option(_text((row.text, f"bold underline {tone}")), id=row.id))
            elif row.active:
                options.append(Option(_text((row.text, f"bold {tone}")), id=row.id))
            else:
                label_style = palette.paper if row.status != "pending" else palette.fog
                options.append(Option(_text((row.text, label_style)), id=row.id))
        self.clear_options()
        self.add_options(options)
        self.scroll_to(y=scroll_y, animate=False)

    def _on_mouse_move(self, event) -> None:
        super()._on_mouse_move(event)
        index = event.style.meta.get("option")
        option = self.get_option_at_index(index) if index is not None else None
        self.tooltip = self._full_labels.get(str(option.id)) if option is not None else None

    def _on_leave(self, event) -> None:
        super()._on_leave(event)
        self.tooltip = None


class EngineOutput(Vertical):
    """Read-only bounded RichLog fed from the supervisor's normalizer."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="output-heading"):
            yield Static(id="output-title")
            yield BounceIndicator(id="activity")
            yield Static(id="output-hint")
        yield RichLog(id="engine", highlight=False, markup=False, wrap=True, max_lines=2000)

    def set_state(self, status: str, expanded: bool, full: bool = False) -> None:
        if status == "running" or status == "initializing":
            label, tone = "LIVE [>]", palette.signal
        elif status == "paused":
            label, tone = "PAUSED [!]", palette.hold
        else:
            label, tone = "STOPPED", palette.fog
        self.query_one("#output-title", Static).update(
            _text(("ENGINE OUTPUT", palette.fog), (f"  /  {label}", tone))
        )
        active = status in ("running", "initializing", "aborting")
        self.query_one("#activity", BounceIndicator).display = active
        self.set_class(expanded, "expanded")
        self.set_class(full, "full-canvas")
        self.query_one("#output-hint", Static).update(_text((self._hint(status, expanded, full), palette.fog)))

    @staticmethod
    def _hint(status: str, expanded: bool, full: bool) -> str:
        if full:
            if status in ("running", "initializing", "aborting"):
                return "[end] tail"
            return "[l] close  [end] tail"
        if expanded:
            return "[l] full  [e] collapse  [end] tail"
        return "[l] open  [end] tail"

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
            log.write(Text(line, style=palette.fog), scroll_end=False)
        if lines and at_tail:
            log.scroll_end(animate=False)


class CommandRail(Horizontal):
    """Bottom actions; destructive actions are always labeled."""

    def compose(self) -> ComposeResult:
        yield Static(id="commands")
        yield Static(id="feedback")
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

    def set_feedback(self, message: str) -> None:
        """Transient success feedback, shown on the rail for a short while."""
        self.query_one("#feedback", Static).update(_text((message, palette.signal)) if message else "")


class ErrorStrip(Static):
    """Persistent, actionable error strip above the command rail.

    The strip states the failed operation, the authoritative run state, and the
    next available action. It stays visible until every source clears.
    """

    def on_mount(self) -> None:
        self.display = False

    def show(self, message: str) -> None:
        self.update(_text((f"  {message}", palette.fault)))
        self.display = True

    def clear(self) -> None:
        self.update("")
        self.display = False


class ResizeGuard(Static):
    """Blocking resize instruction shown below the minimum terminal size."""

    def render_size(self, width: int, height: int) -> None:
        self.update(
            _text(
                ("MORE ROOM TO WORK\n\n", f"bold {palette.hold}"),
                (f"Terminal  {width} x {height}\n", palette.paper),
                ("Required  88 x 36\n\n", palette.fog),
                ("Resize to continue. Your place is preserved.\n[q] exit", palette.paper),
            )
        )
