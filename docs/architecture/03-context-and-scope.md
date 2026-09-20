# 3. Context and Scope

| Field | Value |
|---|---|
| arc42 | 3. Context and Scope |
| Tier | 2 |

## Business context

The Cockpit sits between a user's terminal and an already initialized Spec Kit project. It shows
one run and owns that run's lifecycle; the workflow engine remains the only thing that actually
advances a workflow. It starts a new run, discovers and adopts an existing paused run, or inspects
an existing run read-only under `.specify/workflows/runs/`.

```mermaid
flowchart TB
    user([User]) -->|select, adopt, inspect, decide, abort| cockpit[workflow-cockpit]
    cockpit -->|run / resume / status| specify[specify CLI]
    cockpit -->|read state.json, inputs.json, log.jsonl, workflow.yml| runfiles[(.specify run files)]
    cockpit -->|read HEAD, branch, dirty| git[(Git worktree)]
    cockpit -->|SIGINT, TERM, KILL| group[owned engine process group]
    cockpit -->|write current_run index| runfiles
    cockpit -->|write ownership claim| runfiles
    cockpit -->|suspend + restore| editor[$EDITOR]
    agent([External coding agent]) -->|invoke cockpit-run-context| runfiles
    specify --> runfiles
```

The engine is never modified. Cockpit's only writes inside `.specify/` are the stable context index
at `.specify/workflows/runs/current_run`, which points at the authoritative sources instead of
copying them, and the Cockpit-owned ownership claim `runs/<run_id>/.cockpit-owner.json`, held for
every run Cockpit starts or adopts; lifecycle state changes only through `specify workflow resume`.

## Technical context

| Neighbor | Interface | Direction |
|---|---|---|
| `specify` CLI | `workflow run`, `workflow resume`, capability probes; argv without a shell | write |
| Persisted run files | `state.json`, `inputs.json`, `log.jsonl`, `workflow.yml` | read |
| Run directories | bounded discovery of `.specify/workflows/runs/` and the `current_run` index | read |
| Ownership claim | `runs/<run_id>/.cockpit-owner.json` (owner identity plus liveness evidence) | write |
| Workflow catalog | `.specify/workflows/workflow-registry.json` | read |
| Git | `HEAD`, branch, dirty state via `GitService` | read |
| Engine process group | signals only while the owned child is verified live | signal |
| `$EDITOR` | suspend/restore Textual while paused at a gate | interactive |
| External agent | `cockpit-run-context` skill reads the context index only | read |

## External interfaces

- **Launch:** `workflow-cockpit [--project PATH]`; discovers the nearest Spec Kit project root.
- **Compatibility:** one resolved `specify` executable in the tested range (`>=1.0,<2.0`); refused
  outside it with install guidance.
- **Context index:** a Markdown index (not a snapshot) listing authoritative live sources for a
  user-chosen external agent.
- **Skill:** `cockpit-run-context` consumes only the context-index path and never invokes workflow
  lifecycle commands.
- **Adoption, inspection, and deletion:** the launch screen lists bounded, read-only run descriptors.
  An adoptable `paused` run can be claimed and decided; any usable run (including `running`,
  terminal, or foreign-owned) can be inspected read-only without acquiring a claim or spawning
  processes; and a confirmed user action may delete one stale run directory under the safety rules
  in [ADR 0011](../decisions/0011-delete-run-directories.md).

## Engine contract

Recorded against `specify 1.0.6.dev0` and applied to every build that passes the range check and
workflow capability probe; every row is covered by a Cockpit test or a code reference.

- **Version.** `specify --version` prints `specify <pep440>`. Tested range `>=1.0,<2.0`; prereleases
  in range are accepted, `0.16.1` and `2.0.0` are refused. Probes are non-mutating:
  `specify workflow --help` lists `run resume status list`, and `specify workflow run --help`
  lists `--input/-i` and `--json`.
- **Launch.** `specify workflow run <workflow_id> -i <name>=<value> ...` with **no shell**. `-i`
  values are strings the engine coerces. cwd is the selected canonical project root and
  `SPECIFY_INIT_DIR` is set to it on every child. `SPECKIT_WORKFLOW_RUN_ID` is used verbatim.
- **Run files.** `runs/<run_id>/` contains `workflow.yml` (written first), then atomic
  `state.json`/`inputs.json` (temp file + `os.replace`) and append-only `log.jsonl`. Cockpit
  refuses to spawn when the run directory already exists.
- **Gates.** `verdict_input` gates resume with `resume -i <name>=<choice> --json`; gates without it
  are answered by one write to the managed PTY. The recorded prompt contract applies to any
  supported engine, so interactive gates are not restricted to a single release. The engine exposes
  no abort command, so Abort uses signals.

Out of scope: workflow authoring/installation, built-in multi-run history, multi-run dashboards,
automatic run cleanup or archiving, launching or editing workflow definitions, adopting `running`
runs, taking over a run held by another live process, hosted services, launching or managing coding
agents, notifications, localization, and native Windows. Deleting a stale run is an explicit,
confirmed capability, not automatic history management.
