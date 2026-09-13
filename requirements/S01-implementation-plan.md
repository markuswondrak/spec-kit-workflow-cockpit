# Implementation Plan: S01 - Own one workflow run

| Field | Value |
|---|---|
| Status | Implemented; live PTY/SIGINT spikes remain per `engine-contract.md` §8 |
| Story | [S01 - Own one workflow run](S01-owned-run.md) |
| Requirements | FR-1, FR-2 (basic), FR-6 (basic) |
| Baseline | `PRD.md`, `TUI_DESIGN.md`, `UI_DESIGN.md`, `ARCHITECTURE.md`, `prototype/` |
| Package | Top-level `workflow_cockpit/` (standalone distribution exposing `workflow-cockpit`) |

This plan realizes S01 against the real engine in `../spec-kit`. Product contract stays in
`PRD.md`; runtime component names stay in `ARCHITECTURE.md`; visual behavior stays in
`UI_DESIGN.md`. This file only sequences the work.

## 1. Scope

### In

- Project discovery (nearest Spec Kit root or `--project`).
- Preflight: platform, Git worktree with a valid `HEAD`, `.specify/` init, and a pinned
  `specify` executable in the tested version range.
- Workflow selection, effective summary and step list after enabled overlays, schema-driven
  input form, and required/type validation.
- Dirty-worktree warning plus one confirmation; Start is never blocked.
- Start records `HEAD`, preallocates the run ID, and lets one `EngineSupervisor` own the run
  under an internal output PTY.
- Read-only, bounded, normalized live Engine Output.
- Basic run state, current step, branch, baseline commit, elapsed time (<= 500 ms).
- Confirmed Abort: signal a verified live owned group only; if a paused command has exited,
  record the Cockpit-owned abort without signaling a stale process-group ID.
- Success, failure, and Cockpit-owned abort outcomes that require acknowledgment to exit.
- Resize guard below the minimum size.

### Out (later stories)

- Full control-flow Runway, branches, loops, attempts (S02).
- Worktree Changes, diff/rendered views, `$EDITOR` (S03).
- Structured or interactive gate decisions (S03/S04).
- Context index and Cockpit skill (S05).
- Catchable-signal cleanup, stale-read recovery, and full resilience hardening (S06).

## 2. Verified engine contract (`../spec-kit`)

- No abort command exists. Commands are `run/resume/status/list/...`
  (`src/specify_cli/workflows/_commands.py`). `aborted` is set only by a gate
  `on_reject: abort` (`engine.py:1264-1278`).
- SIGINT persistence is step-dependent. The outer engine path can persist `paused` and
  `workflow_interrupted`, but nested command/prompt/gate handlers may instead persist failure,
  rejection, or another terminal state. Cockpit's abort outcome never depends on one engine
  status.
- A gate with no valid bound verdict pauses under non-TTY stdin and the `specify` command exits.
  A valid `verdict_input` may decide before the TTY check.
- Run files include `workflow.yml`, `state.json`, `inputs.json`, and `log.jsonl`. Only state and
  inputs use separate atomic replacements; workflow creation and log appends are not atomic as
  a group. Readers tolerate incomplete run directories and partial trailing log records.
- `run --json` emits its result only on exit. The supported engine accepts a caller-selected
  `SPECKIT_WORKFLOW_RUN_ID`; Cockpit uses that exact ID instead of discovering directories.
- Registry: `.specify/workflows/workflow-registry.json` ->
  `{schema_version, workflows:{id:{name,version,description,source,enabled,...}}}`; inputs and
  steps are not in it (`catalog.py:62-76`, `_commands.py:1077-1094`).
- Engine project lookup uses `SPECIFY_INIT_DIR` before cwd and does not provide Cockpit's
  nearest-parent discovery. Every child receives the selected canonical root in both cwd and
  `SPECIFY_INIT_DIR`, overriding any inherited value.
- The PATH engine observed during planning is `specify 0.16.1`, below the candidate
  `>=1.0,<2.0` range. Phase 0 uses and records an explicit executable instead of ambient PATH.

## 3. Locked decisions

1. **Abort**: while the owned child is live, SIGINT its verified process group, wait the fixed
   grace interval established in Phase 0, then TERM/KILL and reap it. Clear PID/PGID ownership
   immediately after reaping. At a persisted pause with no live child, Abort only records the
   Cockpit-owned outcome. Never signal a retained numeric PGID. Engine status is evidence, not
   the definition of Cockpit abort.
2. **Compatibility**: one resolved executable is used for preflight and every child. The
   candidate range is `>=1.0,<2.0`; Phase 0 may narrow it and fixes development/prerelease
   handling before implementation. Refuse outside the resulting tested range with guidance.
