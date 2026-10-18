"""The asyncio Unix-socket host: bind uniqueness, dispatch, events, lifetime.

One host serves one worktree. It binds ``<worktree>/.workflow-cockpit.sock``,
probes the path first so a dead remnant never blocks a new host and a live host
is refused with a structured error, and keeps the kernel's single-bind guarantee
as the final word (research R5). Clients are stateless: any connection may issue
any operation, a reconnecting frontend is the same controller, and pushed events
fan out to every connected client ordered by ``seq`` (research R6).

Blocking session work runs in worker threads, so the event loop that reads
sockets and evaluates lifetime never stalls.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import os
import socket
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import protocol as p
from .lifetime import HostLifetime, catchable_death_abort
from .operations import HostOperations, gate_payload, run_summary

_LOG = logging.getLogger(__name__)

#: Socket file name at the worktree root (gitignored).
SOCKET_NAME = ".workflow-cockpit.sock"

#: Conservative AF_UNIX path bound: Linux allows 108 bytes, macOS 104.
AF_UNIX_MAX_PATH = 104

#: Poll cadence for events and lifetime; the session's own cadence is 250 ms.
POLL_SECONDS = 0.25

#: Read chunk for one connection.
READ_CHUNK = 64 * 1024

#: Bound for the initial status wait in the launcher.
STATUS_TIMEOUT_SECONDS = 15.0


class HostBindError(Exception):
    """Raised when the socket cannot be bound; carries a structured error."""

    def __init__(self, error: p.HostError) -> None:
        super().__init__(error.message)
        self.error = error


def socket_path_for(project_root: Path | str) -> Path:
    return Path(project_root) / SOCKET_NAME


def check_socket_path(path: Path) -> None:
    """Refuse a socket path the kernel cannot represent, before any bind attempt."""
    encoded = len(str(path).encode("utf-8"))
    if encoded >= AF_UNIX_MAX_PATH:
        raise HostBindError(
            p.HostError(
                p.SOCKET_PATH_TOO_LONG,
                (
                    f"The worktree path is too long for a Unix socket: {encoded} bytes, "
                    f"limit {AF_UNIX_MAX_PATH}."
                ),
                "move the worktree to a shorter path",
                {"path": str(path), "bytes": encoded, "limit": AF_UNIX_MAX_PATH},
            )
        )


def probe_socket(path: Path) -> bool:
    """True when a live host answers at ``path``; False for missing or stale."""
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return False
    if not stat.S_ISSOCK(mode):
        return False
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        probe.connect(str(path))
        return True
    except (TimeoutError, ConnectionRefusedError, FileNotFoundError, OSError):
        return False
    finally:
        probe.close()


def remove_stale_socket(path: Path) -> None:
    """Unlink a socket remnant left by a crashed host; never touch a live one."""
    if probe_socket(path):
        return
    try:
        path.unlink()
    except OSError:
        return


@dataclass
class _Client:
    """One connected controller connection."""

    writer: asyncio.StreamWriter
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class HostServer:
    """Own the socket, the connected clients, and the run-scoped lifetime."""

    def __init__(
        self,
        *,
        project_root: Path | str,
        operations: HostOperations,
        session: Any,
        lifetime: HostLifetime | None = None,
        socket_name: str = SOCKET_NAME,
        poll_seconds: float = POLL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.project_root = Path(project_root)
        self.operations = operations
        self.session = session
        self.lifetime = lifetime or HostLifetime()
        self.socket_path = self.project_root / socket_name
        self.poll_seconds = poll_seconds
        self._clock = clock
        self._clients: list[_Client] = []
        self._seq = 0
        self._stop = asyncio.Event()
        self._last_snapshot: Any = None
        self._last_gate_key: tuple | None = None
        self._last_status: str | None = None

    # -- binding --------------------------------------------------------

    def bind(self) -> None:
        """Validate the path and clear a stale remnant; refuse a live host."""
        check_socket_path(self.socket_path)
        if probe_socket(self.socket_path):
            raise HostBindError(
                p.HostError(
                    p.HOST_ALREADY_RUNNING,
                    f"A host is already serving this worktree at {self.socket_path}.",
                    "connect to the running host instead of starting a second one",
                    {"socket": str(self.socket_path)},
                )
            )
        remove_stale_socket(self.socket_path)

    async def serve(self) -> None:
        """Bind, serve until the lifetime releases, then free the claim and exit."""
        self.bind()
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.socket_path),
            limit=p.MAX_LINE_BYTES * 2,
        )
        poll = asyncio.create_task(self._poll_loop())
        try:
            async with server:
                await self._stop.wait()
        finally:
            poll.cancel()
            try:
                await poll
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - teardown
                pass
            await self._close_clients()
            self._unlink_socket()

    def _unlink_socket(self) -> None:
        try:
            self.socket_path.unlink()
        except OSError:
            return

    def request_stop(self) -> None:
        self._stop.set()

    # -- connections ----------------------------------------------------

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        client = _Client(writer=writer)
        self._clients.append(client)
        buffer = p.FrameBuffer()
        try:
            while True:
                data = await reader.read(READ_CHUNK)
                if not data:
                    break
                for frame in buffer.feed(data):
                    if frame.oversized:
                        await self._send(
                            client,
                            p.failure(
                                None,
                                p.HostError(
                                    p.BAD_REQUEST,
                                    f"The request line exceeds {p.MAX_LINE_BYTES} bytes.",
                                    "send one JSON object per line",
                                ),
                            ),
                        )
                        continue
                    await self._handle_line(client, frame.line or b"")
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        finally:
            if client in self._clients:
                self._clients.remove(client)
            try:
                writer.close()
            except OSError:
                pass

    async def _handle_line(self, client: _Client, line: bytes) -> None:
        try:
            request = p.decode(line)
        except p.ProtocolError as exc:
            await self._send(
                client,
                p.failure(None, p.HostError(p.BAD_REQUEST, str(exc), "send one JSON object per line")),
            )
            return
        request_id = p.correlation_id(request)
        op = request.get("op")
        args = request.get("args")
        if not isinstance(op, str) or not op:
            await self._send(
                client,
                p.failure(
                    request_id,
                    p.HostError(p.BAD_REQUEST, "The request needs an 'op' string.", "name an operation"),
                ),
            )
            return
        try:
            result = await self.operations.dispatch(op, args if isinstance(args, dict) else {})
        except p.HostError as exc:
            await self._send(client, p.failure(request_id, exc))
            return
        except Exception as exc:  # noqa: BLE001 - never kill a connection on one request
            _LOG.exception("host operation %s failed", op)
            await self._send(
                client,
                p.failure(request_id, p.HostError(p.BAD_REQUEST, str(exc), "read status and retry")),
            )
            return
        await self._send(client, p.success(request_id, result))

    async def _send(self, client: _Client, message: dict[str, Any]) -> None:
        async with client.lock:
            try:
                client.writer.write(p.encode(message))
                await client.writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError):
                return

    async def _broadcast(self, name: str, data: dict[str, Any]) -> None:
        self._seq += 1
        message = p.event(name, data, self._seq)
        for client in list(self._clients):
            await self._send(client, message)

    # -- events and lifetime --------------------------------------------

    async def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a poll failure must not kill the host
                _LOG.exception("host poll failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                continue

    async def _tick(self) -> None:
        snapshot = await asyncio.to_thread(self.session.snapshot)
        for name, data in self._events_for(self._last_snapshot, snapshot):
            await self._broadcast(name, data)
        self._last_snapshot = snapshot
        # A session with no run yet reports an "initializing" placeholder status;
        # lifetime must see that as "no run", not as a running step.
        run_id = getattr(snapshot, "run_id", "") or ""
        status = getattr(snapshot, "engine_status", None) or getattr(snapshot, "status", None)
        state = self.lifetime.observe(
            run_status=status if run_id else None,
            clients=len(self._clients),
            now=self._clock(),
        )
        if state == "releasing":
            await self._release(snapshot)

    def _events_for(self, previous: Any, current: Any) -> list[tuple[str, dict[str, Any]]]:
        """Events implied by the change between two snapshots, in a stable order."""
        events: list[tuple[str, dict[str, Any]]] = []
        status = getattr(current, "status", None)
        if status != self._last_status:
            self._last_status = status
            if previous is not None or status:
                events.append(
                    (
                        p.STATUS_CHANGED,
                        {
                            "run_id": getattr(current, "run_id", ""),
                            "status": status,
                            "current_step_id": getattr(current, "current_step_id", None),
                        },
                    )
                )
        gate = getattr(current, "gate", None)
        gate_key = None
        if gate is not None:
            gate_key = (gate.runtime_step_id, gate.state.value, gate.token)
        if gate_key != self._last_gate_key:
            self._last_gate_key = gate_key
            if gate is not None:
                events.append((p.GATE_OPEN, {"gate": gate_payload(gate), "run_id": getattr(current, "run_id", "")}))
        terminal = bool(getattr(current, "terminal", False))
        previous_terminal = bool(getattr(previous, "terminal", False)) if previous is not None else False
        if terminal and not previous_terminal:
            events.append((p.TERMINAL, {"run": run_summary(current)}))
        return events

    async def _release(self, snapshot: Any) -> None:
        """Free the claim, stop any live engine group, and exit (FR-026/027)."""
        self.lifetime.exit()
        if getattr(snapshot, "process_live", False):
            # A live group would be orphaned by exit: run the same bounded
            # best-effort abort the TUI runs, signalling only a verified group.
            await asyncio.to_thread(catchable_death_abort, self.session)
        await asyncio.to_thread(self.session.close)
        self._stop.set()

    async def _close_clients(self) -> None:
        for client in list(self._clients):
            try:
                client.writer.close()
            except OSError:
                continue
        self._clients.clear()

    # -- signals --------------------------------------------------------

    def install_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        """Abort catchably and release on SIGINT/SIGTERM/SIGHUP where available."""
        import signal as signal_module

        def _handler(signame: str) -> None:
            async def _run() -> None:
                await asyncio.to_thread(catchable_death_abort, self.session)
                await asyncio.to_thread(self.session.close)
                self._stop.set()

            loop.create_task(_run())

        for name in ("SIGINT", "SIGTERM", "SIGHUP"):
            sig = getattr(signal_module, name, None)
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, _handler, name)
            except (NotImplementedError, RuntimeError, ValueError):
                continue


def stale_remnant_errno(exc: OSError) -> bool:
    """True when ``exc`` is the kernel's "nobody is listening" signal."""
    return exc.errno in (errno.ECONNREFUSED, errno.ENOENT)
