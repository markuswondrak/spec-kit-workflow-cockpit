# Architecture: Workflow Cockpit

| Field | Value |
|---|---|
| Status | Design draft |
| Stack | Python and Textual |
| Product | Standalone `workflow-cockpit` package and CLI |
| Baseline | `PRD.md`, `TUI_DESIGN.md`, `UI_DESIGN.md`, S1-S6 |

This document names the components and how they are wired together. It refines the runtime
architecture in `TUI_DESIGN.md`; it does not change the product contract in `PRD.md`.

## 1. Architectural principles

- One Cockpit process owns exactly one run in one project/worktree.
- The engine is untouched: workflow mutations use existing `specify` CLI commands, Abort uses OS
  signals against a verified live owned group, reads use persisted run files, and no engine
  internals are imported.
- Persisted run files are authoritative for engine workflow state. Cockpit owns only its
  in-memory session lifecycle outcome, including user-requested Abort, and persists no separate
  workflow state or history.
- One `EngineSupervisor` owns at most one active engine process group and is the only
  lifecycle writer. A numeric PID/PGID is actionable only while its child is verified live and
  is cleared immediately after reaping.
- The PTY is internal and never user-visible; ordinary keystrokes are never forwarded to it.
- The UI never blocks: polling, process I/O, Git, and diffing run off the render path.
- Core services have no Textual imports, so they are testable without a running app.

## 2. Layers and components

### 2.1 Bootstrap and environment

| Component | Responsibility |
|---|---|
| `cli` | `workflow-cockpit` entry point, argument parsing (`--project`), app startup; no Cockpit config file. |
| `ProjectDiscovery` | Locate the nearest Spec Kit project root from the current directory. |
| `Preflight` | Validate platform, Git worktree with `HEAD`, project initialization, and prerequisites with actionable errors. |
| `Compatibility` | Resolve and retain one `specify` executable; enforce the bounded range finalized from the initial `>=1.0,<2.0` candidate and run its non-mutating capability probes. |

### 2.2 Engine boundary

| Component | Responsibility |
|---|---|
| `EngineSupervisor` | Validate the session's preallocated run ID; start or resume with the pinned executable and locked project environment; own/reap one process group; signal only a verified live group. |
| `PtySession` | Own the internal output PTY per output-producing command; incremental non-blocking reads. S1 uses non-TTY stdin; later interactive input is enabled only by its validated strategy. |
| `OutputNormalizer` | Decode with replacement, normalize carriage returns, strip ANSI/control sequences, retain complete lines plus the partial line. |
| `VerdictInputDecider` | Structured gate decisions via `resume -i <name>=<choice> --json`. |
| `InternalPtyDecider` | Fallback gate decisions written once to the managed PTY. |

### 2.3 Read model and domain services

| Component | Responsibility |
|---|---|
| `WorkflowRegistry` | Parse `workflow-registry.json` and list installed workflows. |
| `WorkflowDefinitionResolver` | Parse YAML and apply enabled overlays under the versioned engine contract; provide effective launch inputs and steps. |
| `WorkflowDefinitionParser` | Starting in S2, turn the effective definition into declared control flow. |
| `ControlFlowGraph` | Generic graph of nodes, edges, branches, loops, gates, and overlays. |
| `RunStateReader` | Tolerant reads of independently written `state.json`, `inputs.json`, and `log.jsonl`; skip unchanged files while detecting atomic replacements. |
| `GraphProjector` | Combine static `ControlFlowGraph` with runtime state into node status, active path, attempts, and timings. |
| `GitService` | Record the fixed start SHA; classify Worktree Changes; exclude `.specify/` and ignored files; detect binary and large files; produce diff and rendered content. |
| `ContextIndexWriter` | Write `cockpit-context.md` after Start; failure is reported but never interrupts the run. |
| `EditorLauncher` | Suspend and restore Textual around `$EDITOR` at a paused gate only. |

### 2.4 Coordination

| Component | Responsibility |
|---|---|
| `CockpitSession` | Facade that composes services. S1 exposes select, configure, start, and abort; S3 adds decide. |
| `PollingLoop` | Publish an immutable `RunSnapshot` on a 250 ms monotonic schedule. |
| `RunSnapshot` | Immutable view of status, graph projection, gate, review data, output tail, and outcome. |
| `SignalHandler` | On catchable `SIGINT`, `SIGHUP`, `SIGTERM`, attempt bounded best-effort abort without confirmation. |

### 2.5 Presentation (Textual)

