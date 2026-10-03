"""Widgets for the paused-gate Feature Files review surface."""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Markdown, OptionList, Select, Static
from textual.widgets.option_list import Option

from ...services.review import ReviewDocument
from ..palette import palette


def _text(*parts) -> Text:
    return Text.assemble(*parts)


class FeatureFileList(OptionList):
    """Compact feature-file index that retains selection across refresh."""

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.selected_path: str | None = None

    def update_files(self, files, selected_path: str | None = None) -> None:
        scroll_y = self.scroll_y
        live = self.highlighted_option
        live_path = str(live.id) if live is not None and live.id is not None else None
        options: list[Option] = []
        for feature_file in files:
            suffix = "  (binary)" if feature_file.binary else ""
            options.append(Option(_text((f"{feature_file.label}{suffix}", palette.paper)), id=feature_file.path))
        self.clear_options()
        self.add_options(options)
        if options:
            index_by_path = {str(option.id): index for index, option in enumerate(options)}
            # The caller-supplied path is the single source of truth; the live
            # highlight is only a fallback when no explicit selection is known.
            preferred = selected_path or live_path or self.selected_path
            with self.prevent(OptionList.OptionHighlighted):
                self.highlighted = index_by_path.get(preferred or "", 0)
            self.selected_path = str(options[self.highlighted].id)
            self.scroll_to(y=scroll_y, animate=False)
        else:
            self.selected_path = None


class FeatureFileSelect(Select):
    """Narrow-viewport file selector mirroring the shared review selection.

    Presentation only: it renders the already-filtered files and posts the
    chosen path so the screen routes it through the same ``_load_document``
    path the ``OptionList`` uses. It never owns selection state itself.
    """

    class FileChosen(Message):
        """Posted when the operator picks a feature file from the combobox."""

        def __init__(self, path: str) -> None:
            super().__init__()
            self.path = path

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("prompt", "select file")
        super().__init__((), *args, **kwargs)
        self._signature: tuple | None = None

    def update_files(self, files, selected_path: str | None = None) -> None:
        options = []
        for feature_file in files:
            suffix = "  (binary)" if feature_file.binary else ""
            options.append((f"{feature_file.label}{suffix}", feature_file.path))
        # The review surface re-renders on every poll; rebuilding the options
        # would close an overlay the operator is still using. Only touch the
        # control when the filtered set or the shared selection actually moved.
        signature = (selected_path, tuple(options))
        if signature == self._signature:
            return
        self._signature = signature
        with self.prevent(Select.Changed):
            self.set_options(options)
            if selected_path is not None and any(value == selected_path for _, value in options):
                self.value = selected_path
        self.disabled = not options

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()
        if event.value is Select.NULL:
            return
        self.post_message(self.FileChosen(str(event.value)))


class ReviewDocumentView(Static):
    """Rendered current content of one feature file."""

    def show(self, document: ReviewDocument | None) -> None:
        if document is None:
            self.update(_text(("No feature files to review yet.", palette.fog)))
            return
        header = document.display or document.path
        if document.error:
            self.update(_text((header + "\n\n", palette.paper), (document.error, palette.fault)))
            return
        if document.binary:
            self.update(_text((header + "\n\n", palette.paper), (document.note or "Binary file.", palette.hold)))
            return
        body = document.text or "(empty file)"
        parts = [(header + "\n\n", palette.paper), (body, palette.paper)]
        if document.truncated:
            limit = document.limit_bytes or 0
            parts.append(("\n\n", palette.paper))
            parts.append((f"Preview truncated at {limit} bytes; press f to load the full file.", palette.hold))
        self.update(_text(*parts))


class MarkdownDocumentView(Markdown):
    """Formatted, read-only rendering of a Markdown feature file.

    The selected path leads as a bold line; the bounded preview and full-load
    semantics match the plain viewer. Links render styled but stay inert so the
    review surface never leaves the terminal.
    """

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("open_links", False)
        super().__init__(*args, **kwargs)
        self.display = False

    def show(self, document: ReviewDocument) -> None:
        label = document.display or document.path
        parts = [f"**{label}**", "", document.text or "(empty file)"]
        if document.truncated:
            limit = document.limit_bytes or 0
            parts.append("")
            parts.append(f"_Preview truncated at {limit} bytes; press f to load the full file._")
        self.update("\n".join(parts))
