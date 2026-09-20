# 2. Constraints

| Field | Value |
|---|---|
| arc42 | 2. Constraints |
| Tier | 1 |

Constraints are non-negotiable. If a change appears to require violating one, surface the conflict
instead of working around it.

## Technical constraints

- **The engine is untouched.** Workflow mutations use existing `specify` CLI commands; Abort uses
  OS signals against a verified live owned process group; reads use persisted run files. No engine
  internals are imported.
- **One process, one run, one worktree.** `CockpitSession` composes services for at most one run;
  it may start a new run, adopt one existing `paused` run, or inspect an existing run read-only
  without ownership. Discovery lists runs read-only, but lifecycle ownership is always at most one.
  There is no multi-run, multi-project, or history model.
- **Persisted run files are authoritative.** `state.json`, `inputs.json`, and `log.jsonl` under
  `.specify/workflows/runs/<run_id>/` decide workflow state. Engine Output is diagnostic evidence,
  never a state source.
- **Adoption is explicit and single-owner.** Only a run whose persisted status is `paused` with a
  parseable launch-copy `workflow.yml` may be adopted, and only after Cockpit writes and holds a
  durable ownership claim. A live foreign owner is refused; a stale claim may be recovered without
  signalling any process. Adoption binds the existing run ID and spawns nothing.
- **Stack.** Python `>=3.10` with Textual. PyYAML and `packaging` are direct dependencies; Cockpit
  never relies on packages from the `specify` installation.
- **Engine boundary is opaque.** The transport (PTY or pipe) and the decision strategy (structured
  resume or PTY write) stay internal. The presentation sees only `CockpitSession`.
- **Supported platforms.** Linux, macOS, and WSL. Native Windows is unsupported.

## Organizational constraints

- **Simple first.** Do not overengineer. No backward compatibility unless a requirement states it
  clearly.
- **Component scoped.** Keep functionality within its component; keep files under 500 lines and
  split by functional domain.
- **Documentation is living.** Any change that alters a documented constraint, boundary, or
  decision updates the matching document in the same commit.
- **Dogfooding.** Changes to this repository are driven through the published GitHub installation
  of `spec-kit-extended-flow` and observed/decided in the Cockpit itself. Local sibling-checkout
  development is an explicit alternate mode.

## Boundaries

- `CockpitSession` is the only API the presentation layer calls.
- `EngineSupervisor` is the only component that writes workflow lifecycle and the only component
  that signals a process.
- `RunStateReader`, `WorkflowRegistry`, `WorkflowDefinitionResolver`, and `RunCatalog` are the only
  readers of their persisted/catalog/definition/run-directory files. `RunCatalog` reads bounded and
  imports no engine internals.
- Inside `.specify/`, `ContextIndexWriter` (the `current_run` index), `RunClaimStore` (the
  `.cockpit-owner.json` ownership claim), and `RunStore` (confirmed deletion of one run directory)
  write. None writes engine lifecycle state; deletion removes a whole run directory only under the
  explicit rules in [ADR 0011](../decisions/0011-delete-run-directories.md).
- `SkillInstaller` may write the shipped skill into the project's integration skills directory; it
  never writes run state.

See [§8 Crosscutting Concepts](08-crosscutting-concepts.md) for how these are enforced.
