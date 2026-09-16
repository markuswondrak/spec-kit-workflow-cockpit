# 0002. Heavy I/O runs in Textual `@work(thread=True)` workers

- Status: Accepted
- Supersedes: -

## Context

Git reads, feature-file listing, and large-file reads can block long enough to freeze the UI if
run on the event loop.

## Decision

Run heavy I/O in Textual `@work(thread=True)` workers (Git, feature-file reads, large-file work)
and hand results back through messages.

## Consequences

- The 500 ms responsiveness bound is met even during large reads.
- Workers are `exclusive` per group so only one poll, branch refresh, or review read runs at a time.
- Services remain Textual-free; the worker annotation lives in the UI layer.

## Rejected alternatives

- **Blocking calls on the event loop:** freezes rendering.
- **A separate process pool:** heavier than needed for bounded file and Git reads.
