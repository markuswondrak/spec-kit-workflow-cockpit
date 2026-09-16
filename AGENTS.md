# AGENTS.md

`workflow-cockpit` is a standalone Python + Textual TUI that owns exactly one Spec Kit workflow
run in one project/worktree. It uses an installed `specify` CLI for writes and the engine's
persisted run files for reads; the engine is never modified and its internals are never imported.

## Always-on context

This file is the only always-on context. Load more only when the task needs it:

- **Architecture index:** [`docs/architecture/README.md`](docs/architecture/README.md) - enter at
  the matching arc42 section and stop. Tier 2 sections load on demand; Tier 3 is reference-only.
- **Decision log:** [`docs/decisions/README.md`](docs/decisions/README.md) - numbered ADRs.
- **Vocabulary:** [`docs/glossary.md`](docs/glossary.md) - pinned domain terms; do not treat
  synonyms as interchangeable.

Code is the source of truth for behavior; those documents are the source of truth for intent and
constraints. If they conflict, surface it to a human; never silently edit docs to match code or
code to match docs.

## Top quality goals

1. **Operational certainty** - the user can always identify branch, current node, engine status,
   and available gate action.
2. **Responsiveness** - the UI never blocks; visible updates appear within 500 ms.
3. **Engine safety** - the engine stays untouched; persisted run files are authoritative.

## Universal rules

- **Never modify or import the engine.** Rationale: Cockpit must keep working across `specify`
  versions without engine changes.
- **Treat persisted run files as authoritative.** Rationale: output is diagnostic evidence, not a
  second state model; inferring state causes drift.
- **Keep one supervisor owning one process group; signal only a verified live group.** Rationale: a
  reaped PGID can be reused, so a late signal can hit an unrelated process.
- **Keep Textual imports out of core services.** Rationale: services must be testable without a
  running app; put Textual in `workflow_cockpit/ui/`.
- **Keep blocking work off the render path.** Rationale: Git, file reads, and process I/O would
  freeze the UI.
- **Bound every read.** Rationale: `log.jsonl` and feature files can grow without limit.
- **Keep functionality component scoped and files under 500 lines.** Rationale: large files hide
  unrelated responsibilities and resist review; split by domain.
- **Keep it simple; add no backward compatibility unless a requirement states it.** Rationale:
  unused compatibility is untested complexity.
- **Keep documentation living.** Rationale: a change that alters a documented constraint,
  boundary, or decision updates the matching document in the same commit.

## Commands

```bash
python -m pip install -e ".[test]"          # setup
ruff check workflow_cockpit tests           # lint
python -m pytest tests/unit tests/textual tests/contract tests/pty tests/docs -q
```

The real-`specify` contract suite skips unless `WORKFLOW_COCKPIT_REAL_SPECIFY` points at a pinned
executable. Development is dogfooded through `presets/lean-workflow` + `workflows/lean-flow`; see
[`presets/lean-workflow/README.md`](presets/lean-workflow/README.md).

## Layout

- `workflow_cockpit/` - application source.
- `docs/` - architecture context, decisions, glossary.
- `tests/` - unit, Textual, contract, PTY, and docs tests.
- `workflow_ui/prototype/` - visual-only prototype, not shipped.
- `presets/`, `workflows/`, `extensions/` - dogfooding tooling.
