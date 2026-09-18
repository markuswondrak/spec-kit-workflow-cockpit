# 0005. Run identity is preallocated and passed via `SPECKIT_WORKFLOW_RUN_ID`

- Status: Accepted
- Supersedes: -
- Amended by: [0010](0010-adopt-paused-runs.md)

## Context

The engine can generate a run ID itself, but Cockpit must know exactly which run directory it owns
before it starts reading state.

## Decision

Cockpit generates a collision-resistant run ID, verifies the target directory does not exist,
launches without a shell with `SPECKIT_WORKFLOW_RUN_ID` set to that ID, and observes only that
exact directory. Directory scanning is never used to claim ownership.

## Consequences

- Cockpit never attaches to a run it did not start.
- An existing run directory makes Start fail rather than reuse a run.
- The context index is written under the known run ID immediately after Start.

## Rejected alternatives

- **Scanning `runs/` for the newest directory:** races with other runs and can claim the wrong one.
- **Letting the engine choose the ID:** Cockpit would have to discover its own run.
