# 0010. A paused run may be adopted through an explicit single-owner claim

- Status: Accepted
- Supersedes: -
- Amends: [0005](0005-preallocated-run-identity.md)
- Amended by: [0013](0013-context-index-pointer-and-start-claim.md), [0014](0014-resume-failed-runs.md)

## Context

ADR 0005 fixed Cockpit's rule that it never attaches to a run it did not start. That rule is still
right for the fast path, but it leaves a real gap: a paused run produced by a plain
`specify workflow run`, an exited Cockpit session, a terminal loss, or another worktree is
unmanageable from Cockpit even though the engine can resume it. Story 11 (issue #2) asks Cockpit to
pick up such a run so its files can be reviewed, its gate decided, or it aborted.

Attaching to an existing run introduces a second writer into a run directory that may already have
a live owner. The engine itself keeps no cross-process owner record, so Cockpit must provide one and
must never signal or write lifecycle state on the strength of a guess.

## Decision

Cockpit may adopt an existing run only when all of the following hold:

1. The persisted `state.json` is readable and its authoritative `status` is exactly `paused`.
   `completed`, `failed`, `aborted`, `running`, and `initializing` runs stay read-only; a malformed
   or oversized run file is reported unusable with a reason and never inferred.
2. The persisted launch-copy `workflow.yml` is present and parseable. It is authoritative for the
   adopted run's graph and declared gates; Cockpit does not re-resolve the installed workflow.
3. Cockpit can write and hold a durable ownership claim at `runs/<run_id>/.cockpit-owner.json`
   (owner identity, host, PID/PGID, process start time, timestamp). No live foreign owner may hold
   the run.

Ownership is proven by the claim file plus liveness evidence. A claim is live when its host differs
from this host (cross-host shared storage cannot be probed safely) or when the recorded PID is alive
and its recorded process start time still matches. A same-host claim whose PID is gone, or whose
start time changed (PID/PGID reuse), is stale and may be reclaimed. A stale claim is recovered
without signalling any process. The claim never signals; only the supervisor signals, and only a
verified live owned group (ADR 0006).

Adoption binds the session and supervisor to the existing run ID and spawns nothing. The first
lifecycle write happens on the user's confirmed decision: one `resume -i <name>=<choice> --json` for
a `verdict_input` gate, or exactly one guarded `resume` plus one PTY write for an interactive gate,
matching the existing gate semantics (ADR 0004, ADR 0009).

## Consequences

- Cockpit can review, decide, and abort a paused run it did not start, without engine changes.
- The single-owner guarantee is extended, not weakened: at most one live Cockpit owner holds a run.
- Usable runs that cannot be adopted (such as currently running runs, completed runs, or runs held
  by a live foreign owner) can be inspected in read-only mode without acquiring a claim or mutating
  lifecycle state.
- A crash leaves the claim behind, so the next adoption detects it and recovers without signalling.
- Discovery reads are bounded (run count, state/workflow size, log window) so a large `runs/`
  directory cannot block the UI.
- ADR 0005's start rule is unchanged: a new run still refuses an existing run directory.

## Rejected alternatives

- **Scan and guess the newest run:** races with other runs and can attach to the wrong one.
- **Advisory `flock` only:** not discoverable after a crash and not portable across the supported
  hosts, so a stale lock could not be explained or recovered.
- **A separate manager process:** adds a second lifecycle owner to keep consistent and is less
  discoverable after a crash than an in-directory claim.
- **Adopting `running` runs or taking over a live foreign owner:** would put two writers on one run
  and can signal or overwrite a process Cockpit does not own.
- **Re-resolving the installed workflow on adoption:** the installed definition may have changed
  since launch, so it cannot describe the run that actually exists; the launch copy is authoritative.
