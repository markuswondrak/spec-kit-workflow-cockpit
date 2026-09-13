# Story 5 - Cockpit skill and run context

> As a workflow user, I want a Cockpit skill to load the run context in an agent of my choice
> without Cockpit managing that agent.

| Field | Value |
|---|---|
| ID | S5 |
| Requirements | FR-4 |
| Dependencies | S1 |

## Acceptance criteria

- After Start returns a run ID, Cockpit writes a stable context index under
  `.specify/workflows/runs/<run_id>/`.
- The index points to authoritative workflow definition, status, inputs, logs, worktree,
  current branch source, and the declared feature directory rather than copying live state.
- Cockpit displays the context path and concise skill invocation guidance.
- The skill accepts that path, reads the authoritative sources, and can explain workflow state,
  gates, and Feature Files.
- The skill states that Cockpit alone controls lifecycle and never invokes start, resume,
  decision, or abort commands.
- Before editing, the skill checks that the engine is paused at a gate.
- Cockpit does not discover, launch, embed, control, or terminate agents.
- Context generation failure is reported but never interrupts the workflow run.

## Tests

- Unit tests cover context generation, path validation, source resolution, and lifecycle safety
  rules.
