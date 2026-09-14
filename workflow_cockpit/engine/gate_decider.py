"""Engine-boundary gate decision executors.

These executors are the only places that touch an engine transport for a
decision. They are small, have no UI concerns, and classify every outcome so
the coordinator can preserve write-once protection.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .interactive_contract import PromptContract
from .pty_session import WriteOutcome
from .supervisor import EngineSupervisor, StdinPolicy, SupervisorError, build_resume_argv


@dataclass(frozen=True)
class DecisionResult:
    """The classified result of one attempted engine-boundary decision."""

    result: WriteOutcome
    detail: str = ""


class VerdictInputDecider:
    """Structured gate decisions via ``resume -i <name>=<choice> --json``."""

    def __init__(self, executable: Path, supervisor: EngineSupervisor) -> None:
        self._executable = Path(executable)
        self._supervisor = supervisor

    def submit(self, *, run_id: str, verdict_input: str, choice: str) -> DecisionResult:
        argv = build_resume_argv(self._executable, run_id, verdict_input, choice)
        try:
            # Structured resume keeps the non-TTY stdin policy so the gate
            # pauses again rather than prompting.
            self._supervisor.resume(run_id, argv, stdin=StdinPolicy.DEVNULL)
        except SupervisorError as exc:
            return DecisionResult(WriteOutcome.NOT_WRITTEN, str(exc))
        return DecisionResult(WriteOutcome.WRITTEN)


class InternalPtyDecider:
    """Validate the prompt contract and perform one guarded PTY write."""

    def __init__(self, contract: PromptContract, supervisor: EngineSupervisor) -> None:
        self._contract = contract
        self._supervisor = supervisor

    def submit(self, *, choice: str, options: tuple[str, ...]) -> DecisionResult:
        payload, reason = self._contract.map_choice(choice, options)
        if payload is None:
            return DecisionResult(WriteOutcome.NOT_WRITTEN, reason or "The choice cannot be mapped.")
        outcome = self._supervisor.write_input(payload)
        if outcome is WriteOutcome.NOT_WRITTEN:
            return DecisionResult(
                WriteOutcome.NOT_WRITTEN,
                "The engine process is no longer available to receive the choice.",
            )
        return DecisionResult(outcome)
