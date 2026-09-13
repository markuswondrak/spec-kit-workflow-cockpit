# Story 4 - Decide interactive gates

> As a workflow user, I want to submit gates without `verdict_input` so that compatible
> interactive workflows use the same review experience.

| Field | Value |
|---|---|
| ID | S4 |
| Requirements | FR-5 (PTY fallback) |
| Dependencies | S3 |

## Acceptance criteria

- When the supported engine contract indicates a ready interactive prompt, Cockpit maps the
  confirmed declared choice to its input and writes it to the live supervised PTY.
- Ordinary user input never reaches the PTY.
- A choice is written at most once.
- The UI acknowledges the write but continues to show authoritative persisted state.
- If state does not advance, choices cannot be resent and confirmed Abort is the only action.
- Engine Output remains available for diagnosis.
- Structured `verdict_input` is preferred whenever declared.

## Tests

- A pre-implementation spike establishes prompt readiness and input mapping for each supported
  `specify` version.
- PTY tests cover success, delayed advancement, unverified submission, disabled resend, and
  abort-only recovery.
