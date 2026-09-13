# Story 6 - Resilient operation

> As a workflow user, I want the Cockpit to remain usable when files, child processes, or the
> terminal behave unexpectedly so that it is safe for real runs.

| Field | Value |
|---|---|
| ID | S6 |
| Requirements | FR-6, quality requirements |
| Dependencies | S1-S5 |

## Acceptance criteria

- Linux, macOS, and WSL are covered for the declared `specify` version range; native Windows is
  explicitly unsupported.
- The English UI is keyboard accessible and provides in-app help.
- Below the documented minimum terminal size, a blocking resize message replaces the layout.
- Polling does not block the UI and skips unchanged state files.
- Partial JSON writes, missing files, malformed events, child-process failure, context-index
  failure, and editor failure preserve the last good state and produce actionable errors.
- Interactive exit requires confirmed Abort while active.
- Catchable `SIGINT`, `SIGHUP`, and `SIGTERM` trigger bounded best-effort abort and cleanup of
  the recorded engine process group without confirmation.
- No cleanup guarantee is claimed for `SIGKILL`, host loss, power loss, or interpreter failure.
- Cockpit writes no history outside engine metadata and ephemeral process state.

## Tests

- Unit, Textual, and subprocess/PTY suites run in CI where platform capabilities permit.
- End-to-end fixtures cover success, structured and interactive gates, branch creation,
  retry/skip, empty changes, no-gate execution, failure, abort, and termination signals.
