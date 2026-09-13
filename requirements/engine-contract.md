# Engine Contract: S01

| Field | Value |
|---|---|
| Status | Recorded from `../spec-kit` source at `1.0.6.dev0`; S03 structured-gate behavior confirmed live |
| Story | S01 - Own one workflow run (implemented) |
| Plan | [S01 - Implementation Plan](S01-implementation-plan.md) |
| Sources | `src/specify_cli/workflows/_commands.py`, `engine.py`, `catalog.py`, `overlays/` |

This note records the confirmed engine behavior Cockpit depends on. Each confirmed row has a
Cockpit test or a code reference; unresolved behaviors are listed in section 8 and remain the
only Phase 0 work that needs a live spike.

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

## 8. Pending live spikes

These behaviors are documented from source but were not exercised against the real engine in
this environment; they remain the only Phase 0 follow-ups:

1. Raw ANSI/CR output and prompt behavior of each step type through the real CLI.
2. Exact persisted state after SIGINT during command, prompt, shell, and gate steps.
3. ~~Real gate pause/exit behavior with and without a bound `verdict_input` under non-TTY stdin.~~
   Resolved for the structured path in section 9; interactive-prompt behavior remains S04.
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
