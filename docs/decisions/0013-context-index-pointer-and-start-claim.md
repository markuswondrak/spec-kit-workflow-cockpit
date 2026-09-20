# 0013. The context index is a pointer, and every Cockpit-owned run holds the claim

- Status: Accepted
- Supersedes: -
- Amends: [0005](0005-preallocated-run-identity.md), [0010](0010-adopt-paused-runs.md)

## Context

The stable context index at `.specify/workflows/runs/current_run` is written by Cockpit so a
user-chosen external agent can find the active run. Issue #4 showed that the index reported a stale
`feature_directory` from a previous run: `ContextIndexWriter` resolved the value once at
construction and copied it into the file, while `.specify/feature.json` — the file that owns that
value — was updated by a later step. The two truth sources disagreed.

The same review found a second gap. The single-owner claim `runs/<run_id>/.cockpit-owner.json` was
acquired only when Cockpit adopted an existing run (ADR 0010). A run that Cockpit itself started had
no durable ownership record, so a halted started run looked ownerless to a second Cockpit and could
be adopted while the first still drove it.

## Decision

1. **One writer per fact.** The context index is a pure pointer. It records only the Cockpit-owned
   fact it uniquely owns (which run this worktree is bound to) plus the paths of the authoritative
   sources. It never resolves or caches a value owned by another file: not the run status
   (`state.json`), not the feature directory (`.specify/feature.json`), not ownership
   (`.cockpit-owner.json`). Consumers resolve each source themselves.

2. **Every Cockpit-owned run holds the claim.** A started run acquires
   `runs/<run_id>/.cockpit-owner.json` with the same claim format and liveness evidence as an
   adopted one, on the first poll that observes the run directory the engine creates. The claim is
   released on a clean session close; a crash leaves it for liveness-based recovery. Adoption is
   unchanged and still acquires its claim before binding.

## Consequences

- Issue #4 is impossible by construction: with no copied feature directory there is nothing that
  can drift, so no refresh-on-transition is needed.
- The index never needs re-writing between Start/Adopt and deletion; the run binding is fixed when
  the run is bound.
- The single-owner guarantee now covers started runs: while Cockpit's process is alive its claim is
  live, so a second Cockpit refuses to adopt the run; after a crash the claim is stale and
  recoverable, exactly as for adopted runs.
- The external agent answers "which run / what state / who owns it" from the index, `state.json`,
  and the claim, instead of trusting a copy.
- The claim for a started run is written on the first poll, so a very short window exists between
  the engine creating the run directory and the claim write; a poll interval is the bound.

## Rejected alternatives

- **Refresh the index on every state transition:** keeps the second writer and only moves the drift;
  it also copies values that never belonged in the index.
- **Embed owner identity in the index:** creates a second ownership record that can disagree with
  the claim, the exact redundancy this ADR removes.
- **Claim synchronously in `start`:** impossible, because Cockpit refuses an existing run directory
  and the engine creates that directory only after spawn.
- **Release the claim when the engine process is reaped:** a run paused at a gate is still owned by
  the live Cockpit session that can resume it; releasing at reap would reopen the ownership gap at
  every gate.
