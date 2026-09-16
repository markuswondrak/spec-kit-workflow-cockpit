# 0001. Snapshot transport is an `asyncio.Queue` published with `post_message`

- Status: Accepted
- Supersedes: -

## Context

The presentation layer needs a steady stream of run state, but services must not be polled from
the render path, and mutable state must not be shared across the boundary.

## Decision

The polling loop produces an immutable `RunSnapshot` and publishes it to the app with
`post_message`; presentation never polls services directly.

## Consequences

- The UI updates from messages it can coalesce, keeping rendering responsive.
- Every consumer sees a frozen value, so refresh logic cannot corrupt state.
- A dropped or late message is harmless: the next scheduled poll republishes.

## Rejected alternatives

- **Widgets polling services directly:** blocks the render path and couples widgets to services.
- **A shared mutable model:** introduces races between the poll thread and the render loop.
