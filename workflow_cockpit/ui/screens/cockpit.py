"""The run cockpit: Runway, state-driven Focus, review, output, command rail."""

from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Static

from ...services.context_index import SKILL_GUIDANCE
from ...services.review import ReviewDocument
from ...services.snapshot import OutcomeKind, RunSnapshot
from ..editor import default_editor_launcher, editor_environment
from ..palette import COLD, FAULT, FOG, PAPER, SIGNAL
from ..view_model import default_focus_mode, format_elapsed, gate_decision
from ..widgets import (
    TRUNCATION_MARKER,
    CommandRail,
    EngineOutput,
    ErrorStrip,
    FeatureFileList,
    GateOptions,
    HeaderRail,
    ResizeGuard,
    ReviewDocumentView,
    Runway,
)
from .aborting import AbortingScreen
from .base import AdaptiveScreen
from .confirm import ConfirmScreen
from .help import HelpScreen
from .review_mixin import ReviewMixin
from .run_poll_mixin import BRANCH_REFRESH_SECONDS, RunPollMixin


class CockpitScreen(RunPollMixin, ReviewMixin, AdaptiveScreen):
    BINDINGS = [
        Binding("x", "abort", "Abort"),
        Binding("q", "quit", "Exit"),
        Binding("l", "expand_output", "Output"),
        Binding("e", "collapse_output", "Collapse", show=False),
        Binding("s", "state", "State"),
        Binding("g", "gate", "Gate", show=False),
        Binding("c", "changes", "Files", show=False),
        Binding("o", "open_editor", show=False),
        Binding("f", "full_file", show=False),
        Binding("slash", "filter", show=False),
        *[Binding(str(number), f"choose({number})", show=False) for number in range(1, 10)],
        Binding("end", "tail", show=False),
        Binding("enter", "acknowledge", show=False, priority=True),
        Binding("question_mark", "help", "Help"),
    ]

    def __init__(self, session, *, editor_launcher=None, editor_env=None) -> None:
        super().__init__()
        self._init_run_poll(session)
        self._editor_launcher = editor_launcher or default_editor_launcher
        self._editor_env = editor_env or editor_environment
        self._written = 0
        self._output_expanded = False
        self._held_mode: str | None = None
        self._focus_mode: str | None = None
        self._last_default_mode: str | None = None
        self._selected_node_id: str | None = None
        self._selected_review_path: str | None = None
        self._filter = ""
        self._review_loaded = False
        self._review_tick = 0
        self._review_pending = False
        self._full_file = False
        self._current_document: ReviewDocument | None = None
        self._document_key: tuple | None = None
        self._document_pending_key: tuple | None = None
        self._diagnostic = ""
        self._pending_decision: tuple[str, str | None] | None = None

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
                        yield Static(id="review-status")
                    with VerticalScroll(id="overview"):
                        yield Static(id="overview-content")
                    with Horizontal(id="review-panel"):
                        with Vertical(id="review-index"):
                            yield Input(placeholder="filter paths", id="review-filter")
                            yield FeatureFileList(id="feature-files")
                        with VerticalScroll(id="review-scroll"):
                            yield ReviewDocumentView(id="review-document")
                    with Horizontal(id="decide-bar"):
                        yield Static("DECIDE", id="decide-label")
                        yield GateOptions(id="gate-options")
                        yield Static(id="decide-hint")
                    yield EngineOutput(id="output")
            yield ErrorStrip(id="error-strip")
            yield CommandRail(id="command-rail")
        yield ResizeGuard(id="resize-guard")

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh()
        # The timer only requests a poll; snapshot production runs in a
        # single-exclusive worker so rendering is never blocked by Git or I/O.
        self.set_interval(0.25, self._request_poll)
        self.set_interval(BRANCH_REFRESH_SECONDS, self._request_branch)

    def _refresh(self) -> None:
        self._request_poll(force=True)

    def _apply_snapshot(self, snapshot: RunSnapshot) -> None:
        if snapshot is None:
            return
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
        self._maybe_load_review(snapshot)
        self._update_output(snapshot)
        self._update_focus(snapshot)

    def _update_output(self, snapshot) -> None:
        output = self.query_one(EngineOutput)
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
            self._full_file = False
            self._last_default_mode = default_mode
        mode = self._held_mode or default_mode
        self._focus_mode = mode
        self._set_focus_mode(mode)
        step_label = self._step_label(snapshot, definition)
        if mode == "outcome":
            self._render_outcome(snapshot)
        elif mode == "gate":
            self._render_gate(snapshot, step_label)
        elif mode == "changes":
            self._render_changes(snapshot)
        elif mode == "state":
            self._render_state(snapshot, step_label)
        else:
            self._render_output_mode(snapshot, step_label)
        self._update_commands(snapshot)
        self._render_error_strip(snapshot)

    def _set_focus_mode(self, mode: str) -> None:
        snapshot = self._snapshot_now()
        overview = self.query_one("#overview", VerticalScroll)
        review = self.query_one("#review-panel")
        decide = self.query_one("#decide-bar")
        output = self.query_one(EngineOutput)
        full = mode == "output"
        output.display = True
        output.set_state(snapshot.status, expanded=full or self._output_expanded, full=full)
        overview.display = mode != "changes"
        overview.set_class(mode == "output", "compact-summary")
        overview.set_class(mode == "gate", "gate-summary")
        review.display = mode in ("gate", "changes")
        # The decide bar follows the unified gate snapshot: selectable while
        # ready, visible-but-disabled while submitted, unverified, or blocked
        # when the gate still declares options.
        decision = gate_decision(snapshot) if mode == "gate" else None
        decide.display = decision is not None and bool(decision.options)

    def _render_state(self, snapshot, step_label) -> None:
        self.query_one("#review-status", Static).update("")
        self.query_one("#view-label", Static).update(Text.assemble(("STATE", f"bold {PAPER}")))
        parts: list = [
            (f"{step_label}\n\n", f"bold {PAPER}"),
            (f"workflow {snapshot.workflow_name or snapshot.workflow_id}\n", FOG),
            (f"run {snapshot.run_id}\n", COLD),
            (f"status {snapshot.status}\n", FOG),
        ]
        parts.extend(self._context_lines(snapshot))
        self.query_one("#overview-content", Static).update(Text.assemble(*parts))

    @staticmethod
    def _context_lines(snapshot) -> list:
        if snapshot.context_error:
            return [(f"\n{snapshot.context_error}\n", FAULT)]
        if snapshot.context_path:
            return [
                ("\ncontext ", FOG),
                (snapshot.context_path + "\n", COLD),
                (SKILL_GUIDANCE + "\n", FOG),
            ]
        return []

    def _render_output_mode(self, snapshot, step_label) -> None:
        self.query_one("#review-status", Static).update("")
        self.query_one("#view-label", Static).update(Text.assemble(("OUTPUT / RUNNING", f"bold {PAPER}")))
        phase = "STARTING" if snapshot.status == "initializing" else "RUNNING"
        attempt = self._attempt(snapshot, self._selected_node_id or snapshot.current_step_id)
        next_step = self._next_step(snapshot)
        self.query_one("#overview-content", Static).update(
            Text.assemble(
                (f"{phase}\n", FOG),
                (f"NOW {step_label}  attempt {attempt}  {format_elapsed(snapshot.elapsed_seconds)}\n", f"bold {PAPER}"),
                (f"NEXT {next_step}\n", FOG),
            )
        )

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
        self.query_one("#review-status", Static).update("")
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
        stale = "STALE  /  " if snapshot.stale else ""
        if snapshot.terminal:
            rail.set_actions(f"  {stale}enter  close", None)
            return
        decision = gate_decision(snapshot)
        if decision.selectable:
            digits = " ".join(str(index) for index in range(1, min(9, len(decision.options)) + 1))
            rail.set_actions(
                f"  {stale}{digits}  decide     c  changes     s  state     x  abort", "x  Abort run"
            )
        elif snapshot.gate is not None:
            rail.set_actions(
                f"  {stale}c  changes     s  state     l  output     x  abort run", "x  Abort run"
            )
        else:
            rail.set_actions(
                f"  {stale}l  output     x  abort run     ?  help", "x  Abort run"
            )

    def action_expand_output(self) -> None:
        snapshot = self._snapshot_now()
        at_gate = snapshot.gate is not None
        if at_gate:
            if not self._output_expanded:
                self._output_expanded = True
                self._held_mode = "gate"
            elif self._held_mode != "output":
                self._held_mode = "output"
            else:
                self._output_expanded = False
                self._held_mode = "gate"
        else:
            self._output_expanded = True
            self._held_mode = "output"
        self._update_focus(snapshot)
        self.query_one(EngineOutput).log().scroll_end(animate=False)

    def action_collapse_output(self) -> None:
        snapshot = self._snapshot_now()
        self._output_expanded = False
        self._held_mode = "gate" if snapshot.gate is not None else None
        self._update_focus(snapshot)

    def action_tail(self) -> None:
        self.query_one(EngineOutput).log().scroll_end(animate=False)

    def action_state(self) -> None:
        self._held_mode = "state"
        self._update_focus(self._snapshot_now())

    def action_gate(self) -> None:
        snapshot = self._snapshot_now()
        if snapshot.gate is not None:
            self._held_mode = "gate"
            self._update_focus(snapshot)

    def action_changes(self) -> None:
        snapshot = self._snapshot_now()
        if snapshot.gate is None and snapshot.review is None:
            return
        self._held_mode = "changes"
        if snapshot.gate is not None:
            self._reload_review()
        self._update_focus(snapshot)

    def action_choose(self, index: str | None = None) -> None:
        snapshot = self._snapshot_now()
        decision = gate_decision(snapshot)
        if self._focus_mode != "gate" or not decision.selectable:
            return
        if index is not None:
            try:
                number = int(index)
            except (TypeError, ValueError):
                return
            if not 1 <= number <= len(decision.options):
                return
            self._confirm_choice(decision.options[number - 1])
            return
        selected = self.query_one(GateOptions).selected_option()
        if selected is not None:
            self._confirm_choice(selected)

    def _confirm_choice(self, choice: str) -> None:
        snapshot = self._snapshot_now()
        gate = snapshot.gate
        if gate is None or not gate.selectable:
            return
        self._pending_decision = (choice, gate.token)
        title = f"Submit {choice!r}?"
        effect = "The confirmed choice is submitted once. Persisted engine state stays authoritative."
        if gate.on_reject and choice.lower() in ("reject", "abort"):
            effect = f"This gate declares on_reject: {gate.on_reject}. " + effect
        self.app.push_screen(
            ConfirmScreen(
                title,
                effect,
                confirm_label=choice,
                note="Persisted engine state stays authoritative after submission.",
            ),
            self._after_choice,
        )

    def _after_choice(self, confirmed: bool | None) -> None:
        pending = self._pending_decision
        self._pending_decision = None
        if not confirmed or pending is None:
            return
        choice, token = pending
        self._submit_decision(choice, token)

    @work(thread=True)
    def _submit_decision(self, choice: str, token: str | None) -> None:
        error = ""
        try:
            self.session.submit_decision(choice, token)
        except Exception as exc:  # noqa: BLE001 - refusal stays diagnostic
            error = str(exc)
        self.app.call_from_thread(self._after_submission, error)

    def _after_submission(self, error: str) -> None:
        if error:
            self._diagnostic = error
        else:
            self._show_transient("Choice submitted once.")
        self._review_loaded = False
        self._refresh()

    def on_option_list_option_highlighted(self, event) -> None:
        if event.option.id is None:
            return
        if event.option_list.id == "runway-graph":
            self._selected_node_id = str(event.option.id)
            self.query_one(Runway).selected_node_id = self._selected_node_id
            self._update_focus(self._snapshot_now())
            event.stop()
        elif event.option_list.id in ("feature-files", "changed-files"):
            self._selected_review_path = str(event.option.id)
            self._full_file = False
            self._load_document(self._selected_review_path)
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
        self.app.push_screen(AbortingScreen())
        self._run_abort()

    @work(thread=True)
    def _run_abort(self) -> None:
        try:
            self.session.abort()
        finally:
            self.app.call_from_thread(self.app.exit)

    def action_quit(self) -> None:
        if self._snapshot_now().terminal:
            self.app.exit()
            return
        self.action_abort()

    def action_acknowledge(self) -> None:
        snapshot = self._snapshot_now()
        if snapshot.terminal:
            self.app.exit()
            return
        if self._focus_mode != "gate":
            return
        if not gate_decision(snapshot).selectable:
            return
        selected = self.query_one(GateOptions).selected_option()
        if selected is not None:
            self._confirm_choice(selected)

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())
