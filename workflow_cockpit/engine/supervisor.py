"""Own at most one engine process group and abort only a verified live group."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .normalizer import OutputNormalizer
from .pty_session import PtySession


class SupervisorError(Exception):
    """Raised for invalid supervisor lifecycle calls."""


@dataclass(frozen=True)
class ProcessCondition:
    live: bool
    exit_code: int | None
    reaped: bool
    aborting: bool


def build_run_argv(
    executable: Path, workflow_id: str, input_argv: Sequence[str]
) -> list[str]:
    return [str(executable), "workflow", "run", workflow_id, *input_argv]


def build_resume_argv(
    executable: Path, run_id: str, verdict_input: str, choice: str
) -> list[str]:
    """Structured resume: one verdict input, JSON outcome on stderr if needed."""
    return [
        str(executable),
        "workflow",
        "resume",
        run_id,
        "-i",
        f"{verdict_input}={choice}",
        "--json",
    ]


class EngineSupervisor:
    """Own one engine child under a PTY and its own process group."""

    def __init__(
        self,
        executable: Path,
        project_root: Path,
        *,
        grace_interrupt: float = 5.0,
        grace_term: float = 3.0,
        normalizer: OutputNormalizer | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        spawner: Callable[..., subprocess.Popen] | None = None,
    ) -> None:
        self.executable = Path(executable)
        self.project_root = Path(project_root)
        self.grace_interrupt = grace_interrupt
        self.grace_term = grace_term
        self.normalizer = normalizer or OutputNormalizer()
        self._clock = clock
        self._sleep = sleeper
        self._spawner = spawner or subprocess.Popen

        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._pgid: int | None = None
        self._pty: PtySession | None = None
        self._run_id: str | None = None
        self._reaped_event = threading.Event()
        self._exit_code: int | None = None
        self._abort_requested = False
        self._started_at: float | None = None
        self._command_kind: str | None = None
        self._last_reaped_command: str | None = None

    @property
    def run_id(self) -> str | None:
        return self._run_id

    @property
    def started_at(self) -> float | None:
        return self._started_at

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    @property
    def abort_requested(self) -> bool:
        return self._abort_requested

    @property
    def last_reaped_command(self) -> str | None:
        return self._last_reaped_command

    @property
    def output_lines(self) -> list[str]:
        return self.normalizer.lines

    @property
    def partial_line(self) -> str:
        return self.normalizer.partial

    @property
    def output_emitted(self) -> int:
        return self.normalizer.emitted

    def _run_dir(self, run_id: str) -> Path:
        return self.project_root / ".specify" / "workflows" / "runs" / run_id

    def start(
        self,
        run_id: str,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        with self._lock:
            if self._proc is not None and not self._reaped_event.is_set():
                raise SupervisorError("An engine process is already active.")
            if self._reaped_event.is_set() or self._proc is not None:
                raise SupervisorError("This supervisor has already owned a process.")
            if self._run_dir(run_id).exists():
                raise SupervisorError(
                    f"Run directory already exists for {run_id!r}; refusing to reuse it."
                )
            self._spawn(run_id, argv, env, command_kind="run")

    def resume(
        self,
        run_id: str,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        """Spawn a structured resume for the already-owned run.

        Only one child may be owned at a time; the previous child must have
        been reaped. The normalizer's output history is preserved.
        """
        with self._lock:
            if self._run_id is None:
                raise SupervisorError("No run has been started to resume.")
            if self._abort_requested:
                raise SupervisorError("This supervisor aborted the run and cannot resume it.")
            if run_id != self._run_id:
                raise SupervisorError("Refusing to resume a run this supervisor does not own.")
            if self._proc is not None and not self._reaped_event.is_set():
                raise SupervisorError("An engine process is already active.")
            if not self._reaped_event.is_set():
                raise SupervisorError("The previous engine process has not exited.")
            self._reset_for_spawn()
            self._spawn(run_id, argv, env, command_kind="resume")

    def _reset_for_spawn(self) -> None:
        if self._pty is not None:
            self._pty.close()
            self._pty = None
        self._proc = None
        self._pgid = None
        self._exit_code = None
        self._reaped_event = threading.Event()

    def _spawn(
        self,
        run_id: str,
        argv: Sequence[str],
        env: Mapping[str, str] | None,
        *,
        command_kind: str,
    ) -> None:
        master_fd, slave_fd = os.openpty()
        # stdin is deliberately not a TTY: Cockpit is a read-only observer in
        # S03, and the engine pauses a gate instead of prompting when stdin is
        # not a TTY. stdout/stderr stay on the PTY for normalized output.
        stdin_fd = os.open(os.devnull, os.O_RDONLY)
        child_env = dict(os.environ if env is None else env)
        child_env["SPECIFY_INIT_DIR"] = str(self.project_root)
        child_env["SPECKIT_WORKFLOW_RUN_ID"] = run_id
        try:
            proc = self._spawner(
                list(argv),
                cwd=str(self.project_root),
                env=child_env,
                stdin=stdin_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
                close_fds=True,
            )
        except BaseException:
            os.close(master_fd)
            os.close(slave_fd)
            os.close(stdin_fd)
            raise
        os.close(slave_fd)
        os.close(stdin_fd)
        self._proc = proc
        self._run_id = run_id
        self._pgid = os.getpgid(proc.pid)
        self._command_kind = command_kind
        if self._started_at is None:
            self._started_at = self._clock()
        self._pty = PtySession(master_fd, self.normalizer.feed)
        self._pty.start()
        threading.Thread(target=self._reap, name="cockpit-reap", daemon=True).start()

    def _reap(self) -> None:
        proc = self._proc
        command_kind = self._command_kind
        if proc is None:
            return
        code = proc.wait()
        with self._lock:
            self._exit_code = code
            self._last_reaped_command = command_kind
            self._reaped_event.set()
            if self._pty is not None:
                self._pty.close()
                self._pty = None

    def verify_live(self) -> bool:
        with self._lock:
            proc = self._proc
            if proc is None or self._reaped_event.is_set():
                return False
            if proc.poll() is not None:
                return False
            try:
                return os.getpgid(proc.pid) == self._pgid
            except (ProcessLookupError, OSError):
                return False

    def is_live(self) -> bool:
        return self.verify_live()

    def condition(self) -> ProcessCondition:
        with self._lock:
            reaped = self._reaped_event.is_set()
            return ProcessCondition(
                live=self.verify_live(),
                exit_code=self._exit_code,
                reaped=reaped,
                aborting=self._abort_requested and not reaped,
            )

    def _wait_until_reaped(self, timeout: float) -> bool:
        return self._reaped_event.wait(timeout=timeout)

    def _signal_group(self, sig: signal.Signals) -> bool:
        with self._lock:
            if not self.verify_live():
                return False
            pgid = self._pgid
        try:
            os.killpg(pgid, sig)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            return False

    def abort(self) -> None:
        """SIGINT then TERM/KILL a verified live group; otherwise record locally."""
        with self._lock:
            self._abort_requested = True
        if not self.verify_live():
            return
        self._signal_group(signal.SIGINT)
        if self._wait_until_reaped(self.grace_interrupt):
            return
        if self._signal_group(signal.SIGTERM):
            if self._wait_until_reaped(self.grace_term):
                return
        if self.verify_live():
            self._signal_group(signal.SIGKILL)
            self._wait_until_reaped(self.grace_term)

    def close(self) -> None:
        if self.is_live():
            self.abort()
        with self._lock:
            if self._pty is not None:
                self._pty.close()
                self._pty = None
