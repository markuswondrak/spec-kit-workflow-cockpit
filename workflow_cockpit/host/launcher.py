"""Start and detach the headless host, and run it in the foreground child.

``workflow-cockpit serve`` must return control to the shell while a host keeps
owning the run. The parent probes the socket, refuses a second host with a
structured error, spawns a detached child with ``start_new_session=True`` (no
double fork), waits until the child's socket answers ``status``, prints that
result, and exits (research R4). The child runs the asyncio server in the
foreground of its own session, so it stays the process-group parent of the engine
(ADR-0006).
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from ..bootstrap.compatibility import Compatibility, CompatibilityError, CompatibilityResult
from ..session.cockpit_session import CockpitSession
from ..session.dependencies import CockpitEnvironment, CockpitServices, EngineRuntime
from . import protocol as p
from .lifetime import HostLifetime
from .operations import HostOperations
from .server import (
    SOCKET_NAME,
    STATUS_TIMEOUT_SECONDS,
    HostBindError,
    HostServer,
    check_socket_path,
    probe_socket,
    socket_path_for,
)


class HostStartError(Exception):
    """Raised when the detached host does not come up."""


def ensure_gitignore(project_root: Path | str) -> None:
    """Append the socket name to ``.gitignore`` when absent; never fatal (FR-018)."""
    root = Path(project_root)
    gitignore = root / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
        if any(line.strip() == SOCKET_NAME for line in existing.splitlines()):
            return
        separator = "" if not existing or existing.endswith("\n") else "\n"
        gitignore.write_text(f"{existing}{separator}{SOCKET_NAME}\n", encoding="utf-8")
    except OSError:
        return


def build_session(project_root: Path | str, compatibility: CompatibilityResult) -> CockpitSession:
    """Compose the one session the host drives, exactly as the TUI composes it."""
    environment = CockpitEnvironment(Path(project_root), compatibility)
    return CockpitSession(
        environment,
        services=CockpitServices.for_environment(environment),
        engine=EngineRuntime.for_environment(environment),
    )


def _structured_error(error: p.HostError) -> str:
    return json.dumps({"ok": False, "error": error.to_dict()}, indent=2)


def _child_argv(project_root: Path, explicit_executable: str | Path | None) -> list[str]:
    argv = [
        sys.executable,
        "-m",
        "workflow_cockpit",
        "--project",
        str(project_root),
        "serve",
        "--foreground",
    ]
    if explicit_executable:
        argv += ["--specify", str(explicit_executable)]
    return argv


def _open_log():
    """The opt-in diagnostics log, or ``/dev/null`` so no new artifact appears."""
    target = os.environ.get("WORKFLOW_COCKPIT_DEBUG_LOG", "").strip()
    if not target:
        return open(os.devnull, "a")
    try:
        return open(target, "a", encoding="utf-8", buffering=1)
    except OSError:
        return open(os.devnull, "a")


def _request_status(socket_path: Path) -> dict:
    """One synchronous ``status`` round trip, or raise :class:`HostStartError`."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(1.0)
    try:
        client.connect(str(socket_path))
        client.sendall(p.encode(p.request("status")))
        raw = client.recv(p.MAX_LINE_BYTES)
    except OSError as exc:
        raise HostStartError(str(exc)) from exc
    finally:
        client.close()
    if not raw:
        raise HostStartError("the host closed the connection without a response")
    return p.decode(raw.split(b"\n", 1)[0])


def _wait_for_status(socket_path: Path, process: subprocess.Popen, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    last_error = "the host did not answer"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise HostStartError(
                f"the host process exited with code {process.returncode} before serving"
            )
        if socket_path.exists():
            try:
                response = _request_status(socket_path)
            except (HostStartError, p.ProtocolError) as exc:
                last_error = str(exc)
            else:
                result = response.get("result")
                host = result.get("host") if isinstance(result, dict) else None
                if isinstance(host, dict) and host.get("pid") == process.pid:
                    return response
                last_error = "another host answered the socket"
        time.sleep(0.05)
    raise HostStartError(last_error)


def launch(
    project_root: Path | str,
    *,
    explicit_executable: str | Path | None = None,
    timeout: float = STATUS_TIMEOUT_SECONDS,
) -> int:
    """Detach a host, wait for its status, print it, and exit."""
    root = Path(project_root)
    ensure_gitignore(root)
    socket_path = socket_path_for(root)
    try:
        check_socket_path(socket_path)
    except HostBindError as exc:
        print(_structured_error(exc.error), file=sys.stderr)
        return 2
    if probe_socket(socket_path):
        error = p.HostError(
            p.HOST_ALREADY_RUNNING,
            f"A host is already serving this worktree at {socket_path}.",
            "connect to the running host instead of starting a second one",
            {"socket": str(socket_path)},
        )
        print(_structured_error(error), file=sys.stderr)
        return 1

    with _open_log() as log:
        process = subprocess.Popen(
            _child_argv(root, explicit_executable),
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            close_fds=True,
        )
    try:
        response = _wait_for_status(socket_path, process, timeout)
    except HostStartError as exc:
        error = p.HostError(
            p.BAD_REQUEST,
            f"The host did not start: {exc}",
            "set WORKFLOW_COCKPIT_DEBUG_LOG to capture the host's diagnostics",
        )
        print(_structured_error(error), file=sys.stderr)
        return 1
    print(json.dumps(response.get("result", {}), indent=2))
    return 0


def serve_foreground(
    project_root: Path | str,
    *,
    explicit_executable: str | Path | None = None,
) -> int:
    """Run the host in this process until its run-scoped lifetime releases."""
    root = Path(project_root)
    ensure_gitignore(root)
    try:
        compatibility = Compatibility().resolve_and_check(explicit_executable)
    except CompatibilityError as exc:
        print(f"workflow-cockpit: {exc}", file=sys.stderr)
        return 2
    session = build_session(root, compatibility)
    lifetime = HostLifetime()
    operations = HostOperations(
        session,
        project_root=root,
        lifetime=lifetime,
        owner_id=session.owner_id,
    )
    server = HostServer(
        project_root=root,
        operations=operations,
        session=session,
        lifetime=lifetime,
    )

    async def _main() -> None:
        loop = asyncio.get_running_loop()
        server.install_signal_handlers(loop)
        await server.serve()

    try:
        asyncio.run(_main())
    except HostBindError as exc:
        print(_structured_error(exc.error), file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover - the signal handler owns this path
        return 0
    return 0
