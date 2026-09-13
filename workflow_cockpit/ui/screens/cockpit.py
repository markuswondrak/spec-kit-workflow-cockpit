"""The run cockpit: Runway, state-driven Focus, engine output, command rail."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import OptionList, Static

from ...services.snapshot import OutcomeKind
from ...session.polling import PollingLoop
from ..view_model import default_focus_mode, format_elapsed
from ..widgets import TRUNCATION_MARKER, CommandRail, EngineOutput, HeaderRail, ResizeGuard, Runway
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
        Binding("s", "state", "State"),
        Binding("g", "gate", "Gate", show=False),
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
        self._held_mode: str | None = None
        self._last_default_mode: str | None = None
        self._selected_node_id: str | None = None
        self._selected_review_path: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield HeaderRail(id="header")
            with Horizontal(id="workspace"):
                with Vertical(id="runway"):
                    yield Static("01 / RUNWAY", classes="section-label")
                    yield Static(id="workflow-name")
                    yield Static(id="run-progress")
                    yield Runway(id="runway-graph")
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
        projection = snapshot.graph_projection
        runway = self.query_one(Runway)
        runway.update_projection(projection, self._selected_node_id)
        self._selected_node_id = runway.selected_node_id
        done = sum(1 for node in projection.nodes if node.status == "completed") if projection else 0
        total = len(projection.nodes) if projection else len(definition.steps) if definition else 0
        self.query_one("#run-progress", Static).update(Text.assemble((f"{done}/{total} complete", FOG)))
        self._update_output(snapshot)
        self._update_focus(snapshot)

    def _update_output(self, snapshot) -> None:
        output = self.query_one(EngineOutput)
        output.set_state(snapshot.status, self._output_expanded)
        # Track an absolute emitted count, not the bounded tail length, so
        # output keeps flowing after the retained tail saturates.
        emitted = snapshot.output_emitted
        delta = emitted - self._written
        if delta <= 0:
            return
        if delta > len(snapshot.output_tail):
            output.append_lines([TRUNCATION_MARKER, *snapshot.output_tail], reset=True)
        else:
            output.append_lines(list(snapshot.output_tail)[-delta:])
        self._written = emitted

    def _update_focus(self, snapshot) -> None:
        definition = getattr(self.session, "definition", None)
        default_mode = default_focus_mode(snapshot)
        if default_mode != self._last_default_mode:
            self._held_mode = None
            self._output_expanded = False
            self._last_default_mode = default_mode
        mode = self._held_mode or default_mode
        self._set_focus_mode(mode)
        step_label = self._step_label(snapshot, definition)
        if mode == "outcome":
            self._render_outcome(snapshot)
            return
        if mode == "gate":
            step = next(
                (s for s in (definition.steps if definition else ()) if s.id == snapshot.current_step_id),
                None,
            )
            message = step.message if step else "The engine is paused."
            self.query_one("#view-label", Static).update(Text.assemble(("GATE / PAUSED", f"bold {HOLD}")))
            self.query_one("#overview-content", Static).update(
                Text.assemble(
                    (f"{step_label}   /   attempt 1   /   engine paused\n\n", PAPER),
                    (message + "\n\n", HOLD),
                    ("Worktree changes and gate decisions arrive in S03/S04.\n", FOG),
                    ("Only Abort is available for this paused run in S01.", FOG),
                )
            )
        elif mode == "state":
            self.query_one("#view-label", Static).update(Text.assemble(("STATE", f"bold {PAPER}")))
            self.query_one("#overview-content", Static).update(
                Text.assemble(
                    (f"{step_label}\n\n", f"bold {PAPER}"),
                    (f"workflow {snapshot.workflow_name or snapshot.workflow_id}\n", FOG),
                    (f"run {snapshot.run_id}\n", COLD),
                    (f"status {snapshot.status}\n", FOG),
                )
            )
        else:
            self.query_one("#view-label", Static).update(Text.assemble(("OUTPUT / RUNNING", f"bold {PAPER}")))
            phase = "STARTING" if snapshot.status == "initializing" else "RUNNING"
            attempt = self._attempt(snapshot, self._selected_node_id or snapshot.current_step_id)
            next_step = self._next_step(snapshot)
            self.query_one("#overview-content", Static).update(
                Text.assemble(
                    (f"{phase}\n", FOG),
                    (
                        f"NOW {step_label}  attempt {attempt}  {format_elapsed(snapshot.elapsed_seconds)}\n",
                        f"bold {PAPER}",
                    ),
                    (f"NEXT {next_step}\n", FOG),
                )
            )
        self._update_commands(snapshot)

    def _set_focus_mode(self, mode: str) -> None:
        overview = self.query_one("#overview", VerticalScroll)
        output = self.query_one(EngineOutput)
        output.display = True
        output.set_class(mode == "output" or self._output_expanded, "full-canvas")
        overview.set_class(mode == "output", "compact-summary")
        if mode == "output":
            overview.display = True
            output.set_state(self._snapshot_now().status, True)
        elif self._output_expanded:
            overview.display = False
            output.set_state(self._snapshot_now().status, True)
        else:
            overview.display = True
            output.set_state(self._snapshot_now().status, False)

    def _step_label(self, snapshot, definition) -> str:
        selected = self._selected_node_id or snapshot.current_step_id
        projection = snapshot.graph_projection
        if projection is not None and selected:
            node = projection.graph.by_id.get(selected)
            if node is not None:
                return node.label
        if definition is not None:
            for step in definition.steps:
                if step.id == selected:
                    return step.label
        return selected or "—"

    @staticmethod
    def _attempt(snapshot, node_id: str | None) -> int:
        if snapshot.graph_projection is None or node_id is None:
            return 1
        node = snapshot.graph_projection.by_id.get(node_id)
        return node.attempts or 1 if node else 1

    @staticmethod
    def _next_step(snapshot) -> str:
        if snapshot.graph_projection is None:
            return "—"
        next_id = snapshot.graph_projection.next_node_id
        node = snapshot.graph_projection.graph.by_id.get(next_id) if next_id else None
        return node.label if node else "—"

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
        self._held_mode = "output"
        self._set_focus_mode("output")
        self.query_one(EngineOutput).log().scroll_end(animate=False)

    def action_collapse_output(self) -> None:
        self._output_expanded = False
        self._held_mode = None
        self._set_focus_mode(default_focus_mode(self._snapshot_now()))

    def action_tail(self) -> None:
        self.query_one(EngineOutput).log().scroll_end(animate=False)

    def action_state(self) -> None:
        self._held_mode = "state"
        self._update_focus(self._snapshot_now())

    def action_gate(self) -> None:
        if self._snapshot_now().status == "paused":
            self._held_mode = "gate"
            self._update_focus(self._snapshot_now())

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "runway-graph" and event.option.id is not None:
            self._selected_node_id = str(event.option.id)
            self.query_one(Runway).selected_node_id = self._selected_node_id
            self._update_focus(self._snapshot_now())
            event.stop()

    def action_abort(self) -> None:
        if self._snapshot_now().terminal:
            self.app.exit()
            return
        self.app.push_screen(
            ConfirmScreen(
                "Abort this run?",
                "The engine process group will be interrupted and stopped. This run cannot resume in this session.",
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
