"""Review and gate-surface behavior mixed into the cockpit screen."""

from __future__ import annotations

from rich.text import Text
from textual import work
from textual.containers import VerticalScroll
from textual.widgets import Input, Static

from ...services.context_index import SKILL_GUIDANCE
from ...services.review import ReviewDocument
from ..editor import resolve_editor_command
from ..palette import palette
from ..view_model import gate_decision
from ..widgets import FeatureFileList, GateDecisionBar, MarkdownDocumentView, ReviewDocumentView


class ReviewMixin:
    """Feature Files and structured-gate rendering and actions.

    The host screen owns the composed cockpit widgets, the ``session``, the
    ``_snapshot_now`` accessor, and the selection/focus attributes.
    """

    # -- lifecycle -----------------------------------------------------

    #: Poll ticks between automatic paused review refreshes (0.25 s each).
    REVIEW_REFRESH_TICKS = 8

    def _maybe_load_review(self, snapshot) -> None:
        if snapshot.gate is None:
            self._review_loaded = False
            self._review_tick = 0
            return
        if not self._review_loaded:
            self._reload_review()
            return
        self._review_tick += 1
        if self._review_tick >= self.REVIEW_REFRESH_TICKS:
            self._review_tick = 0
            self._reload_review()

    def _reload_review(self) -> None:
        if self._review_pending:
            return
        self._review_pending = True
        self._refresh_review_worker(self._snapshot_now().run_id)

    @work(thread=True, group="review", exclusive=True)
    def _refresh_review_worker(self, run_id: str) -> None:
        try:
            review = self.session.refresh_review()
            error = ""
        except Exception as exc:
            review = None
            error = str(exc)
        self.app.call_from_thread(self._apply_review, run_id, review, error)

    def _apply_review(self, run_id: str, review, error: str) -> None:
        self._review_pending = False
        if self._snapshot_now().run_id != run_id:
            return
        if error:
            self._diagnostic = error
        self._review_loaded = True
        self._review_tick = 0
        self._refresh()

    # -- rendering -----------------------------------------------------

    def _render_gate(self, snapshot, step_label) -> None:
        decision = gate_decision(snapshot)
        self.query_one(GateDecisionBar).update_options(
            decision.options, selectable=decision.selectable, affordance=decision.affordance
        )
        self.query_one("#view-label", Static).update(Text.assemble(("GATE / REVIEW", f"bold {palette.hold}")))
        tone = {
            "fog": palette.fog,
            "fault": palette.fault,
            "hold": palette.hold,
            "paper": palette.paper,
        }.get(decision.tone, palette.fog)
        phase = "running" if snapshot.process_live else "paused"
        parts: list = [
            (f"{step_label}   /   engine {phase}\n\n", palette.paper),
            (decision.message + "\n\n", palette.hold),
            (decision.notice + "\n\n", tone),
        ]
        diagnostic = self._diagnostic or snapshot.diagnostic
        if diagnostic:
            parts.append((diagnostic + "\n\n", palette.fault))
        if snapshot.context_error:
            parts.append((snapshot.context_error + "\n\n", palette.fault))
        elif snapshot.context_path:
            parts.append(("context ", palette.fog))
            parts.append((snapshot.context_path + "\n", palette.cold))
            parts.append((SKILL_GUIDANCE + "\n\n", palette.fog))
        self.query_one("#overview-content", Static).update(Text.assemble(*parts))
        self.query_one("#decide-hint", Static).update(Text.assemble((decision.hint, palette.fog)))
        self._render_review_status(snapshot)
        self._render_review_files(snapshot)

    def _render_changes(self, snapshot) -> None:
        self.query_one("#view-label", Static).update(Text.assemble(("FEATURE FILES", f"bold {palette.paper}")))
        self._render_review_status(snapshot)
        self._render_review_files(snapshot)

    def _render_review_status(self, snapshot) -> None:
        review = snapshot.review
        diagnostic = self._diagnostic or snapshot.diagnostic
        if review is None:
            text = "refreshing" if self._review_pending else "no review data"
            tone = palette.fog
        else:
            where = review.feature_dir or "feature folder"
            text = f"{review.count} file(s) in {where}"
            tone = palette.fog
            if review.status == "error":
                text += "  /  refresh failed"
                tone = palette.fault
        if diagnostic:
            text += "  /  " + diagnostic
            tone = palette.fault
        self.query_one("#review-status", Static).update(Text.assemble((text, tone)))

    def _visible_files(self, snapshot):
        files = snapshot.review.files if snapshot.review else ()
        needle = self._filter.strip().lower()
        if needle:
            return tuple(item for item in files if needle in item.path.lower())
        return tuple(files)

    def _render_review_files(self, snapshot) -> None:
        files = self._visible_files(snapshot)
        file_list = self.query_one(FeatureFileList)
        if not files:
            file_list.update_files(())
            self._selected_review_path = None
            self._current_document = None
            if snapshot.review is not None and snapshot.review.status == "error":
                self._show_document(
                    ReviewDocument(
                        path="Feature Files",
                        error=snapshot.review.error or "Unable to refresh Feature Files.",
                    )
                )
            else:
                self._show_document(None)
            return
        file_list.update_files(files, self._selected_review_path)
        self._selected_review_path = file_list.selected_path
        self._load_document(self._selected_review_path)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "review-filter":
            return
        self._filter = event.value
        self._render_review_files(self._snapshot_now())

    def _show_document(self, document: ReviewDocument | None) -> None:
        """Render one document, swapping the plain and Markdown viewers.

        Scroll is preserved across a same-path refresh and reset when a
        different path (or the empty state) is shown.
        """
        plain = self.query_one(ReviewDocumentView)
        markdown = self.query_one(MarkdownDocumentView)
        path = document.path if document is not None else None
        same_path = path is not None and path == self._rendered_document_path
        scroll = self.query_one("#review-scroll", VerticalScroll)
        offset = scroll.scroll_y if same_path else 0
        if document is not None and document.markdown and not (document.binary or document.error):
            markdown.show(document)
            plain.display = False
            markdown.display = True
        else:
            markdown.display = False
            plain.display = True
            plain.show(document)
        self._rendered_document_path = path
        self.call_after_refresh(lambda: scroll.scroll_to(y=offset, animate=False))

    def _load_document(self, path: str | None) -> None:
        if not path:
            self._current_document = None
            self._show_document(None)
            return
        review = self._snapshot_now().review
        revision = review.revision if review is not None else -1
        key = (self._snapshot_now().run_id, path, self._full_file, revision)
        if key == self._document_key or key == self._document_pending_key:
            return
        self._document_pending_key = key
        self._load_document_worker(*key)

    @work(thread=True, group="review-document", exclusive=True)
    def _load_document_worker(self, run_id: str, path: str, full: bool, revision: int) -> None:
        try:
            document = self.session.review_document(path, full=full)
        except Exception as exc:
            document = ReviewDocument(path=path, error=str(exc))
        self.app.call_from_thread(self._apply_document, run_id, path, full, revision, document)

    def _apply_document(self, run_id: str, path: str, full: bool, revision: int, document) -> None:
        key = (run_id, path, full, revision)
        if self._document_pending_key == key:
            self._document_pending_key = None
        snapshot = self._snapshot_now()
        review = snapshot.review
        current_revision = review.revision if review is not None else -1
        if (
            snapshot.run_id != run_id
            or self._selected_review_path != path
            or self._full_file != full
            or current_revision != revision
        ):
            return
        self._current_document = document
        self._document_key = key
        self._show_document(document)

    # -- view actions --------------------------------------------------

    def action_full_file(self) -> None:
        if self._focus_mode not in ("gate", "changes") or not self._selected_review_path:
            return
        self._full_file = True
        self._load_document(self._selected_review_path)

    def action_filter(self) -> None:
        if self._focus_mode not in ("gate", "changes"):
            return
        self.query_one("#review-filter", Input).focus()

    # -- editor --------------------------------------------------------

    def action_open_editor(self) -> None:
        self._diagnostic = ""
        if not self._editor_available():
            if not self._editor_env():
                self._diagnostic = "$EDITOR is unset; set it to edit files."
                self._update_focus(self._snapshot_now())
            return
        path = self.session.resolve_path(self._selected_review_path)
        if path is None or not path.is_file():
            self._diagnostic = "That file cannot be opened in the editor."
            self._update_focus(self._snapshot_now())
            return
        argv = resolve_editor_command(self._editor_env(), path)
        if argv is None:
            self._diagnostic = "$EDITOR is invalid; fix it to edit files."
            self._update_focus(self._snapshot_now())
            return
        try:
            self._run_editor(argv)
        except Exception as exc:
            self._diagnostic = f"Editor failed: {exc}"
        self._review_loaded = False
        self._reload_review()
        self._update_focus(self._snapshot_now())

    def _editor_available(self) -> bool:
        snapshot = self._snapshot_now()
        document = self._current_document
        # A gate wait is a gate wait: a live process blocked on its private PTY
        # prompt is awaiting a decision, not running an automated editing step.
        if snapshot.gate is None or self._focus_mode not in ("gate", "changes"):
            return False
        if document is None or document.binary or document.error:
            return False
        if not self._editor_env():
            return False
        return True

    def _run_editor(self, argv) -> None:
        from textual.app import SuspendNotSupported

        try:
            with self.app.suspend():
                self._editor_launcher(argv, self.session.project_root)
        except SuspendNotSupported:
            self._editor_launcher(argv, self.session.project_root)