| Component | Responsibility |
|---|---|
| `CockpitApp` | Textual application and screen routing. |
| Screens | Preflight, Launch (select then in-place configure), Cockpit, Confirm, Help; a resize-guard widget replaces the layout below the minimum size without exiting. |
| `HeaderRail` | Product, state, branch, baseline, elapsed, workflow, run ID. |
| `Runway` | Scrollable control-flow graph with runtime overlay. |
| `Focus` | State, Changes, Gate, and Outcome surfaces with `d`/`r` diff and rendered views. |
| `EngineOutput` | Bounded, read-only `RichLog` fed from the supervisor. |
| `CommandRail` | Actions valid in the current state, including dynamic gate choices. |
| `CockpitViewModel` | Map `RunSnapshot` to renderable state; preserve selection, focus, and scroll across refreshes. |

### 2.6 Shipped artifact

| Component | Responsibility |
|---|---|
| `cockpit-skill` | Markdown skill for a user-chosen external agent; consumes only the context-index path and reads authoritative sources. No runtime coupling to Cockpit. |

### 2.7 Distribution

The repository has one `pyproject.toml` declaring the `workflow-cockpit` console script, bounded
Python/runtime dependencies, and packaged Textual CSS. PyYAML and version-specifier support are
direct Cockpit dependencies; Cockpit never relies on packages from the `specify` installation.
An isolated wheel smoke test verifies the executable and package data.

## 3. Wiring

```
                 workflow-cockpit (one Textual process, one run, one worktree)
┌──────────────────────────────── Presentation (Textual) ────────────────────────────────┐
│  Screens/Widgets  ◀── CockpitViewModel ◀── RunSnapshot (immutable)                      │
│         │ intent                    ▲                                                   │
└─────────┼───────────────────────────┼─────────────────────────────────────────────────┘
          ▼                           │ Textual message / asyncio queue
┌──────────────── CockpitSession (coordination) ────────────────────────────────────────┐
│  PollingLoop ──▶ RunStateReader ──▶ [GraphProjector from S2] ──▶ RunSnapshot           │
│  decide ──▶ Decider (S3/S4) ┐                                                         │
│  start/abort ────────┼──▶ EngineSupervisor ──▶ PtySession ──▶ OutputNormalizer ──▶ Log │
└──────────────────────┼─────────────────────────────────────────────────────────────────┘
                       ▼                         reads      ▲            writes
               specify CLI (start/resume)       persisted run files     context-index.md
               OS signals (live-group Abort only)
```

### 3.1 Observe

1. `EngineSupervisor` starts or resumes the pinned engine executable under an internal output
   PTY, with the selected canonical project in cwd and `SPECIFY_INIT_DIR`.
2. `PtySession` reads output incrementally; `OutputNormalizer` produces clean lines.
3. Lines flow into a bounded queue behind the read-only `RichLog`; `log.jsonl` remains the
   complete source.
4. `PollingLoop` reads persisted state, skips unchanged files, and publishes a new
   `RunSnapshot`.
5. Starting in S2, `GraphProjector` overlays runtime state onto the declared graph. The
   ViewModel updates available widgets without stealing focus or scroll.

### 3.2 Start

1. `WorkflowDefinitionResolver` applies enabled overlays before the config screen presents the
   effective step list and schema-driven input set.
2. `GitService` records the fixed baseline commit after dirty confirmation and immediately
   before spawn; a dirty worktree warns but does not block.
3. `CockpitSession` generates a collision-resistant run ID; `EngineSupervisor` fails if its
   directory exists, then launches argv without a shell with `SPECKIT_WORKFLOW_RUN_ID` set to
   that ID.
4. Cockpit observes only that exact run directory. Once its persisted `workflow.yml` is complete
   and parseable, the resolver compares normalized parsed structures and fails on a semantic
   mismatch; incomplete content remains initializing until child exit or the startup deadline.
5. Starting in S5, `ContextIndexWriter` writes the stable index and the UI displays its path plus
   skill help.

### 3.3 Gate

1. A `RunSnapshot` marks a paused gate with its step, message, and exact declared options.
2. Runway highlights the gate and Focus opens the review surface automatically.
3. `GitService` provides Worktree Changes against the fixed start commit; Focus toggles diff
   and rendered views.
4. A confirmed choice is dispatched: structured resume when `verdict_input` exists, otherwise
   one write to the PTY via `InternalPtyDecider`.
5. Persisted state remains authoritative. An unverified PTY write is shown but not resent; if
   state does not advance, only confirmed Abort is offered.

S4 replaces S1's non-TTY stdin with validated, Cockpit-controlled PTY stdin for workflows that
need an interactive gate. No user keystrokes are forwarded. `InternalPtyDecider` writes only
while that original supervised process and PTY are still live; it never addresses a reaped
process. Structured gates whose command exited use a newly supervised `resume` process.

### 3.4 Lifecycle

1. If the owned child is verified live, Abort sends SIGINT to its process group, waits the
   configured bounded grace period, escalates with TERM/KILL if required, reaps the child, and
   then clears PID/PGID ownership.
2. If a paused engine command has already exited, Abort sends no signal and records only the
   Cockpit-owned aborted outcome. A retained numeric PGID is never used after reaping.
