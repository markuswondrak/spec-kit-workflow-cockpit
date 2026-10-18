"""Line-delimited JSON framing, envelopes, and error codes for the host.

Transport: one UTF-8 JSON object per ``\\n``-terminated line, both directions,
with a 1 MiB maximum line. A request carries an ``id`` that is echoed verbatim
on its response; an event carries no ``id``. Every message carries
``protocol_version``, and every failure is a structured error object rather than
a bare message (FR-019).

This module is pure: it frames bytes and builds mappings. It opens no socket, so
the framing rules are testable without a host.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

#: Protocol shape version; bumped when the message shape changes (FR-019).
PROTOCOL_VERSION = 1

#: Maximum line length accepted in either direction (1 MiB).
MAX_LINE_BYTES = 1024 * 1024

#: Structured error codes named by contracts/host-protocol.md.
HOST_ALREADY_RUNNING = "host_already_running"
RUN_IN_PROGRESS = "run_in_progress"
UNDECLARED_OPTION = "undeclared_option"
CLAIM_LIVE_FOREIGN = "claim_live_foreign"
GATE_NOT_OPEN = "gate_not_open"
STALE_TOKEN = "stale_token"
UNKNOWN_OP = "unknown_op"
BAD_REQUEST = "bad_request"
USER_ONLY = "user_only"
SOCKET_PATH_TOO_LONG = "socket_path_too_long"

#: Every code a client can receive, so tests and docs can enumerate them.
ERROR_CODES = frozenset(
    {
        HOST_ALREADY_RUNNING,
        RUN_IN_PROGRESS,
        UNDECLARED_OPTION,
        CLAIM_LIVE_FOREIGN,
        GATE_NOT_OPEN,
        STALE_TOKEN,
        UNKNOWN_OP,
        BAD_REQUEST,
        USER_ONLY,
        SOCKET_PATH_TOO_LONG,
    }
)

#: Pushed event names, ordered per connection by ``seq``.
GATE_OPEN = "gate_open"
STATUS_CHANGED = "status_changed"
TERMINAL = "terminal"
EVENTS = frozenset({GATE_OPEN, STATUS_CHANGED, TERMINAL})

#: Owner-view operations (FR-020).
OPERATIONS = frozenset(
    {"list", "validate", "start", "status", "gate", "decide", "abort", "adopt", "resume"}
)

#: Operations that change run or ownership state and must serialise.
MUTATING_OPERATIONS = frozenset({"start", "decide", "abort", "adopt", "resume"})


class ProtocolError(Exception):
    """Raised when a frame cannot be decoded as one request object."""


class HostError(Exception):
    """A structured refusal carrying a protocol error code."""

    def __init__(
        self,
        code: str,
        message: str,
        action: str = "",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.details = dict(details) if details else {}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "action": self.action,
        }
        if self.details:
            payload["details"] = self.details
        return payload


def error_object(
    code: str,
    message: str,
    action: str = "",
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A structured error object, the only failure shape on the wire."""
    return HostError(code, message, action, details).to_dict()


def encode(message: Mapping[str, Any]) -> bytes:
    """One UTF-8 JSON object terminated by a newline."""
    return (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")


def decode(line: bytes | str) -> dict[str, Any]:
    """Decode one frame into a JSON object; raise :class:`ProtocolError` otherwise."""
    if isinstance(line, bytes):
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError(f"the frame is not valid UTF-8: {exc}") from exc
    else:
        text = line
    text = text.strip()
    if not text:
        raise ProtocolError("the frame is empty")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"the frame is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProtocolError("the frame must be a JSON object")
    return data


def correlation_id(request: Mapping[str, Any] | None) -> str | None:
    """The request id echoed verbatim, or ``None`` when it is unparseable/absent."""
    if not isinstance(request, Mapping):
        return None
    value = request.get("id")
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return None


def request(op: str, args: Mapping[str, Any] | None = None, *, id: str | None = "1") -> dict[str, Any]:
    message: dict[str, Any] = {"id": id, "op": op}
    if args is not None:
        message["args"] = dict(args)
    return message


def success(request_id: str | None, result: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": request_id,
        "ok": True,
        "result": dict(result) if result is not None else {},
        "protocol_version": PROTOCOL_VERSION,
    }


def failure(
    request_id: str | None,
    error: HostError | Mapping[str, Any],
) -> dict[str, Any]:
    payload = error.to_dict() if isinstance(error, HostError) else dict(error)
    return {
        "id": request_id,
        "ok": False,
        "error": payload,
        "protocol_version": PROTOCOL_VERSION,
    }


def event(name: str, data: Mapping[str, Any] | None, seq: int) -> dict[str, Any]:
    """A pushed event; it carries no ``id`` so it can never be mistaken for a reply."""
    return {
        "event": name,
        "data": dict(data) if data is not None else {},
        "seq": seq,
        "protocol_version": PROTOCOL_VERSION,
    }


@dataclass(frozen=True)
class Frame:
    """One framed line, or a marker that an over-long line was dropped."""

    line: bytes | None = None
    oversized: bool = False


@dataclass
class FrameBuffer:
    """Split a byte stream into newline-terminated frames with a hard size bound.

    An over-long line produces exactly one ``oversized`` frame; the rest of that
    line is discarded and the connection stays open (contract: over-size ->
    ``bad_request``, connection kept). The buffer never grows past the bound, so
    a peer that never sends a newline cannot exhaust memory.
    """

    max_line_bytes: int = MAX_LINE_BYTES
    _buffer: bytearray = field(default_factory=bytearray)
    _dropping: bool = False

    def feed(self, data: bytes) -> list[Frame]:
        frames: list[Frame] = []
        self._buffer.extend(data)
        while True:
            index = self._buffer.find(b"\n")
            if index == -1:
                if len(self._buffer) > self.max_line_bytes:
                    self._buffer.clear()
                    if not self._dropping:
                        self._dropping = True
                        frames.append(Frame(oversized=True))
                break
            line = bytes(self._buffer[:index])
            del self._buffer[: index + 1]
            if self._dropping:
                self._dropping = False
                continue
            if len(line) > self.max_line_bytes:
                frames.append(Frame(oversized=True))
                continue
            frames.append(Frame(line=line))
        return frames
