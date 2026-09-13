"""Widgets for the paused-gate Feature Files review surface."""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from ...services.review import ReviewDocument
from ..palette import FAULT, FOG, HOLD, PAPER


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
            options.append(Option(_text((f"{feature_file.label}{suffix}", PAPER)), id=feature_file.path))
        self.clear_options()
        self.add_options(options)
        if options:
            index_by_path = {str(option.id): index for index, option in enumerate(options)}
            preferred = live_path or selected_path or self.selected_path
            self.highlighted = index_by_path.get(preferred or "", 0)
            self.selected_path = str(options[self.highlighted].id)
            self.scroll_to(y=scroll_y, animate=False)
        else:
            self.selected_path = None


class ReviewDocumentView(Static):
    """Rendered current content of one feature file."""

    def show(self, document: ReviewDocument | None) -> None:
        if document is None:
            self.update(_text(("No feature files to review yet.", FOG)))
            return
        header = document.path
        if document.error:
            self.update(_text((header + "\n\n", PAPER), (document.error, FAULT)))
            return
        if document.binary:
            self.update(_text((header + "\n\n", PAPER), (document.note or "Binary file.", HOLD)))
            return
        body = document.text or "(empty file)"
        parts = [(header + "\n\n", PAPER), (body, PAPER)]
        if document.truncated:
            limit = document.limit_bytes or 0
            parts.append(("\n\n", PAPER))
            parts.append((f"Preview truncated at {limit} bytes; press f to load the full file.", HOLD))
        self.update(_text(*parts))


class GateOptions(OptionList):
    """Equal-weight declared gate choices; digits select by position."""

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
    ]

    def update_options(self, options: tuple[str, ...] | list[str]) -> None:
        highlighted = self.highlighted_option
        selected = str(highlighted.id) if highlighted is not None and highlighted.id is not None else None
        scroll_y = self.scroll_y
        items = [Option(_text((f"[{index}]  {option}", PAPER)), id=option) for index, option in enumerate(options, 1)]
        self.clear_options()
        self.add_options(items)
        if items:
            by_id = {str(option.id): index for index, option in enumerate(items)}
            self.highlighted = by_id.get(selected or "", 0)
            self.scroll_to(y=scroll_y, animate=False)

    def selected_option(self) -> str | None:
        option = self.highlighted_option
        if option is not None and option.id is not None:
            return str(option.id)
        return None
