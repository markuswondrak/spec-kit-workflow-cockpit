# 0011. A run directory may be deleted through explicit confirmation

- Status: Accepted
- Supersedes: -
- Amends: -

## Context

Persisted runs accumulate under `.specify/workflows/runs/`: neither the engine nor Cockpit removes
them, so successful, failed, and abandoned runs stay on disk forever. The launch screen lists that
directory faithfully, so stale runs clutter the list with no way to remove them from Cockpit.

Deleting a run directory is destructive and would be the first Cockpit action that removes
engine-owned run state. It therefore needs explicit, narrow safety rules rather than an implicit
cleanup job.

## Decision

Cockpit may delete one run directory only when all of the following hold:

1. The target is a single path segment that resolves to a direct child of
   `.specify/workflows/runs/`; a missing or escaping target is refused.
2. No live owner holds the run: a live foreign claim, or a claim owned by this session, is refused,
   so another live Cockpit is never undercut.
3. The run is not the one this session is currently using (started, adopted, or inspected).
4. The persisted `state.json` is readable and its status is not `running` or `initializing`,
   because the engine may still be writing those files.
5. The user confirms a destructive confirmation sheet that names the run.

Deletion removes the run directory and, when the stable `current_run` index names the deleted run,
clears that index so it never points at a missing run. Deletion never signals a process.

## Consequences

- Stale runs can be removed from the launch screen without leaving Cockpit.
- Cockpit gains a second writer of engine run state: `RunStore` removes a run directory, and
  `ContextIndexWriter` may clear its own index. This is an explicit, confirmed exception to the
  otherwise read-only run-file boundary; §2 and §3 record it.
- The single-owner guarantee is preserved: a live owner, a running engine, and the session's own run
  are all protected, and deletion is never automatic.
- History stays explicit: nothing is pruned without a confirmed user action.

## Rejected alternatives

- **Automatic pruning of completed runs:** silent data loss and races with a run that finished while
  discovery was in flight.
- **Archiving instead of deleting:** adds a second storage location and a migration burden for a
  cleanup action the user asked to keep simple.
- **Deleting without owner checks or confirmation:** can remove a run another live Cockpit holds or
  an engine is still writing.
- **Letting the read-only `RunCatalog` delete:** conflates discovery with mutation and weakens its
  bounded read-only contract.
