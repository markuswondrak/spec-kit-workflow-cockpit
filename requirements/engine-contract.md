# Engine Contract: S01-S04

| Field | Value |
|---|---|
| Status | Recorded from `../spec-kit` source at `1.0.6.dev0`; S03/S04 gate behavior confirmed live |
| Story | S01-S04 - Own, observe, and decide one workflow run |
| Plan | [S01 - Implementation Plan](S01-implementation-plan.md) |
| Sources | `src/specify_cli/workflows/_commands.py`, `engine.py`, `catalog.py`, `overlays/` |

This note records the confirmed engine behavior Cockpit depends on. Each confirmed row has a
Cockpit test or a code reference. Unsupported workflow shapes fail before Cockpit spawns a child.

## 1. Executable and version

- One resolved executable is retained by `Compatibility` and used for preflight and every child.
- `specify --version` prints `specify <pep440>` (`_commands.py` version callback). Observed on the
  development venv: `specify 1.0.6.dev0`; ambient PATH: `specify 0.16.1`.
- Tested range: `>=1.0,<2.0`. Prereleases whose release segment is in range are accepted
  (`1.0.6.dev0`); `0.16.1` and `2.0.0` are refused. Implemented in
  `bootstrap/compatibility.py`; tested in `tests/unit/test_compatibility.py`.
- Capability probes are non-mutating: `specify workflow --help` must list
  `run resume status list` and `specify workflow run --help` must list `--input/-i` and `--json`.

## 2. Launch argv and environment

- Cockpit launches `specify workflow run <workflow_id> -i <name>=<value> ...` with **no shell**.
  The `-i` values are strings; the engine coerces them to the declared input type
  (`_parse_input_values`, `_resolve_inputs`/`_coerce_input`).
- cwd is the selected canonical project root. `SPECIFY_INIT_DIR` is set to that same root on
  every child, overriding any inherited value.
- `SPECKIT_WORKFLOW_RUN_ID` is set to Cockpit's preallocated ID; `WorkflowEngine.execute` uses
  it verbatim instead of generating one (`engine.py:1008`).
- The engine creates `runs/<run_id>/` with `mkdir(parents=True, exist_ok=True)`. Cockpit refuses
  to spawn when that directory already exists, so an existing run is never reused.
- Verified end-to-end against a fake executable in `tests/contract/test_engine_contract.py`.

## 3. Run directory and files

- Run files: `workflow.yml` (a copy of the definition, written first), `state.json` and
  `inputs.json` (atomic temp-file + `os.replace`), and append-only `log.jsonl`.
- `state.json` fields: `run_id`, `workflow_id`, `installed_workflow_id`,
  `installed_registry_root`, `status`, `current_step_index`, `current_step_id`, `step_results`,
  `workflow_dir`, `created_at`, `updated_at`, `error`.
- `status` values: `created`, `running`, `paused`, `completed`, `failed`, `aborted`.
- `inputs.json` holds `{"inputs": {...}}`.
- Readers tolerate a missing directory, partial trailing JSON, independently replaced
  `state.json`/`inputs.json` (detected by inode), and a partial trailing `log.jsonl` record.
  Implemented in `services/run_state.py`; tested in `tests/unit/test_run_state.py`.
- `state.json` is authoritative; Cockpit never writes engine files.

## 4. Registry

- `.specify/workflows/workflow-registry.json` ->
  `{schema_version, workflows: {id: {name, version, description, source, enabled, ...}}}`.
- Inputs and steps are **not** in the registry; they come from the workflow definition.
- Disabled entries are omitted from the runnable list. A missing, unreadable, or malformed
  registry fails closed (never an empty catalog). Implemented in `services/registry.py`.

## 5. Definitions and overlays

- Base definition: `.specify/workflows/<id>/workflow.yml` with `workflow` metadata, `inputs`, and
  `steps`. Step `type` defaults to `command`; `type: gate` carries `message`, `options`,
  `verdict_input`, and `on_reject`.
- Overlays: `.specify/workflows/overlays/<id>/*.yml` with `id`, `extends`, `priority`, `enabled`,
  and `edits`. Edit operations are `insert_before`, `insert_after`, `replace`, and `remove`,
  anchored by base step id. Lower priority numbers win; disabled overlays are skipped.
- Cockpit reimplements resolution (no engine imports) in `services/definition.py`; tested in
  `tests/unit/test_definition.py`.

## 6. Transport (PTY output, non-TTY stdin)

- Every output-producing command runs with stdout/stderr on an internal PTY. stdin is
  `/dev/null`, not the PTY slave, so `sys.stdin.isatty()` is false: a `gate` step without an
  available verdict therefore pauses (PAUSED) instead of blocking on an interactive prompt.
- Output is decoded incrementally (UTF-8, replacement on error), CR/LF normalized, ANSI/OSC/C0
  controls stripped, and retained as complete lines plus the current partial line, bounded with
  one truncation marker. Implemented in `engine/normalizer.py`; tested in
  `tests/unit/test_normalizer.py` and through a real PTY in `tests/pty/test_pty.py`.
- Confirmed live against `1.0.6.dev0`: a `verdict_input` gate pauses after the initial `run`
  child exits, and each `resume` child re-executes the gate. Asserted by
  `tests/contract/test_real_engine.py`.

## 7. Abort

- The engine exposes **no abort command**; the only stop mechanism is a signal to the process
  group.
- Cockpit sends SIGINT to the verified live owned process group, waits a bounded grace period,
  then TERM, then KILL, and reaps the child. A group is signalable only while the owned child is
  unreaped, `poll()` is `None`, and its OS process group equals the PGID recorded at spawn.
