# Requirements - Workflow Cockpit

The product and design contract now lives in the architecture set under
[`docs/architecture/`](../docs/architecture/README.md), starting at
[`docs/architecture/README.md`](../docs/architecture/README.md). This folder keeps the product
backlog: the deferred epic and the remaining story slices.

- [`AGENTS.md`](../AGENTS.md) is the always-on agent context.
- [`docs/architecture/`](../docs/architecture/README.md) holds intent and constraints mapped to
  arc42, including the functional requirements in [§1](../docs/architecture/01-introduction-and-goals.md).
- [`docs/decisions/`](../docs/decisions/README.md) holds numbered ADRs.
- [`docs/glossary.md`](../docs/glossary.md) pins the vocabulary.

## Story index

Delivered slices (`S01`-`S08`) were retired as their design documents were absorbed into the
architecture set. Open and deferred work:

| # | Vertical slice | Requirements | File |
|---|---|---|---|
| S9 | Release polish for publishing | Quality requirements | [S09](S09-release-polish.md) |
| S10 | arc42 context layer for agents | Quality requirements; architecture context | [S10](S10-arc42-context-layer.md) |
| E1 | Optional OpenCode adapter (deferred epic) | Discovery and design only | [E01](E01-opencode-adapter.md) |

Dependencies: S9 depends on S1-S8; S10 depends on S1-S6 and coordinates with the S9 CI workflow.
E1 depends on the completed first-release slices and a stable public session/read-model boundary.
It must not alter the standalone Cockpit's lifecycle ownership or make OpenCode a required
dependency.

## Global definition of done

- No workflow-engine changes and no imports of engine internals.
- Persisted run files are authoritative; lifecycle writes use existing CLI commands.
- One Engine Supervisor owns at most one active engine process group.
- Unit tests, Textual `App.run_test()` tests, and subprocess/PTY integration tests pass.
- English UI and keyboard-accessible controls with in-app help.
- Documentation is living: a changed constraint, boundary, or decision updates the matching
  architecture document in the same commit.
