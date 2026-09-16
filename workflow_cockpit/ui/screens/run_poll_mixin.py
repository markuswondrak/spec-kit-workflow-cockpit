"""Off-render-path polling, snapshot publication, and feedback for the cockpit.

The host screen owns the composed widgets, the ``session``, the render methods
(``_update_focus``/``_update_output``), the selection attributes, and
``_diagnostic``. This mixin owns the 250 ms poll request, the single-exclusive
snapshot and branch workers, the error strip, and transient success feedback.
"""

from __future__ import annotations

from textual import work

from ...services.snapshot import RunSnapshot
from ...session.polling import PollingLoop
from ..messages import SnapshotPublished
from ..view_model import gate_decision
from ..widgets import CommandRail, ErrorStrip

#: Independent, cached branch refresh cadence (seconds).
BRANCH_REFRESH_SECONDS = 1.0

#: Transient success feedback lifetime (seconds).
TRANSIENT_SECONDS = 2.0


class RunPollMixin:
    """Request snapshots off the render path and surface read failures."""

    def _init_run_poll(self, session) -> None:
        self.session = session
        self._loop = PollingLoop(session)
        self._snapshot = None
        self._poll_error = ""
        self._branch_pending = False
        self._transient_timer = None

    # -- snapshot production ------------------------------------------

    def _snapshot_now(self) -> RunSnapshot:
        # Never create a snapshot from the UI thread. Before the first worker
        # result arrives, the empty value simply disables data-dependent work.
        return self._snapshot or RunSnapshot(run_id="")

    def _request_poll(self, *, force: bool = False) -> None:
        if self._loop.begin(force=force):
            self._produce_snapshot()

    @work(thread=True, group="poll", exclusive=True)
    def _produce_snapshot(self) -> None:
        snapshot = self._loop.produce()
        self.post_message(SnapshotPublished(snapshot, self._loop.last_error))

    def on_snapshot_published(self, message: SnapshotPublished) -> None:
        if message.snapshot is not None:
            self._snapshot = message.snapshot
        self._poll_error = message.error
        self._apply_snapshot(self._snapshot_now())

    def _request_branch(self) -> None:
        if self._branch_pending:
            return
        self._branch_pending = True
        self._refresh_branch_worker()

    @work(thread=True, group="branch", exclusive=True)
    def _refresh_branch_worker(self) -> None:
        refresh = getattr(self.session, "refresh_branch", None)
        try:
            if callable(refresh):
                refresh()
        finally:
            self.app.call_from_thread(self._after_branch)

    def _after_branch(self) -> None:
        self._branch_pending = False
        self._request_poll(force=True)

    # -- error feedback -----------------------------------------------

    def _render_error_strip(self, snapshot: RunSnapshot) -> None:
        """Route every recoverable failure to one persistent, actionable strip."""
        messages = [snapshot.diagnostic, snapshot.context_error, self._poll_error]
        if self._diagnostic:
            messages.append(self._diagnostic)
        review = snapshot.review
        if review is not None and review.status == "error" and review.error:
            messages.append(review.error)
        strip = self.query_one(ErrorStrip)
        if not any(messages):
            strip.clear()
            return
        joined = "  /  ".join(message for message in messages if message)
        strip.show(f"{joined}    [state: {snapshot.status}]  next: {self._next_action(snapshot)}")

    @staticmethod
    def _next_action(snapshot: RunSnapshot) -> str:
        if snapshot.terminal:
            return "enter to close"
        if gate_decision(snapshot).selectable:
            return "choose a gate option"
        return "x to abort or wait for the run"

    def _show_transient(self, message: str) -> None:
        self.query_one(CommandRail).set_feedback(message)
        if self._transient_timer is not None:
            self._transient_timer.stop()
        self._transient_timer = self.set_timer(TRANSIENT_SECONDS, self._clear_transient)

    def _clear_transient(self) -> None:
        self._transient_timer = None
        self.query_one(CommandRail).set_feedback("")
