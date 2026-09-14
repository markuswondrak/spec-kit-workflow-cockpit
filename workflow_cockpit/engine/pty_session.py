"""Incremental, non-blocking reads from an internal output PTY."""

from __future__ import annotations

import errno
import os
import threading
from collections.abc import Callable
from enum import Enum

_IO_ERRORS = (errno.EIO, errno.EBADF, errno.EINVAL)


class WriteOutcome(str, Enum):
    """Classification of one attempted PTY write.

    ``WRITTEN`` means the complete payload was accepted exactly once.
    ``NOT_WRITTEN`` means zero bytes reached the PTY. ``UNCERTAIN`` means a
    partial write or an ambiguous I/O failure occurred, so the input may or may
    not have been received; the caller must treat the attempt as consumed.
    """

    NOT_WRITTEN = "not_written"
    WRITTEN = "written"
    UNCERTAIN = "uncertain"


class PtySession:
    """Read one PTY master in a background thread; write only confirmed input."""

    def __init__(
        self,
        master_fd: int,
        on_chunk: Callable[[bytes], None],
        read_size: int = 65536,
    ) -> None:
        self.master_fd = master_fd
        self._on_chunk = on_chunk
        self._read_size = read_size
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.exit_reason: str | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="cockpit-pty", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data = os.read(self.master_fd, self._read_size)
            except OSError as exc:
                if exc.errno in _IO_ERRORS:
                    self.exit_reason = "closed"
                    break
                if self._stop.is_set():
                    break
                self.exit_reason = f"error:{exc.errno}"
                break
            if not data:
                self.exit_reason = "eof"
                break
            try:
                self._on_chunk(data)
            except Exception:
                self.exit_reason = "consumer"
                break

    def write(self, data: bytes) -> WriteOutcome:
        """Write the complete payload, classifying the result.

        Short writes are retried until the whole payload is accepted, and an
        interrupted ``os.write`` (``EINTR``) is retried. The returned
        classification lets the caller keep write-once protection for a partial
        or ambiguous write instead of treating it as complete.
        """
        if self._stop.is_set():
            return WriteOutcome.NOT_WRITTEN
        if not data:
            return WriteOutcome.WRITTEN
        written = 0
        while written < len(data):
            try:
                count = os.write(self.master_fd, data[written:])
            except InterruptedError:
                continue
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                return WriteOutcome.UNCERTAIN if written else WriteOutcome.NOT_WRITTEN
            if count <= 0:
                return WriteOutcome.UNCERTAIN if written else WriteOutcome.NOT_WRITTEN
            written += count
        return WriteOutcome.WRITTEN

    def close(self) -> None:
        self._stop.set()
        try:
            os.close(self.master_fd)
        except OSError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
