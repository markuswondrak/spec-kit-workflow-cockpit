# 4. Solution Strategy

| Field | Value |
|---|---|
| arc42 | 4. Solution Strategy |
| Tier | 3 |

Reference material. Do not load automatically; read when evaluating a structural change.

## Architectural principles

- **Ownership is explicit.** One Cockpit process owns exactly one run. A numeric PID/PGID is
  actionable only while its owned child is verified live, and is cleared as part of reaping.
- **The engine is a black box.** Writes use CLI commands, Abort uses OS signals against a verified
  group, reads use persisted files, and internals are never imported.
- **Persisted files win.** Process state and persisted state are separate evidence joined in
  `RunSnapshot`; persisted state is authoritative for workflow status.
- **The UI never blocks.** Blocking work runs in worker threads; state crosses the presentation
  boundary only as immutable snapshots.
- **Core services are Textual-free.** Domain logic is testable without a running app.

## Technology decisions

| Area | Choice | Reason |
|---|---|---|
| Language/runtime | Python `>=3.10` | Matches the target environment and Textual. |
| UI | Textual | One async event loop for UI, polling, and subprocess/PTY. |
| Config/data | PyYAML, `packaging` | Definition parsing and version bounds without engine coupling. |
| Snapshot transport | `asyncio.Queue` + `post_message` | Presentation never polls services directly. |
| Heavy I/O | Textual `@work(thread=True)` | Keeps rendering responsive. |
| Engine transport | Internal PTY | Supports interactive gates without a user-visible terminal. |

## Quality tactics

- Poll on a 250 ms monotonic schedule so observable updates stay within the 500 ms product bound.
- Read defensively: skip unchanged files, tolerate missing/partially written state, and retain the
  last good value with a `STALE` marker.
- Bound every read: tail `log.jsonl`, cap `RichLog` output, preview large files with an explicit
  full-open action.
- Confirm every declared gate choice once; never resend an unverified PTY write.

The decisions above are recorded as ADRs in [§9 Architecture Decisions](09-architecture-decisions.md).