- When no live child exists (for example a paused run whose command exited), Abort records the
  Cockpit-owned outcome without signaling a stale PGID, and never resumes the run.
- Implemented in `engine/supervisor.py`; tested in `tests/unit/test_supervisor.py`.

## 8. Unsupported Shapes And Pending Spikes

The following shapes are rejected before Start because the verified engine behavior cannot provide
deterministic prompt ownership or authoritative resolved values for Cockpit:

- A workflow mixing gates with and without `verdict_input`.
- A non-verdict gate with dynamic message or option expressions.
- A non-verdict gate inside a loop or fan-out node.
- A non-verdict gate with `on_reject: retry`.

The remaining source-level follow-ups are diagnostic only and do not enable a new runtime shape:

1. Raw ANSI/CR output and prompt behavior of each step type through the real CLI.
2. Exact persisted state after SIGINT during command, prompt, shell, and gate steps.
3. ~~Real gate pause/exit behavior with and without a bound `verdict_input` under non-TTY stdin.~~
   Resolved for the structured path in section 9; interactive-prompt behavior is recorded in
   section 10.
4. Confirmation that the final fixed SIGINT/TERM/KILL grace bounds are comfortable on the
   supported hardware.

Cockpit's outcome model does not depend on any single one of these: it treats `state.json` as
authoritative evidence and always owns its own abort outcome.

## 9. Structured gates and resume (S03, confirmed live)

- A non-TTY paused gate records `state.json.step_results[<current_step_id>]` with `type: "gate"`,
  `status: "paused"`, and `output = {message, options, on_reject, show_file, choice}`. The options
  are the post-expression resolved values in declared order; `verdict_input` is not copied into
  the result and must come from the workflow definition.
- The engine's own `workflow resume <run_id>` parses repeated `-i key=value` pairs, merges them
  over persisted inputs, sets the run back to running, and re-executes from `current_step_index`.
  Cockpit uses `specify workflow resume <run_id> -i <verdict_input>=<choice> --json`.
- A verdict value is matched to a declared option case-insensitively. When it matches a value
  that the gate treats as a rejection (`reject`/`abort`), `on_reject` decides the outcome:
  `abort` marks the run aborted, `skip` completes the gate and continues, and `retry` clears the
  bound verdict input and pauses the gate again.
- The resume child's exit code is diagnostic only; Cockpit re-reads `state.json` before choosing
  the next presentation state. A failed resume leaves the persisted paused state authoritative.
- Asserted end-to-end against `1.0.6.dev0` in `tests/contract/test_real_engine.py` (continue,
  reject-to-retry then approve, reject-to-skip, and reject-to-abort) and deterministically against
  the fake executable in `tests/contract/test_engine_contract.py`. Cockpit-side extraction is
  tested in `tests/unit/test_gate.py`.

## 10. Interactive gates (S04, confirmed live)

| Field | Value |
|---|---|
| Status | Confirmed live against exact `specify 1.0.6.dev0`; exact `1.0.6` is separately admitted |
| Engine | `/home/markus/workspace/spec-kit/.venv/bin/specify` (or `WORKFLOW_COCKPIT_REAL_SPECIFY`) |
| Encoded in | `workflow_cockpit/engine/interactive_contract.py` (`PromptContract`) |

Spike procedure: a minimal workflow with a non-verdict `gate` step was run through a real PTY
whose slave was the child's stdin/out/err, and the persisted `state.json` and PTY output were
observed while the prompt was live.

1. With the PTY slave attached as child stdin, a gate that **declares** `verdict_input` **and has
   no bound value** also prompts interactively rather than pausing. Therefore Cockpit enables the
   interactive stdin policy only for definitions whose gates are all non-verdict; any
   `verdict_input` gate keeps the non-TTY `/dev/null` policy so its S03 pause/resume path is never
   regressed.
2. A gate that declares **no** `verdict_input` with PTY stdin keeps the supervised `run` child
   alive in front of the prompt and persists `status: "running"` at that gate's
   `current_step_id`. It does **not** persist `paused` while the prompt is live; `running` is the
   authoritative pause identity for the live-prompt case.
3. **Readiness**: for `1.0.6`, a live supervised run whose persisted state is `running` at a
   declared non-verdict gate is deterministically waiting at the prompt. No PTY output matching is
   performed; PTY text is diagnostic only.
4. **Choice-to-input mapping**: the prompt is the engine's builtin `input()` (see
   `workflows/steps/gate/__init__.py`). It accepts either the option name (case-insensitively) or
    its 1-based decimal index, and a newline terminates the line. Cockpit records the safer
    `index` strategy, emitting only ASCII digits plus `b"\n"`. A non-decimal, unknown option loops
    with `Invalid choice. Enter 1-N or an option name.` so only a declared choice may be written.
5. After the mapped input is accepted, the run continues and persists a terminal or subsequent
   state; Cockpit never treats PTY output as proof of submission. A `KeyboardInterrupt`/EOF at the
   prompt defaults to the last option (usually reject) and Control-C returns the run to `PAUSED`.

Covered by `tests/unit/test_interactive_contract.py`, `tests/pty/test_interactive_pty.py`,
`tests/contract/test_engine_contract.py` (fake engine emulating this contract), and
`tests/unit/test_session.py`. The recorded contract is the single source of truth shared by the
fake, PTY, and real-engine tests. Any exact release without a recorded contract is unsupported;
mixed, dynamic, loop/fan-out, and interactive-retry shapes are rejected before Start.
