# 9. Architecture Decisions

| Field | Value |
|---|---|
| arc42 | 9. Architecture Decisions |
| Tier | 2 |

## Decision log

Architecture decisions are numbered ADRs under [`docs/decisions/`](../decisions/README.md). This
section is the index; each ADR records context, the decision, consequences, and what was rejected.

| ADR | Decision |
|---|---|
| [0001](../decisions/0001-snapshot-transport.md) | Snapshot transport is an `asyncio.Queue` published with `post_message`. |
| [0002](../decisions/0002-heavy-io-thread-workers.md) | Heavy I/O runs in Textual `@work(thread=True)` workers. |
| [0003](../decisions/0003-minimum-terminal-size.md) | Minimum terminal size is 88 x 36 with a reversible resize guard. |
| [0004](../decisions/0004-engine-boundary-opaque.md) | Engine transport and decision strategy stay opaque to presentation. |
| [0005](../decisions/0005-preallocated-run-identity.md) | Run identity is preallocated and passed via `SPECKIT_WORKFLOW_RUN_ID`. |
| [0006](../decisions/0006-signal-only-live-group.md) | A process group is signalable only while its owned child is verified live. |
| [0007](../decisions/0007-effective-definition-launch-model.md) | The launch model is the effective base-plus-overlay definition. |
| [0008](../decisions/0008-install-run-context-skill.md) | The run-context skill installs into the project integration at startup. |
| [0009](../decisions/0009-universal-interactive-contract.md) | The interactive gate contract applies to any workflow-capable engine. |
| [0010](../decisions/0010-adopt-paused-runs.md) | A paused run may be adopted through an explicit single-owner claim. |
| [0011](../decisions/0011-delete-run-directories.md) | A run directory may be deleted through explicit confirmation. |

## How to add an ADR

1. Take the next free number in `docs/decisions/`.
2. Use the same template: Title, Status, Context, Decision, Consequences, Rejected alternatives.
3. Add the row above and list it in [`docs/decisions/README.md`](../decisions/README.md) in the same
   change. The ADR test fails on any orphaned or unlisted ADR.
