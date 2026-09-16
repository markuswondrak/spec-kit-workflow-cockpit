# Architecture Decision Records

Numbered decisions for `workflow-cockpit`. Each ADR records what was decided and what was
rejected. The set is indexed from [§9 Architecture Decisions](../architecture/09-architecture-decisions.md).

| ADR | Title | Status |
|---|---|---|
| [0001](0001-snapshot-transport.md) | Snapshot transport is an `asyncio.Queue` published with `post_message` | Accepted |
| [0002](0002-heavy-io-thread-workers.md) | Heavy I/O runs in Textual `@work(thread=True)` workers | Accepted |
| [0003](0003-minimum-terminal-size.md) | Minimum terminal size is 88 x 36 with a reversible resize guard | Accepted |
| [0004](0004-engine-boundary-opaque.md) | Engine transport and decision strategy stay opaque to presentation | Accepted |
| [0005](0005-preallocated-run-identity.md) | Run identity is preallocated and passed via `SPECKIT_WORKFLOW_RUN_ID` | Accepted |
| [0006](0006-signal-only-live-group.md) | A process group is signalable only while its owned child is verified live | Accepted |
| [0007](0007-effective-definition-launch-model.md) | The launch model is the effective base-plus-overlay definition | Accepted |
| [0008](0008-install-run-context-skill.md) | The run-context skill installs into the project integration at startup | Accepted |

An ADR test asserts every file here is listed and every listed ADR resolves to a file.
