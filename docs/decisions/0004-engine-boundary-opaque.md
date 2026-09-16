# 0004. Engine transport and decision strategy stay opaque to presentation

- Status: Accepted
- Supersedes: -

## Context

Some gates resume through structured `resume -i name=choice --json`; others require a write to the
managed PTY. Presentation must not know which mechanism is in play.

## Decision

The engine transport (PTY or pipe) and the decision strategy (structured resume or PTY write) stay
internal to the engine boundary. The presentation sees only `CockpitSession.submit_decision`.

## Consequences

- Adding or changing a transport does not touch screens or widgets.
- Gate semantics stay workflow-defined; presentation cannot synthesize approve/reject.
- The write-once reconciliation for PTY decisions lives entirely in the coordinator.

## Rejected alternatives

- **Exposing the decider choice to the UI:** leaks transport detail and invites divergent handling.
- **A single universal decision mechanism:** impossible while both `verdict_input` and interactive
  gates exist.
