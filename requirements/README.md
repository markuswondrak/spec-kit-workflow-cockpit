# Requirements - Workflow Cockpit

These files define the standalone Python/Textual application `workflow-cockpit`. One invocation
owns one Spec Kit workflow run in one project/worktree. Engine output is rendered inside the
application; external agents remain independent.

`PRD.md` is the product contract. `TUI_DESIGN.md` defines runtime architecture.
`UI_DESIGN.md` defines visual language and interaction.

## Story index

| # | Vertical slice | Requirements | File |
|---|---|---|---|
| S1 | Own one workflow run | FR-1, FR-2 basic, FR-6 basic | [S01](S01-owned-run.md) |
| S2 | Workflow runway | FR-2 | [S02](S02-workflow-runway.md) |
| S3 | Review and decide a structured gate | FR-3, FR-5 | [S03](S03-gate-review.md) |
| S4 | Decide interactive gates | FR-5 | [S04](S04-interactive-gates.md) |
| S5 | Cockpit skill and run context | FR-4 | [S05](S05-cockpit-skill.md) |
| S6 | Resilient operation | FR-6, NFRs | [S06](S06-resilience.md) |
| S7 | Agent-matched styling templates | FR-7 | [S07](S07-agent-styling-templates.md) |

Dependencies: S1 -> S2 -> S3 -> S4; S5 depends on S1; S6 depends on S1-S5; S7 depends on S1 and
themes the S2-S6 surfaces.

## First-release boundary

S1-S6 deliver workflow selection and inputs, owned process lifecycle, integrated output, the
workflow graph, Worktree Changes, both gate paths, the external-agent context bridge, and robust
shutdown behavior. S7 is a cross-cutting presentation slice layered over the core loop.

## Global definition of done

- No workflow-engine changes and no imports of engine internals.
- Persisted run files are authoritative; lifecycle writes use existing CLI commands.
- One Engine Supervisor owns at most one active engine process group.
- Unit tests, Textual `App.run_test()` tests, and subprocess/PTY integration tests pass.
- English UI and keyboard-accessible controls with in-app help.

## Removed scope

- Multi-run and historical-run navigation.
- Workflow authoring, installation, and management.
- Multi-project operation and Cockpit-owned persistence.
- Embedded or managed coding agents.
- External notifications, localization, and native Windows.
- Terminal emulation and terminal multiplexer integration.

## Pre-implementation validation

1. Supported `specify` range: initial minimum `>=1.0`. Document registry, input, state, pause,
   resume, and interrupt/abort contracts. (Range decided; contracts documented during the S1
   engine spike.)
2. Verify process behavior for structured and interactive gates, including PTY prompt readiness
   and choice mapping.
3. Verify Git comparison behavior across branch changes and dirty/untracked files.
4. Minimum terminal size: **88 x 36** (validated by the prototype).
