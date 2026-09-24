"""Resume lifecycle behavior mixed into the cockpit screen."""

from __future__ import annotations

from textual import work

from ..view_model import resume_decision
from .confirm import ConfirmScreen


class ResumeMixin:
    """The confirmed, write-once Resume action for an adopted failed run.

    The host screen owns the composed cockpit widgets, the ``session``, the
    ``_snapshot_now`` accessor, the ``_diagnostic`` attribute, and the refresh /
    transient-feedback helpers.
    """

    #: Token of the confirmation currently on screen, if any.
    _pending_resume: str | None = None

    def _resume_closing(self, snapshot) -> str:
        """The outcome-surface closing hint, offering Resume when available."""
        if resume_decision(snapshot).available:
            return "Press r to resume this run, or enter to close."
        return "Press enter to close."

    def action_resume(self) -> None:
        snapshot = self._snapshot_now()
        decision = resume_decision(snapshot)
        if not decision.available:
            return
        accessor = getattr(self.session, "resume_decision", None)
        session_decision = accessor() if callable(accessor) else None
        token = session_decision.token if session_decision is not None else None
        if not token:
            return
        self._pending_resume = token
        if decision.nested and decision.parent_label:
            heading = f"Resume {decision.parent_label} (nested step)?"
            effect = (
                f"The recorded current step is {decision.step_label}, nested inside "
                f"{decision.parent_label}. Resuming re-runs {decision.parent_label} and its "
                "whole nested body, then the rest of the run."
            )
        else:
            heading = f"Resume from {decision.step_label}?"
            effect = (
                f"The run resumes from {decision.step_label}. That step and the rest of the "
                "run execute again; earlier completed steps stay untouched."
            )
        self.app.push_screen(
            ConfirmScreen(
                heading,
                effect,
                confirm_label="Resume run",
                note="Persisted engine state stays authoritative after submission.",
            ),
            self._after_resume,
        )

    def _after_resume(self, confirmed: bool | None) -> None:
        token = self._pending_resume
        self._pending_resume = None
        if not confirmed or not token:
            return
        self._submit_resume(token)

    @work(thread=True)
    def _submit_resume(self, token: str) -> None:
        error = ""
        try:
            self.session.resume_run(token)
        except Exception as exc:  # noqa: BLE001 - refusal stays diagnostic
            error = str(exc)
        self.app.call_from_thread(self._after_resume_submission, error)

    def _after_resume_submission(self, error: str) -> None:
        if error:
            self._diagnostic = error
        else:
            self._show_transient("Resume submitted once.")
        self._review_loaded = False
        self._refresh()