3. **Package root**: top-level `workflow_cockpit/`, separate from the design assets in `requirements/`.
4. **Run identity and project**: generate a collision-resistant run ID before spawn, fail if its
   directory already exists, and pass it as `SPECKIT_WORKFLOW_RUN_ID`. Pass argv without a shell;
   set cwd and `SPECIFY_INIT_DIR` to the selected canonical project root.
5. **Effective definition**: S01 resolves the base definition plus enabled overlays using the
   versioned Phase 0 contract. It defers graph projection, not definition resolution. After the
   persisted `workflow.yml` is complete and parseable, compare its normalized parsed structure
   with the launch model and surface a fatal contract error on semantic mismatch. Missing or
   temporarily incomplete content remains initializing until the child exits or the startup
   deadline established in Phase 0 expires.
6. **Engine abstraction**: presentation calls only `CockpitSession`; S01 exposes `select`,
   `configure`, `start`, and `abort`. Gate decision intents are added in S03/S04, not as S01
   no-ops. PTY-vs-pipe remains internal to the engine boundary.
7. **UI screens**: Preflight, one Launch screen with in-place configuration, Cockpit, Confirm,
   Help, plus an in-screen resize guard (matches `UI_DESIGN.md:172-213`,
   `prototype/launch.py:72-107`, `components.py:44-66`).
8. **Minimum size**: 88 x 36; compact below 112 columns / short below 38 rows. Small terminals
   enter the in-app resize guard rather than failing preflight.

## 4. Phase 0 - Engine spike (before product code)

Use the exact candidate executable from `../spec-kit` in a temp Spec Kit project. Keep the
resulting contract note and convert each confirmed behavior into an integration test. Phase 1
does not start until all exit criteria pass or the plan is amended. Exit criteria:

1. Resolve and record the executable path and exact version. Define prerelease handling and the
   final bounded supported range; probe all required capabilities rather than version alone.
2. Confirm caller-selected run IDs, collision behavior, run-file creation order, and isolation
   from a concurrent external run. Confirm inherited `SPECIFY_INIT_DIR` is overridden.
3. Document base, registry, and overlay formats and verify effective step/input resolution
   against the persisted run `workflow.yml`, including overlay-added required inputs.
4. Confirm S01 transport: PTY stdout/stderr with non-TTY stdin; record gate behavior both with
   and without a valid bound verdict and capture raw ANSI/CR output.
5. Exercise SIGINT during command, prompt, shell, and gate steps. Record all possible persisted
   states, choose fixed SIGINT/TERM/KILL bounds, and prove escalation affects only a verified
   live owned group. Prove paused-without-process Abort sends no signal.
6. Record which output each step type emits live through the CLI. Engine Output promises live
   CLI-emitted output only; persisted step results may be shown later and must not be presented
   as live PTY output.
7. Write `requirements/engine-contract.md` with sources, executable/version, results, and exact
   subprocess argv/environment contracts.

## 5. Module layout

```
pyproject.toml                 build metadata, dependencies, console script, package data
workflow_cockpit/
  __init__.py
  cli.py                     entry point, --project, startup
  bootstrap/
    discovery.py             ProjectDiscovery
    preflight.py             Preflight
    compatibility.py         executable resolution and tested compatibility range
  services/
    registry.py              WorkflowRegistry
    definition.py            effective WorkflowDefinitionResolver (base + overlays)
    run_state.py             RunStateReader (tolerant, skip unchanged)
    git.py                   GitService: HEAD, branch, dirty
    snapshot.py              RunSnapshot and outcome value objects
  engine/
    supervisor.py            EngineSupervisor
    pty_session.py           PtySession
    normalizer.py            OutputNormalizer
  session/
    cockpit_session.py       CockpitSession facade (select/configure/start/abort)
    polling.py               PollingLoop
  ui/
    app.py                   CockpitApp
    screens/preflight.py     actionable prerequisite checklist
    screens/launch.py        select + in-place configure
    screens/cockpit.py       run, output, outcome
    screens/confirm.py       ConfirmScreen
    screens/help.py          HelpScreen
    widgets/                 HeaderRail, StepRail, EngineOutput, CommandRail, ResizeGuard
    view_model.py            CockpitViewModel
    styles.tcss              tokens from prototype/styles.tcss
tests/
  unit/  textual/  contract/  pty/  fixtures/
```

Production UI starts from the prototype's palette and widget vocabulary
(`prototype/styles.tcss:1-11`, `components.py`, `launch.py`, `review.py`); the prototype stays a
design reference and is not imported by production code.

## 6. Phases

### Phase 1 - Packaging, bootstrap, and environment

