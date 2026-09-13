"""The run cockpit: header, step rail, overview, engine output, command rail."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from ...services.snapshot import OutcomeKind
from ...session.polling import PollingLoop
from ..view_model import build_step_rows
from ..widgets import CommandRail, EngineOutput, HeaderRail, ResizeGuard, StepRail
from .base import AdaptiveScreen
from .confirm import ConfirmScreen
from .help import HelpScreen

FOG = "#94A399"
PAPER = "#E5E9DF"
SIGNAL = "#9CD6AD"
FAULT = "#EF9387"
COLD = "#A1BFCE"
HOLD = "#E8BD79"


class CockpitScreen(AdaptiveScreen):
    BINDINGS = [
        Binding("x", "abort", "Abort"),
        Binding("q", "quit", "Exit"),
        Binding("l", "expand_output", "Output"),
        Binding("e", "collapse_output", "Collapse", show=False),
        Binding("end", "tail", show=False),
        Binding("enter", "acknowledge", show=False, priority=True),
        Binding("question_mark", "help", "Help"),
    ]

    def __init__(self, session) -> None:
        super().__init__()
        self.session = session
        self._loop = PollingLoop(session)
        self._snapshot = None
        self._written = 0
        self._output_expanded = False

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield HeaderRail(id="header")
            with Horizontal(id="workspace"):
                with Vertical(id="runway"):
                    yield Static("01 / WORKFLOW", classes="section-label")
                    yield Static(id="workflow-name")
                    yield Static(id="run-progress")
                    yield StepRail(id="steps")
                with Vertical(id="focus"):
                    with Horizontal(id="view-tabs"):
                        yield Static(id="view-label")
                    with VerticalScroll(id="overview"):
                        yield Static(id="overview-content")
                    yield EngineOutput(id="output")
            yield CommandRail(id="command-rail")
        yield ResizeGuard(id="resize-guard")

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh()
        self.set_interval(0.25, self._refresh)

    def _snapshot_now(self):
        if self._snapshot is None:
            self._snapshot = self._loop.tick()
        return self._snapshot

    def _refresh(self) -> None:
        snapshot = self._loop.tick()
        self._snapshot = snapshot
        self.query_one(HeaderRail).update_snapshot(snapshot)
        definition = getattr(self.session, "definition", None)
        if definition is not None:
            self.query_one("#workflow-name", Static).update(Text.assemble((definition.name, PAPER)))
        rows = build_step_rows(definition, snapshot)
        current = None
        if definition is not None and snapshot.current_step_id is not None:
            for index, step in enumerate(definition.steps):
                if step.id == snapshot.current_step_id:
                    current = index
                    break
        self.query_one(StepRail).update_steps(rows, current)
        done = sum(1 for row in rows if row.status == "done")
        self.query_one("#run-progress", Static).update(
            Text.assemble((f"{done}/{len(rows)} complete", FOG))
        )
        self._update_output(snapshot)
        self._update_focus(snapshot)

    def _update_output(self, snapshot) -> None:
        tail = list(snapshot.output_tail)
        reset = len(tail) < self._written
        new_lines = tail if reset else tail[self._written :]
        output = self.query_one(EngineOutput)
        output.set_state(snapshot.status, self._output_expanded)
        output.append_lines(new_lines, reset=reset)
        self._written = len(tail)

    def _update_focus(self, snapshot) -> None:
        definition = getattr(self.session, "definition", None)
        step_label = snapshot.current_step_id or "—"
        if definition is not None:
            for step in definition.steps:
                if step.id == snapshot.current_step_id:
                    step_label = step.label
                    break
        if snapshot.outcome is not None:
            self._render_outcome(snapshot)
            return
        if snapshot.status == "paused":
            step = next(
                (s for s in (definition.steps if definition else ()) if s.id == snapshot.current_step_id),
                None,
            )
            message = step.message if step else "The engine is paused."
            self.query_one("#view-label", Static).update(Text.assemble(("PAUSED AT GATE", f"bold {HOLD}")))
            self.query_one("#overview-content", Static).update(
                Text.assemble(
                    (f"{step_label}   /   attempt 1   /   engine paused\n\n", PAPER),
                    (message + "\n\n", HOLD),
                    ("Worktree changes and gate decisions arrive in S03/S04.\n", FOG),
                    ("Only Abort is available for this paused run in S01.", FOG),
                )
            )
        else:
            self.query_one("#view-label", Static).update(Text.assemble(("OVERVIEW", f"bold {PAPER}")))
            phase = "STARTING" if snapshot.status == "initializing" else "RUNNING"
            self.query_one("#overview-content", Static).update(
                Text.assemble(
                    (f"{phase}\n\n", FOG),
                    (f"{step_label}\n", f"bold {PAPER}"),
                    (f"workflow {snapshot.workflow_name or snapshot.workflow_id}\n", FOG),
                    (f"run {snapshot.run_id}\n", COLD),
                )
            )
        self._update_commands(snapshot)

    def _render_outcome(self, snapshot) -> None:
        outcome = snapshot.outcome
        if outcome.kind is OutcomeKind.SUCCESS:
            marker, tone, heading = "[x]", SIGNAL, "RUN COMPLETE"
        elif outcome.kind is OutcomeKind.ABORT:
            marker, tone, heading = "[/]", FAULT, "RUN ABORTED"
        else:
            marker, tone, heading = "[X]", FAULT, "RUN FAILED"
        self.query_one("#view-label", Static).update(Text.assemble((f"{marker} {heading}", f"bold {tone}")))
        detail = outcome.detail or ""
        step = outcome.step_id or snapshot.current_step_id or "—"
        self.query_one("#overview-content", Static).update(
            Text.assemble(
                (f"{heading} {marker}\n\n", f"bold {tone}"),
                (f"{step}\n", PAPER),
                (f"status {snapshot.status}   /   engine {outcome.engine_status or snapshot.engine_status}\n", FOG),
                (f"{detail}\n\n", tone if outcome.kind is not OutcomeKind.SUCCESS else FOG),
                ("Press enter to close.", PAPER),
            )
        )
        self._update_commands(snapshot)

    def _update_commands(self, snapshot) -> None:
        rail = self.query_one(CommandRail)
        if snapshot.terminal:
            rail.set_actions("  enter  close", None)
        elif snapshot.status == "paused":
            rail.set_actions("  l  output     x  abort run     ?  help", "x  Abort run")
        else:
            rail.set_actions("  l  output     x  abort run     ?  help", "x  Abort run")

    def action_expand_output(self) -> None:
        self._output_expanded = True
        self.query_one(EngineOutput).set_state(self._snapshot_now().status, True)
        self.query_one(EngineOutput).log().scroll_end(animate=False)

    def action_collapse_output(self) -> None:
        self._output_expanded = False
        self.query_one(EngineOutput).set_state(self._snapshot_now().status, False)

    def action_tail(self) -> None:
        self.query_one(EngineOutput).log().scroll_end(animate=False)

    def action_abort(self) -> None:
        if self._snapshot_now().terminal:
            self.app.exit()
            return
        self.app.push_screen(
            ConfirmScreen(
                "Abort this run?",
                "The engine process group will be interrupted and stopped. "
                "This run cannot resume in this session.",
                confirm_label="Abort run",
                note="Worktree changes are preserved.",
                destructive=True,
            ),
            self._after_abort,
        )

    def _after_abort(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        self.session.abort()
        self._refresh()

    def action_quit(self) -> None:
        if self.is_small() or self._snapshot_now().terminal:
            self.app.exit()
            return
        self.action_abort()

    def action_acknowledge(self) -> None:
        if self._snapshot_now().terminal:
            self.app.exit()

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())
