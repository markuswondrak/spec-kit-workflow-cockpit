# AGENTS.md

## Project

`workflow-cockpit` is a standalone Python + Textual TUI that owns exactly one Spec Kit
workflow run in one project/worktree. It lets a user select and start a workflow, observe its
execution, review worktree changes at gates, and submit the workflow's declared decision. It
uses an installed `specify` CLI for writes and the engine's persisted run files for reads; the
engine is never modified and its internals are never imported.

## Layout

- `requirements/` - product and design contract.
  - `PRD.md` - product contract.
  - `TUI_DESIGN.md` - runtime architecture.
  - `UI_DESIGN.md` - visual language and interaction.
  - `ARCHITECTURE.md` - components and wiring.
  - `S01`-`S06` - story slices.
- `workflow_cockpit/` - application source.
- `tests/` - unit, contract, Textual, and PTY tests.
- `workflow_ui/prototype/` - visual-only Textual mock with mock data.

## Rules

- Keep implementation simple. Do not overengineer.
- No backward compatibility unless a requirement states it clearly.
- Keep functionality component scoped.
- Files must not grow too large (>500 lines). Split into functional domains / subdomains.
