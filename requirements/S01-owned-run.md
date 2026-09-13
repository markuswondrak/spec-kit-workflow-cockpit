# Story 1 - Own one workflow run

> As an existing Spec Kit workflow user, I want to select, start, observe, and abort one run so
> that the Cockpit is useful end to end before advanced review features exist.

| Field | Value |
|---|---|
| ID | S1 |
| Requirements | FR-1, FR-2 (basic), FR-6 (basic) |
| Dependencies | None |

## Acceptance criteria

- `workflow-cockpit` discovers the nearest Spec Kit project root or accepts an explicit path.
- Preflight validates Git, project initialization, and the tested `specify` version range.
- The user selects any installed workflow, sees its summary and steps, and completes a
  schema-driven input form with required-field validation.
- A dirty worktree produces a warning and one confirmation but does not prevent Start.
- Start records current `HEAD` and launches the workflow through one `EngineSupervisor`.
- The supervisor owns at most one active engine process group and runs output-producing engine
  commands under an internal PTY.
- A read-only, bounded Engine Output view shows normalized live output without forwarding user
  keystrokes.
- Basic run state, current step, branch, baseline commit, and elapsed time update within 500 ms.
- Confirmed Abort sends SIGINT to the recorded engine process group (the engine's only stop
  mechanism), then cleans up only that group after a bounded grace period. The engine persists
  the run as interrupted/paused; Cockpit owns the aborted outcome and does not resume it in
  this session.
- Success, failure, and abort remain visible until acknowledgment exits the application.

## Tests

- Unit tests cover discovery, registry parsing, version checks, validation, and supervisor
  transitions.
- Textual tests cover selection, Start, live state, output, outcomes, and Abort confirmation.
- PTY integration tests cover output normalization and child-process cleanup.
