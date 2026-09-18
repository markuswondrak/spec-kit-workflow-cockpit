"""Existing-run section for the launch screen.

The list is deliberately subordinate to the workflow cards: one compact row per
run, read-only values straight from the descriptor, and an explicit empty state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rich.text import Text
from textual import work
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from ...services.run_catalog import RunDescriptor
from ..palette import palette
from .confirm import ConfirmScreen

#: Explicit empty state for a project with no runs (FR-005, AC4).
NO_EXISTING_RUNS = "NO EXISTING RUNS"

#: Status grammar shared with the runway vocabulary.
STATUS_GRAMMAR: dict[str, tuple[str, str]] = {
    "paused": ("[!]", palette.hold),
    "completed": ("[x]", palette.signal),
    "failed": ("[X]", palette.fault),
    "aborted": ("[/]", palette.fault),
    "running": ("[>]", palette.signal),
    "initializing": ("[>]", palette.signal),
    "unusable": ("[X]", palette.fault),
}


def status_marker(descriptor: RunDescriptor) -> tuple[str, str]:
    """Return the ``[symbol]`` and tone for a descriptor's persisted status."""
    return STATUS_GRAMMAR.get(descriptor.status, ("[ ]", palette.fog))


def format_age(updated_at: str | None, *, now: datetime | None = None) -> str:
    """Render a persisted ``updated_at`` as a compact relative age."""
    if not updated_at:
        return ""
    try:
        parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    seconds = max(0.0, (reference - parsed).total_seconds())
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def render_descriptor(descriptor: RunDescriptor, *, now: datetime | None = None) -> Text:
    """Render one compact, single-line run row."""
    marker, tone = status_marker(descriptor)
    style = palette.paper if descriptor.adoptable else palette.fog
    parts: list = [(f"{marker}  ", tone), (descriptor.run_id, style)]
    if descriptor.workflow_id:
        parts.append(("  " + descriptor.workflow_id, palette.fog))
    if not descriptor.usable:
        parts.append((f"  unusable  {descriptor.reason}", palette.fault))
        return Text.assemble(*parts)
    status_label = descriptor.status
    if descriptor.current_step_id:
        status_label += f" @ {descriptor.current_step_id}"
    parts.append(("  " + status_label, tone))
    age = format_age(descriptor.updated_at, now=now)
    if age:
        parts.append(("  " + age, palette.cold))
    if descriptor.is_default:
        parts.append(("  default", palette.hold))
    if not descriptor.adoptable:
        parts.append(("  read-only", palette.cold))
    return Text.assemble(*parts)


class ExistingRunsList(OptionList):
    """Compact read-only list of discovered runs beneath the workflow picker."""

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._descriptors: tuple[RunDescriptor, ...] = ()

    @property
    def descriptors(self) -> tuple[RunDescriptor, ...]:
        return self._descriptors

    def set_descriptors(self, descriptors: tuple[RunDescriptor, ...]) -> None:
        self._descriptors = tuple(descriptors)
        self.clear_options()
        if not self._descriptors:
            self.add_options(
                [Option(Text(NO_EXISTING_RUNS, style=palette.fog), id=None, disabled=True)]
            )
            return
        self.add_options(
            [Option(render_descriptor(descriptor), id=descriptor.run_id) for descriptor in self._descriptors]
        )
        self.highlighted = 0

    def descriptor_at(self, index: int) -> RunDescriptor | None:
        if 0 <= index < len(self._descriptors):
            return self._descriptors[index]
        return None

    def selected_descriptor(self) -> RunDescriptor | None:
        index = self.highlighted
        if index is None:
            return None
        return self.descriptor_at(index)


