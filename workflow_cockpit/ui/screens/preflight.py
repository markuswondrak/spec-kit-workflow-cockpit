"""Preflight prerequisite checklist with exact repair commands."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from ...bootstrap.preflight import Preflight
from ..widgets import ResizeGuard
from .base import AdaptiveScreen
from .help import HelpScreen
from .launch import LaunchScreen

FOG = "#94A399"
PAPER = "#E5E9DF"
SIGNAL = "#9CD6AD"
FAULT = "#EF9387"


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
                wordmark = Text.assemble((" C / ", "bold #E8BD79"), ("WORKFLOW COCKPIT", f"bold {PAPER}"))
                yield Static(wordmark, id="wordmark")
                yield Static(id="run-status")
            yield Static("  checking environment", id="identity")
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
            tone = SIGNAL if check.ok else FAULT
            lines.append(Text.assemble((f"{marker} ", tone), (check.label, PAPER)))
            if check.detail:
                lines.append(Text.assemble(("    ", FOG), (check.detail, FOG)))
            if not check.ok and check.repair:
                lines.append(Text.assemble(("    repair: ", FAULT), (check.repair, PAPER)))
        self.query_one("#preflight-list", Static).update(Text("\n").join(lines))
        status = "PROJECT READY" if report.ok else "PREREQUISITES MISSING"
        self.query_one("#run-status", Static).update(
            Text.assemble((status, f"bold {SIGNAL if report.ok else FAULT}"))
        )
        self.query_one("#identity", Static).update(Text.assemble(("  ", FOG), (str(report.project.root), PAPER)))
        if report.ok:
            self.query_one("#preflight-repair", Static).update(
                Text.assemble(("Launching workflow selection…", FOG))
            )
            session = self.session_factory(report.compatibility)
            self.app.session = session
            self.app.switch_screen(LaunchScreen(session, report))
        else:
            self.query_one("#preflight-repair", Static).update(
                Text.assemble(("Fix the items above, then press 'r' to re-check.", FOG))
            )

    def action_rerun(self) -> None:
        self._evaluate()

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_quit(self) -> None:
        self.app.exit()