- Add `pyproject.toml`: build backend, supported Python, bounded Textual/PyYAML/packaging runtime
  dependencies, `workflow-cockpit` console script, `styles.tcss` package data, ruff and test
  configuration. Add an isolated wheel-install and `workflow-cockpit --help` smoke test.
- `cli.py`: parse `--project` and start `CockpitApp`; there is no Cockpit config file.
- `ProjectDiscovery`: walk up for `.specify/`; validate an explicit path; invoke children with
  cwd and `SPECIFY_INIT_DIR` set to the canonical root.
- `Preflight` and `PreflightScreen`: check platform (Linux/macOS/WSL), Git worktree with valid
  `HEAD`, project init, executable, and compatibility; present actionable errors. Terminal size
  is handled by the resize guard and can recover without restarting.
- `Compatibility`: resolve one executable, parse `specify --version`, enforce the Phase 0
  bounded range, run the non-mutating capability probes selected in Phase 0, and retain that
  executable path for execution.
- Tests (unit): discovery from nested dirs, explicit path, missing init, version parsing and
  lower/upper/prerelease refusal, inherited environment override, detached/unborn `HEAD`, and
  preflight diagnostics. Textual tests cover shrinking below 88 x 36 and recovery.

### Phase 2 - Read model (no Textual imports)

- `WorkflowRegistry`: validate fail-closed without crashing. List runnable enabled workflows;
  omit disabled workflows and report corrupt entries or missing definitions explicitly.
- `WorkflowDefinitionResolver`: read YAML and apply enabled overlays according to the versioned
  engine contract; expose effective name/description/top-level steps and typed inputs
  (`string|number|boolean`, required/default/enum/prompt). Graph construction remains S02.
- `RunStateReader`: read `state.json`/`inputs.json`/`log.jsonl`; skip unchanged (mtime/size);
  include inode/replacement identity; tolerate incomplete directories, independently replaced
  state/inputs, and a partial final log record; treat `state.json` as authoritative.
- `GitService`: current `HEAD`/branch, dirty detection. Diff/classification deferred to S03.
- `RunSnapshot`: immutable status, active step (or last step for terminal states), branch,
  baseline, elapsed, output tail, process condition, and outcome.
- Tests (unit): malformed/partial JSON, missing and same-size replaced files, input typing and
  argv construction, base-plus-overlay resolution, disabled/corrupt registry entries, tracked/
  staged/untracked dirt, detached HEAD, and branch changes that do not alter the baseline.
- Contract tests cover delayed/incomplete persisted `workflow.yml`, normalized semantic equality,
  and a fatal mismatch between the launch model and persisted effective definition.

### Phase 3 - Engine boundary

- `PtySession`: allocate the internal output PTY with non-TTY stdin, perform incremental
  non-blocking reads, allow one process at a time, and never forward user keystrokes.
- `OutputNormalizer`: decode with replacement, normalize CR/LF, strip ANSI/control sequences,
  emit complete lines plus the current partial line, enforce a bounded tail with a truncation
  marker.
- `EngineSupervisor`: accept the preallocated run ID and pinned executable; reject an existing
  run directory; launch argv without a shell under a new process group with the locked project
  environment; guard against a second process; clear PID/PGID only after reaping. Abort signals
  only a verified live group (SIGINT -> fixed grace -> TERM -> fixed grace -> KILL); a paused
  run with no child becomes Cockpit-aborted without a signal.
- Serialize abort and reap under one supervisor lock. A group is verified live only while the
  owned child has not been reaped, its return code is unset, and its OS process group still
  equals the PGID recorded at spawn; failure of any check means no signal is sent.
- Reconcile process and persisted state explicitly: running/live, paused/exited, completed,
  persisted failure, child exit before state, aborting, fully reaped abort, and unexpected death.
  Terminal outcomes are published only after the child is reaped; failure includes the persisted
  step/cause when available and expands the output tail.
- Tests (PTY/contract): split UTF-8, CR/CRLF, ANSI/OSC/C0 controls, partial final lines, one
  truncation marker and bounded memory; exact run ID amid concurrent external creation;
  single-active guard; no UI keystroke reaches stdin; SIGINT/TERM/KILL escalation, descendants
  cleaned, unrelated sibling preserved, and stale PGID never signaled.

### Phase 4 - Coordination

- `CockpitSession`: facade with `select`, `configure`, `start`, and `abort`;
  composes services; owns the run_id and session outcome.
- `PollingLoop`: tick from an injected monotonic clock every 250 ms; publish immutable snapshots
  via `asyncio.Queue` + `post_message`; refresh elapsed time every tick and branch independently
  of unchanged run files; never block the render path.
- Catchable-signal cleanup is S06. S01 owns confirmed interactive Abort and normal close only.
- Tests (unit/async): intent routing, snapshot publication within 500 ms without wall-clock
  sleeps, unchanged-file skipping without freezing elapsed/branch, live-process Abort, and
  paused-without-process Abort.

