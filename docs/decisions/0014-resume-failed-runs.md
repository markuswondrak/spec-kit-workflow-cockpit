# 0014. A failed run may be adopted and resumed once from its recorded step

- Status: Accepted
- Supersedes: -
- Amends: [0010](0010-adopt-paused-runs.md)
- Amended by: -

## Context

ADR 0010 let Cockpit adopt a `paused` run, but a run that reached persisted status `failed`
stayed read-only even though the engine can resume it. `specify workflow resume` accepts a
`PAUSED` or `FAILED` run and continues from the persisted `state.current_step_index`; there is no
step selector in the CLI. A failed run therefore left the operator unable to recover in place
without starting a fresh run, losing the recorded progress.

Two risks must be controlled. First, a second writer must never enter a run directory held by a
live foreign owner. Second, a failed run that is watched by the 250 ms poll could be resumed more
than once if a single confirmation were not made write-once.

## Decision

Widen adoption from `paused` to `{paused, failed}` in one place each: `RunDescriptor.adoptable`
and `RunAdopter.prepare`. `completed`, `aborted`, `running`, `initializing`, unusable, and unknown
statuses stay read-only, and a `live_foreign` claim is never adoptable. All existing guards (usable
launch copy, no live foreign owner, claim acquisition, launch-copy parse with claim release on
failure) are unchanged.

For an adopted failed run, add one explicit, confirmed, write-once **Resume** lifecycle action:

1. A `ResumeCoordinator` projects the affordance only while the persisted status is `failed`, names
   the recorded current step (and its immediate enclosing step when nested), and mints one opaque
   token when no attempt is consumed.
2. On confirmation it issues exactly one bare `specify workflow resume <run_id>` through
   `EngineSupervisor`, with the workflow's validated stdin policy. It never passes `--input` and
   never reimplements the engine's step or nested-resume semantics.
3. The attempt is reserved under the coordinator lock before the engine boundary. `NOT_WRITTEN`
   releases the reservation and the run stays byte-for-byte unchanged and resumable;
   `WRITTEN`/`UNCERTAIN` consume the token permanently. The attempt clears when the persisted status
   advances, and a fresh failure afterwards mints a new token.
4. Persisted run files stay authoritative: post-resume status is re-read from `state.json`, no new
   run identity, branch, or worktree is allocated, and the launch copy still governs the definition.

## Consequences

- A failed run can be recovered in place from its recorded step without losing progress.
- The single-owner guarantee is preserved: a live foreign owner keeps the run view-only and no
  signal or write is ever sent on the strength of a guess.
- Exactly one resume is issued per confirmation; a refused or failed resume leaves the run
  resumable and surfaces the reason.
- Adoption and discovery behavior, the gate decision path, Abort, and the context index are reused
  unchanged.

## Rejected alternatives

- **Allowing `aborted`, `completed`, `running`, or `initializing`:** `aborted` is a terminal
  outcome the spec excludes, and `running`/`initializing` have a live writer.
- **A `--from <step>` selector:** the installed CLI has none, and adding one would require an
  engine change, which the engine-boundary rule forbids.
- **Reimplementing the resume or nested-re-run rule in Cockpit:** the engine owns the exact re-run
  set; duplicating it would drift. Cockpit narrates the nested consequence instead.
- **Relying on the supervisor guard alone for write-once:** it prevents only concurrent double
  spawn, not a second confirmation after the first resume is reaped, so a Cockpit-side ledger is
  required.
