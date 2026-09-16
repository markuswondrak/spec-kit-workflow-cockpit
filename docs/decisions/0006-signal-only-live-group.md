# 0006. A process group is signalable only while its owned child is verified live

- Status: Accepted
- Supersedes: -

## Context

The engine exposes no abort command, so Abort signals the recorded process group. A retained
numeric PGID can be reused by the OS after the child is reaped, making a late signal dangerous.

## Decision

A group is signalable only while the owned child has not been reaped, its return code is unset,
and its OS process group equals the PGID recorded at spawn. Abort and reap are serialized by the
supervisor, and ownership is cleared as part of reaping under the same lock. A paused run whose
command already exited is aborted locally with no signal.

## Consequences

- Cockpit never signals an unrelated process after a reap.
- Abort becomes a local outcome update when no live process exists.
- Cleanup is bounded: SIGINT, a grace period, then TERM/KILL only to the verified group.

## Rejected alternatives

- **Signaling any recorded PGID:** risks killing an unrelated reused process group.
- **Relying on an engine abort command:** none exists.