### Phase 5 - Textual presentation

- `LaunchScreen`: workflow list, brief, in-place configure; typed inputs; required-field inline
  validation; dirty-warning strip plus one confirmation; singular Start in `signal`.
- `CockpitScreen`: HeaderRail (state word+symbol, branch, baseline, elapsed, workflow, run ID);
  low-fidelity StepRail placeholder (S02 replaces it); Focus overview; read-only bounded
  `RichLog` EngineOutput with auto-scroll pause on scroll-up and `l`/`e`/`End`; CommandRail with
  confirmed Abort (`q`/`x`); HelpScreen; resize guard.
- Minimal paused surface in S01: paused step/message as read-only text and Abort only. No disabled
  decision controls, CONTEXT path, or Worktree Changes; those arrive in S03/S05.
- Outcome surfaces: success, failure, and Cockpit-owned abort; each requires acknowledgment
  (`enter`) to exit.
- `CockpitViewModel`: map `RunSnapshot` to widgets, preserving focus, selection, and scroll.
- S01-specific Help and command rails advertise only actions implemented in S01.
- Tests (`App.run_test()`): selection and configuration across all supported input types,
  required/whitespace/default/enum validation, dirty
  confirmation, Start transition, live state updates, output behavior, abort confirmation and
  outcome, acknowledgment exit via Enter (and `q` only where explicitly shown), contextual help,
  resize guard below 88 x 36, and state preservation after resizing back.

### Phase 6 - Integration and end-to-end

- Mandatory fake-executable contract tests cover argv/environment, malformed output, early exit,
  exact run ownership, process transitions, and cleanup.
- Mandatory PTY fixture-process tests cover stream normalization and process groups.
- Mandatory pinned real-`specify` tests use tiny deterministic workflows for linear success,
  non-TTY gate pause, failure, overlays, and abort. They never depend on ambient PATH or external
  agent integrations.
- Assert exact run identity, live state/output, outcome acknowledgment, and no leftover group.
- Run the full unit + Textual + contract + PTY suites.

## 7. Acceptance mapping

| S01 criterion | Phase / component |
|---|---|
| Discover root / explicit path | 1 - ProjectDiscovery |
| Preflight Git, init, executable, bounded version range | 1 - PreflightScreen, Compatibility |
| Select workflow, effective steps/inputs, validation | 2/5 - Resolver, LaunchScreen |
| Dirty warning without blocking, one confirmation | 5 - LaunchScreen (UI_DESIGN:212) |
| Start records HEAD, exact run ID, one supervisor | 3/4 - EngineSupervisor, CockpitSession |
| One process group, output-producing commands under internal PTY | 3 - PtySession, EngineSupervisor |
| Read-only bounded normalized Engine Output | 3/5 - OutputNormalizer, EngineOutput |
| State/step/branch/baseline/elapsed within 500 ms | 2/4/5 - RunStateReader, PollingLoop, HeaderRail |
| Confirmed Abort + bounded cleanup/no stale signal | 3/4 - EngineSupervisor abort paths |
| Outcomes visible until acknowledgment | 5 - outcome surfaces |
| Unit / Textual / contract / PTY tests | 0-6 |

The test suite must additionally assert: baseline capture occurs after dirty confirmation and
immediately before spawn; a second Start cannot spawn; ordinary keys never reach child stdin;
another process creating a run cannot change Cockpit's owned ID; state, branch, step, and elapsed
changes appear within 500 ms; and every outcome remains until explicit acknowledgment.

## 8. Deferred / assumptions

- Decisions and Worktree Changes are intentionally not in S01. S03/S04 add `decide()` and gate
  details when behavior exists.
- S01 resolves overlays for accurate launch steps and inputs; S02 adds complete control-flow
  parsing and projection.
- S01 requires an executable in the bounded range finalized by Phase 0; ambient PATH is not an
  execution contract.
- Testing uses `unittest` with `IsolatedAsyncioTestCase` and Textual `App.run_test()`; lint with
  `ruff`. Runtime dependencies are declared directly and do not rely on the `specify`
  installation environment.

## 9. Risks

- PTY output with non-TTY stdin, effective overlay resolution, and interrupt persistence are
  versioned engine contracts; Phase 0 gates implementation on them.
- Engine status after SIGINT varies by step. Cockpit must not offer or imply resume after its own
  abort, regardless of persisted status.
- Registry/definition corruption is a non-crashing fatal launch diagnostic, never an empty or
  default catalog.
- Shell-step output may not be emitted live by the CLI. The UI labels only captured CLI output
  as live and does not manufacture a second execution-state model from output.
