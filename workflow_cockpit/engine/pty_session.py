"""Incremental, non-blocking reads from an internal output PTY."""

from __future__ import annotations

import errno
import os
import threading
from collections.abc import Callable

_IO_ERRORS = (errno.EIO, errno.EBADF, errno.EINVAL)


class PtySession:
    """Read one PTY master in a background thread; never write to it."""

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

    def close(self) -> None:
        self._stop.set()
        try:
            os.close(self.master_fd)
        except OSError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
