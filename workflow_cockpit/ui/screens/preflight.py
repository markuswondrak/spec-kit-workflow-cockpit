"""Preflight prerequisite checklist with exact repair commands."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from ...bootstrap.preflight import Preflight
from ..palette import palette
from ..theme import active_style
from ..widgets import ResizeGuard
from .base import AdaptiveScreen
from .help import HelpScreen
from .launch import LaunchScreen


class PreflightScreen(AdaptiveScreen):
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "rerun", "Re-check"),
        Binding("question_mark", "help", "Help"),
    ]

    def __init__(self, preflight: Preflight, session_factory) -> None:
        super().__init__()
        self.preflight = preflight
        self.session_factory = session_factory

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            with Horizontal(id="masthead"):
                wordmark = Text.assemble(
                    (" C / ", f"bold {palette.hold}"), ("WORKFLOW COCKPIT", f"bold {palette.paper}")
                )
                yield Static(wordmark, id="wordmark")
                yield Static(id="run-status")
            yield Static("  checking environment", id="identity")
            yield Static(id="style-note")
            with VerticalScroll(id="preflight-content"):
                yield Static("00 / PREFLIGHT", classes="section-label")
                yield Static(id="preflight-list")
                yield Static(id="preflight-repair")
            yield Static(" q  quit     r  re-check     ?  help", id="launch-commands")
        yield ResizeGuard(id="resize-guard")

    def on_mount(self) -> None:
        super().on_mount()
        self._evaluate()

    def _evaluate(self) -> None:
        report = self.preflight.run()
        lines: list = []
        for check in report.checks:
            marker = "[x]" if check.ok else "[X]"
            tone = palette.signal if check.ok else palette.fault
            lines.append(Text.assemble((f"{marker} ", tone), (check.label, palette.paper)))
            if check.detail:
                lines.append(Text.assemble(("    ", palette.fog), (check.detail, palette.fog)))
            if not check.ok and check.repair:
                lines.append(Text.assemble(("    repair: ", palette.fault), (check.repair, palette.paper)))
        self.query_one("#preflight-list", Static).update(Text("\n").join(lines))
        status = "PROJECT READY" if report.ok else "PREREQUISITES MISSING"
        self.query_one("#run-status", Static).update(
            Text.assemble((status, f"bold {palette.signal if report.ok else palette.fault}"))
        )
        root = str(report.project.root)
        self.query_one("#identity", Static).update(Text.assemble(("  ", palette.fog), (root, palette.paper)))
        self._render_style_note()
        if report.ok:
            self.query_one("#preflight-repair", Static).update(
                Text.assemble(("Launching workflow selection…", palette.fog))
            )
            session = self.session_factory(report.compatibility)
            self.app.session = session
            self.app.switch_screen(LaunchScreen(session, report))
        else:
            self.query_one("#preflight-repair", Static).update(
                Text.assemble(("Fix the items above, then press 'r' to re-check.", palette.fog))
            )

    def _render_style_note(self) -> None:
        """Always show the resolved style; name the fallback reason non-fatally."""
        style = active_style()
        label = style.display_name or style.name
        note = self.query_one("#style-note", Static)
        if style.is_fallback:
            note.update(
                Text.assemble(("STYLE  ", palette.fog), (label, palette.paper), (f"  /  {style.notice}", palette.hold))
            )
        else:
            note.update(Text.assemble(("STYLE  ", palette.fog), (label, palette.paper)))

    def action_rerun(self) -> None:
        self._evaluate()

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_quit(self) -> None:
        self.app.exit()
