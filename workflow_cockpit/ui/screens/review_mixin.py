"""Review and gate-surface behavior mixed into the cockpit screen."""

from __future__ import annotations

from rich.text import Text
from textual import work
from textual.widgets import Input, Static

from ...services.review import ChangeKind, ReviewDocument
from ..editor import resolve_editor_command
from ..palette import FAULT, FOG, HOLD, PAPER
from ..widgets import ChangedFileList, GateOptions, ReviewDocumentView


class ReviewMixin:
    """Worktree Changes and structured-gate rendering and actions.

    The host screen owns the composed cockpit widgets, the ``session``, the
    ``_snapshot_now`` accessor, and the selection/focus attributes.
    """

    # -- lifecycle -----------------------------------------------------

    #: Poll ticks between automatic paused review refreshes (0.25 s each).
    REVIEW_REFRESH_TICKS = 8

    def _maybe_load_review(self, snapshot) -> None:
        if snapshot.status != "paused":
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
        gate = snapshot.gate
        options = gate.options if gate and gate.structured and not snapshot.process_live else ()
        self.query_one(GateOptions).update_options(options)
        self.query_one("#view-label", Static).update(Text.assemble(("GATE / PAUSED", f"bold {HOLD}")))
        message = gate.message if gate else "The engine is paused."
        if gate is None:
            notice, tone = "This pause is not a declared gate; only Abort is available.", FOG
        elif gate.malformed:
            notice, tone = "The persisted gate result is missing options; only Abort is available.", FAULT
        elif not gate.structured:
            notice, tone = (
                "This gate declares no verdict_input; an interactive resume is required (later work).",
                FOG,
            )
        else:
            notice, tone = "Choose an option, then confirm. Opening files is optional.", FOG
        parts: list = [
            (f"{step_label}   /   engine paused\n\n", PAPER),
            (message + "\n\n", HOLD),
            (notice + "\n\n", tone),
        ]
        diagnostic = self._diagnostic or snapshot.diagnostic
        if diagnostic:
            parts.append((diagnostic + "\n\n", FAULT))
        self.query_one("#overview-content", Static).update(Text.assemble(*parts))
        structured = gate is not None and gate.structured and not snapshot.process_live
        hint = "1..N or enter  confirm selected" if structured else "structured selection unavailable"
        self.query_one("#decide-hint", Static).update(Text.assemble((hint, FOG)))
        self._render_review_status(snapshot)
        self._render_review_files(snapshot)

    def _render_changes(self, snapshot) -> None:
        self.query_one("#view-label", Static).update(Text.assemble(("WORKTREE CHANGES", f"bold {PAPER}")))
        self._render_review_status(snapshot)
        self._render_review_files(snapshot)

    def _render_review_status(self, snapshot) -> None:
        review = snapshot.review
        diagnostic = self._diagnostic or snapshot.diagnostic
        if review is None:
            text = "refreshing" if self._review_pending else "no review data"
            tone = FOG
        else:
            baseline = (review.baseline or "start")[:7]
            text = f"{review.count} file(s) vs {baseline}"
            tone = FOG
            if review.status == "error":
                text += "  /  refresh failed"
                tone = FAULT
        if diagnostic:
            text += "  /  " + diagnostic
            tone = FAULT
        self.query_one("#review-status", Static).update(Text.assemble((text, tone)))

    def _visible_files(self, snapshot):
        files = snapshot.review.files if snapshot.review else ()
        needle = self._filter.strip().lower()
        if needle:
            return tuple(item for item in files if needle in item.path.lower())
        return tuple(files)

    def _render_review_files(self, snapshot) -> None:
        files = self._visible_files(snapshot)
        file_list = self.query_one(ChangedFileList)
        if not files:
            file_list.update_files(())
            self._selected_review_path = None
            self._current_document = None
            if snapshot.review is not None and snapshot.review.status == "error":
                self.query_one(ReviewDocumentView).show(
                    ReviewDocument(
                        path="Worktree Changes",
                        view="review",
                        kind=ChangeKind.MODIFIED,
                        error=snapshot.review.error or "Unable to refresh Worktree Changes.",
                    )
                )
            else:
                self.query_one(ReviewDocumentView).show(None)
            return
        file_list.update_files(files, self._selected_review_path)
        self._selected_review_path = file_list.selected_path
        self._load_document(self._selected_review_path)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "review-filter":
            return
        self._filter = event.value
        self._render_review_files(self._snapshot_now())

    def _load_document(self, path: str | None) -> None:
        if not path:
            self._current_document = None
            self.query_one(ReviewDocumentView).show(None)
            return
        view = self._effective_view(path)
        review = self._snapshot_now().review
        revision = review.revision if review is not None else -1
        key = (self._snapshot_now().run_id, path, view, self._full_file, revision)
        if key == self._document_key or key == self._document_pending_key:
            return
        self._document_pending_key = key
        self._load_document_worker(*key)

    @work(thread=True, group="review-document", exclusive=True)
    def _load_document_worker(self, run_id: str, path: str, view: str, full: bool, revision: int) -> None:
        try:
            document = self.session.review_document(path, view, full=full)
        except Exception as exc:
            document = ReviewDocument(path=path, view=view, kind=ChangeKind.MODIFIED, error=str(exc))
        self.app.call_from_thread(self._apply_document, run_id, path, view, full, revision, document)

    def _apply_document(self, run_id: str, path: str, view: str, full: bool, revision: int, document) -> None:
        key = (run_id, path, view, full, revision)
        if self._document_pending_key == key:
            self._document_pending_key = None
        snapshot = self._snapshot_now()
        review = snapshot.review
        current_revision = review.revision if review is not None else -1
        if (
            snapshot.run_id != run_id
            or self._selected_review_path != path
            or self._effective_view(path) != view
            or self._full_file != full
            or current_revision != revision
        ):
            return
        self._current_document = document
        self._document_key = key
        self.query_one(ReviewDocumentView).show(document)

    # -- view switching ------------------------------------------------

    def _set_review_view(self, view: str) -> None:
        if self._focus_mode not in ("changes", "gate"):
            return
        self._review_view = view
        self._view_overridden = True
        self._full_file = False
        if self._selected_review_path:
            self._load_document(self._selected_review_path)

    def _effective_view(self, path: str) -> str:
        if self._view_overridden:
            return self._review_view
        review = self._snapshot_now().review
        changed = next((item for item in (review.files if review else ()) if item.path == path), None)
        if changed is not None and changed.kind is ChangeKind.ADDED and path.lower().endswith(".md"):
            return "rendered"
        return self._review_view

    def action_diff_view(self) -> None:
        self._set_review_view("diff")

    def action_rendered_view(self) -> None:
        self._set_review_view("rendered")

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
        if (
            snapshot.status != "paused"
            or snapshot.process_live
            or self._focus_mode not in ("gate", "changes")
        ):
            return False
        if document is None or document.kind is ChangeKind.DELETED or document.binary or document.error:
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
