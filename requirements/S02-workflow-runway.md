# Story 2 - Workflow runway

> As a workflow user, I want to see the workflow's control flow and runtime position so that I
> understand what has happened and what can happen next.

| Field | Value |
|---|---|
| ID | S2 |
| Requirements | FR-2 |
| Dependencies | S1 |

## Acceptance criteria

- The Runway represents the complete declared workflow graph, including known branches, loops,
  gates, and overlays.
- Runtime state highlights the active path and marks pending, running, paused, completed,
  failed, skipped, and aborted nodes.
- Attempts and completed/live per-step durations are shown.
- Branch changes update automatically while the fixed baseline commit remains unchanged.
- Selection, focus, and scroll survive polling refreshes.
- The graph is derived generically from the installed workflow definition.

## Tests

- Unit tests cover graph parsing, branches, loops, overlays, attempts, and runtime projection.
- Textual tests cover selection and layout through state changes.