3. Engine state after interruption is step-dependent and may be paused, failed, aborted, stale,
   or absent. Cockpit owns its outcome and never resumes that run in the same session.
4. `q` and interactive close confirm Abort while a run is active.
5. Starting in S6, catchable termination signals trigger the same cleanup path without
   confirmation.

### 3.5 Process/state reconciliation

Process state and persisted engine state are separate evidence joined in `RunSnapshot`:

| Process | Persisted state | Cockpit interpretation |
|---|---|---|
| live | running/initializing | Running; continue polling and reading output. |
| reaped normally | paused | Paused with no signalable process; S1 offers Abort only. |
| reaped | completed | Success after output drain and reap. |
| reaped | failed/aborted | Engine terminal result with persisted step/cause when available. |
| reaped | missing/nonterminal | Unexpected process death; preserve output tail and report failure. |
| live | any, after confirmed Abort | Aborting; signal only the verified owned group. |
| reaped | any, after Cockpit Abort began | Cockpit-aborted after cleanup completes. |

`current_step_id` is shown as current only in an active/paused state and as last step in a
terminal state. Output is diagnostic evidence, not a source for inferred workflow state.

Abort and reap are serialized by the supervisor. A group is verified live only while the owned
child has not been reaped, its return code is unset, and its OS process group equals the PGID
recorded at spawn. If any check fails, no signal is sent. PID/PGID ownership is cleared as part
of reaping while the same supervisor lock is held.

## 4. Concurrency

- One asyncio event loop hosts Textual and the async subprocess/PTY tasks. The polling loop uses
  a 250 ms monotonic schedule so observable updates remain within the 500 ms product bound.
- Blocking work (Git, diffing, large files) runs in worker threads so rendering stays
  responsive.
- State is passed as immutable `RunSnapshot` objects; no shared mutable model crosses the
  presentation boundary.

## 5. Boundaries

- `CockpitSession` is the only API the presentation layer calls.
- `EngineSupervisor` is the only component that writes workflow lifecycle.
- `RunStateReader`, `WorkflowRegistry`, and `WorkflowDefinitionResolver` are the only readers of
  their respective engine-persisted/catalog/definition files.
- `ContextIndexWriter` is the only Cockpit writer inside `.specify/`.
- No component imports engine internals or starts a second state model.
- Every engine child uses the executable retained by `Compatibility`, argv without a shell, the
  selected canonical cwd/`SPECIFY_INIT_DIR`, and an explicit Cockpit-owned run ID.
- The engine transport (PTY or pipe) and decision strategy (structured resume or PTY write)
  are internal to the engine boundary; the presentation sees only `CockpitSession`.

## 6. Testing seams

| Layer | Test type |
|---|---|
| Registry, effective definition resolution, graph parsing, projection, diff classification, compatibility, deciders | Unit tests |
| Screens, focus, modes, confirmation, outcomes | Textual `App.run_test()` |
| Executable/project/run identity, process lifecycle, output normalization, gate submission, cleanup, signals | Contract and subprocess/PTY integration against fixtures |

Fixtures cover linear success, `verdict_input`, interactive PTY gates, branch creation,
retry/skip, empty changes, no-gate runs, failure, abort, and termination signals.

## 7. Requirement traceability

| Story | Primary components |
|---|---|
| S1 Own one run | `cli`, `Preflight`, `Launch`, `EngineSupervisor`, `EngineOutput`, Abort path |
| S2 Runway | `WorkflowDefinitionParser`, `ControlFlowGraph`, `GraphProjector`, `Runway` |
| S3 Structured gate | `RunStateReader`, `GitService`, `Focus/Changes`, `VerdictInputDecider` |
| S4 Interactive gate | `InternalPtyDecider`, `PtySession`, unverified-submission state |
| S5 Skill and context | `ContextIndexWriter`, `cockpit-skill` |
| S6 Resilience | `PollingLoop`, `SignalHandler`, error handling across services |

## 8. Resolved decisions

1. Snapshot transport: an `asyncio.Queue` published with `post_message`; presentation never
   polls services directly.
2. Heavy I/O execution: Textual `@work(thread=True)` for Git, diffing, and large-file work.
3. Minimum terminal size is **88 x 36**; the app enters a reversible resize guard below it. S1
   ships a low-fidelity step rail in place of the
   S2 control-flow Runway.
4. The `specify` transport (PTY or pipe) and decision strategy stay internal to the engine
   boundary; the presentation sees only `CockpitSession`.
5. Run identity is allocated before spawn and passed through `SPECKIT_WORKFLOW_RUN_ID`; directory
   diffing is never used to claim ownership.
6. A process group is signalable only while its owned child is verified live. Paused runs whose
   command exited are aborted locally without a signal.
7. The launch model is the effective base-plus-overlay definition. S2 adds graph semantics but
   does not repair an intentionally incomplete S1 definition.
