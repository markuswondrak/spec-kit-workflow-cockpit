"""Normalize engine output: decode, strip controls, bound the retained tail."""

from __future__ import annotations

import codecs
import re
from collections import deque

_OSC = r"\x1b\][^\x07]*(?:\x07|\x1b\\)"
_CSI = r"\x1b\[[0-?]*[ -/]*[@-~]"
_CHARSET = r"\x1b[()][0-9A-Za-z]"
_FE_ESCAPE = r"\x1b[@-Z\\-_]"
_ANSI_RE = re.compile(f"{_OSC}|{_CSI}|{_CHARSET}|{_FE_ESCAPE}")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class OutputNormalizer:
    """Accumulate complete lines plus the current partial line.

    The retained tail is bounded; when it overflows the oldest lines are
    dropped and ``truncated`` becomes true so the UI can show one marker.
    """

    def __init__(self, max_lines: int = 2000) -> None:
        self.max_lines = max_lines
        self._lines: deque[str] = deque(maxlen=max_lines)
        self._partial = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.truncated = False
        self._emitted = 0

    @property
    def partial(self) -> str:
        return self._partial

    @property
    def emitted(self) -> int:
        """Total completed lines ever emitted, independent of the bounded tail."""
        return self._emitted

    @property
    def lines(self) -> list[str]:
        return list(self._lines)

    def tail(self, count: int) -> list[str]:
        if count <= 0:
            return []
        return list(self._lines)[-count:]

    @staticmethod
    def _clean(text: str) -> str:
        text = _ANSI_RE.sub("", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return _CONTROL_RE.sub("", text)

    def feed(self, data: bytes | str) -> list[str]:
        """Feed a chunk; return the newly completed lines."""
        text = self._decoder.decode(data) if isinstance(data, bytes) else data
        text = self._clean(text)
        self._partial += text
        if "\n" not in self._partial:
            return []
        parts = self._partial.split("\n")
        self._partial = parts.pop()
        completed = [line for line in parts]
        for line in completed:
            if len(self._lines) == self.max_lines:
                self.truncated = True
            self._lines.append(line)
        self._emitted += len(completed)
        return completed