class LaunchRunsMixin:
    """Discovery, refusal, adoption, inspection, and deletion for the launch screen."""

    session: Any
    _pending_adopt: str | None
    _pending_delete: str | None

    def _load_existing_runs(self) -> None:
        if not hasattr(self.session, "list_existing_runs"):
            return
        self._existing_runs_worker()

    @work(thread=True)
    def _existing_runs_worker(self) -> None:
        error = ""
        descriptors: tuple = ()
        try:
            descriptors = tuple(self.session.list_existing_runs())
        except Exception as exc:  # noqa: BLE001 - discovery never crashes the screen
            error = str(exc)
        self.app.call_from_thread(self._apply_existing_runs, descriptors, error)

    def _apply_existing_runs(self, descriptors: tuple, error: str) -> None:
        try:
            listing = self.query_one("#existing-runs", ExistingRunsList)
        except NoMatches:
            return
        if error:
            listing.set_descriptors(())
            self._show_validation(error)
            return
        listing.set_descriptors(descriptors)
        try:
            note = self.query_one("#existing-runs-note", Static)
        except NoMatches:
            return
        if descriptors:
            adoptable = sum(1 for descriptor in descriptors if descriptor.adoptable)
            note.update(
                Text.assemble(
                    (f"{len(descriptors)} run(s)", palette.fog),
                    (f"   ·   {adoptable} adoptable", palette.hold),
                )
            )
        else:
            note.update(Text.assemble(("Start a new run; nothing to resume yet.", palette.fog)))

    def _show_validation(self, message: str) -> None:
        try:
            self.query_one("#validation", Static).update(Text.assemble((message, palette.fault)))
        except NoMatches:
            pass

    def _select_existing_run(self, index: int) -> None:
        listing = self.query_one("#existing-runs", ExistingRunsList)
        descriptor = listing.descriptor_at(index)
        if descriptor is None:
            return
        if descriptor.adoptable:
            self._begin_adopt(descriptor)
        elif descriptor.viewable:
            self._begin_inspect(descriptor)
        else:
            self._show_validation(self._refusal(descriptor))

    @staticmethod
    def _refusal(descriptor: RunDescriptor) -> str:
        if not descriptor.usable:
            return f"This run cannot be used: {descriptor.reason}."
        if not descriptor.launch_copy:
            return "This run has no launch-copy workflow definition; it cannot be viewed."
        return "This run cannot be viewed."

    def _begin_adopt(self, descriptor: RunDescriptor) -> None:
        self._pending_adopt = descriptor.run_id
        self.app.push_screen(
            ConfirmScreen(
                "Adopt this paused run?",
                f"Cockpit will bind run {descriptor.run_id} and continue its declared gate. "
                "The engine is not started until you confirm a decision.",
                confirm_label="Adopt run",
                note="The existing run files stay authoritative.",
            ),
            self._after_adopt_confirm,
        )

    def _after_adopt_confirm(self, confirmed: bool | None) -> None:
        run_id = self._pending_adopt
        self._pending_adopt = None
        if not confirmed or run_id is None:
            return
        self._adopt_worker(run_id)

    @work(thread=True)
    def _adopt_worker(self, run_id: str) -> None:
        error = ""
        try:
            self.session.adopt(run_id)
        except Exception as exc:  # noqa: BLE001 - refusal stays diagnostic
            error = str(exc)
        self.app.call_from_thread(self._finish_adopt, error)

    def _begin_inspect(self, descriptor: RunDescriptor) -> None:
        self._pending_adopt = descriptor.run_id
        self.app.push_screen(
            ConfirmScreen(
                "Inspect this run (view only)?",
                f"Cockpit will open run {descriptor.run_id} in read-only mode. "
                "You can observe execution, Feature Files, and state without lifecycle ownership.",
                confirm_label="Inspect run",
                note="Gate decisions and abort are disabled in view-only mode.",
            ),
            self._after_inspect_confirm,
        )

    def _after_inspect_confirm(self, confirmed: bool | None) -> None:
        run_id = self._pending_adopt
        self._pending_adopt = None
        if not confirmed or run_id is None:
            return
        self._inspect_worker(run_id)

    @work(thread=True)
    def _inspect_worker(self, run_id: str) -> None:
        error = ""
        try:
            self.session.inspect(run_id)
        except Exception as exc:  # noqa: BLE001 - refusal stays diagnostic
            error = str(exc)
        self.app.call_from_thread(self._finish_adopt, error)

    def _finish_adopt(self, error: str) -> None:
        if error:
            self._show_validation(error)
            return
        from .cockpit import CockpitScreen

        self.app.switch_screen(CockpitScreen(self.session))

    def _show_notice(self, message: str) -> None:
        try:
            self.query_one("#validation", Static).update(Text.assemble((message, palette.signal)))
        except NoMatches:
            pass

    def action_delete_run(self) -> None:
        try:
            listing = self.query_one("#existing-runs", ExistingRunsList)
        except NoMatches:
            return
        if not listing.has_focus:
            return
        descriptor = listing.selected_descriptor()
        if descriptor is None:
            return
        self._pending_delete = descriptor.run_id
        self.app.push_screen(
            ConfirmScreen(
                "Delete this run?",
                f"This permanently removes .specify/workflows/runs/{descriptor.run_id}/ "
                "and its persisted state, log, and launch copy.",
                confirm_label="Delete run",
                note="This cannot be undone and is not engine-owned cleanup.",
                destructive=True,
                eyebrow="DELETE RUN",
            ),
            self._after_delete_confirm,
        )

    def _after_delete_confirm(self, confirmed: bool | None) -> None:
        run_id = self._pending_delete
        self._pending_delete = None
        if not confirmed or run_id is None:
            return
        self._delete_worker(run_id)

    @work(thread=True)
    def _delete_worker(self, run_id: str) -> None:
        error = ""
        try:
            self.session.delete_existing_run(run_id)
        except Exception as exc:  # noqa: BLE001 - refusal stays diagnostic
            error = str(exc)
        self.app.call_from_thread(self._finish_delete, run_id, error)

    def _finish_delete(self, run_id: str, error: str) -> None:
        if error:
            self._show_validation(error)
            return
        self._show_notice(f"Deleted run {run_id}.")
        self._load_existing_runs()
