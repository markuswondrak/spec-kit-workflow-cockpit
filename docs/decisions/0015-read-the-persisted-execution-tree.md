# 0015. Read the persisted execution tree

- Status: Accepted
- Supersedes: -

## Context

Spec Kit 1.1.3 introduced workflow composition: a step `type: workflow` runs another installed,
enabled workflow as a private scope inside the same run. There is still one run ID and one run
directory, but `state.json` now describes a tree of scopes: the root sequence plus one child
sequence per bound call, loop iteration and fan-out item, each with a YAML `source` string zipped
against a parallel `nodes` list carrying `phase`/`active`/`result`/`outcome`.

Cockpit's read model was flat. For a composed run it could not find the gate, confused a child step
id with a same-named root step, showed the call as one opaque step, merged timings across scopes,
and refused `state.json` files that a composed run legitimately produces.

The engine also exposes its own view of the same tree through
`specify workflow status --json` (`gate.step_id`, `gate.scope_path`, `workflow_scopes`), and the
tree format lives in the engine's private `workflows/_execution.py`.

## Decision

Cockpit reads `state.json` `execution` (version 2) as a **persisted structure** and re-implements a
*reading* of it in `workflow_cockpit/services/execution_tree.py` (decode) and
`execution_walk.py` (walk). It does not import the engine and does not shell out to
`status --json` on the poll path.

- Only `execution.version == 2` is interpreted. Every other value yields a typed
  `UnsupportedExecution(version)` and a diagnostic; the engine itself refuses to load those runs,
  so there is no older format to read. An absent `execution` is a legacy run and keeps the previous
  code path unchanged.
- The active node is the engine's own definition: the first node whose `phase != "done"` in a
  children-first walk, with a `done` node's subtree skipped whole (a handled `continue_on_error`
  child may stay `blocked` under a call node the engine already completed). The per-node `active`
  marker is never the position: the engine sets it on every entered node, so enclosing calls carry
  it too.
- `current_step_id` is a consistency check, compared as the engine's qualified occurrence id
  (`fan:notes:0`, `notes-loop:notes-call:1`). It is never the source of the position.
- A structurally invalid tree, a missing unfinished node, or a mismatched `current_step_id` is
  `UNRESOLVED`, never an exception and never a guess: the gate falls back to a named Abort-only
  state.
- Scope paths, occurrence paths, qualified ids and the YAML source-sharing rule (a call body reads
  `binding.definition`, a fan-out item reads `template`, later loop iterations read iteration 0) are
  reproduced from the persisted bytes, and every distinct YAML string is decoded once per file
  signature.
- The drift risk is contained by the version guard, a single parse point, fixtures recorded from a
  pinned real engine, and a gated contract test that diffs Cockpit's reading against the engine's
  own `status --json`.

## Consequences

- A composed run's gate, scope path, nested runway, timings and resume point all come from one
  authoritative reading; a root step id and a child step id can no longer be confused in either
  direction.
- One shared `MAX_STATE_BYTES` (4 MiB, `services/limits.py`) bounds `state.json` in both the live
  reader and run discovery, and the live reader's previously unbounded read is fixed. Above the
  bound the run is reported "too large" and not parsed.
- The tree is parsed in the existing worker-thread reader and cached per file signature, so the
  500 ms update budget holds. The realistic growth of a composed `state.json` is retained step
  output (JSON); a state whose *embedded definitions* approach 4 MiB is the pathological worst case
  and is measured by a test rather than assumed fast. Lazy decoding of only the active path and
  visible runway is the documented mitigation if engine definitions grow.
- A run with an unsupported `execution.version` can be viewed but not adopted, because the engine
  would refuse to load it.
- Call targets that are not installed or not enabled are refused before Start, and dynamic targets
  are re-checked with the same rules once the engine binds them.

## Rejected alternatives

- **Infer the position from `current_step_id` or the log's `execution_path`:** both are scope
  relative and collide with root ids; the log is diagnostic evidence, not a second state model.
- **Read `status --json` at runtime:** it costs a subprocess on the poll path, and FR-004 keeps
  persisted run files authoritative. It stays the test oracle only.
- **A Cockpit-side scope state machine:** a second state model that drifts from the engine.
- **Import the engine's `_execution.py`:** private, version-coupled, and forbidden by the engine
  boundary rule.
- **Support every `execution.version`:** the engine accepts only 2, so a tolerance would be
  untestable complexity.
