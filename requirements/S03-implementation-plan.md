# Implementation Plan: S03 - Review and decide a structured gate

| Field | Value |
|---|---|
| Status | Implemented; interim PTY stdin is `/dev/null` per `ARCHITECTURE.md` (S04 replaces it) |
| Story | S03 - Review and decide a structured gate (implemented) |
| Requirements | FR-3, FR-5 (structured) |
| Dependencies | S01, S02 (implemented) |
| Baseline | `PRD.md`, `TUI_DESIGN.md`, `UI_DESIGN.md`, `ARCHITECTURE.md`, `engine-contract.md` |
| Package | Top-level `workflow_cockpit/` |

This plan sequences S03 only. The persisted engine state remains authoritative; Cockpit reads it,
compares the current worktree with the fixed S01 baseline, and sends a structured `resume` command
only after the user confirms a declared gate option. Interactive PTY input remains S04 work.

## 1. Scope

### In

- Detect a paused declared gate from persisted `state.json`, including its current step, resolved
  message, and exact resolved option order from the recorded gate result.
- Enrich the static graph's gate metadata with `verdict_input` and `on_reject` solely to select the
  structured strategy and explain a declared rejection effect.
- Worktree Changes against the fixed Start commit, including branch commits and dirty changes that
  existed before Start; exclude `.specify/` and Git-ignored files.
- File classification for created, modified, deleted, renamed, and conflicted files; text diff and
  rendered/current content; binary metadata; bounded large-text preview; clear empty state.
- Paused-gate review as the default Focus mode, with State, Changes, Gate, and collapsible Engine
  Output reachable without abandoning the review.
- Existing selected-file launch through `$EDITOR`, with Textual suspended and restored.
- Confirmed structured decisions for gates declaring `verdict_input`, using an internally supervised
  `specify workflow resume <run_id> -i <name>=<choice> --json` process.
- Unit, Textual, Git integration, fake-executable contract, and pinned-real-engine coverage for the
  structured path.

### Out

- Mapping choices to a live interactive prompt or writing to the PTY (S04).
- Cockpit context-index creation and skill invocation guidance (S05).
- Signal cleanup and broad stale-read/editor failure recovery hardening (S06).
- Agent-specific visual-token templates (S07).

## 2. Verified engine contract

- A gate persists its resolved `message`, `options`, `on_reject`, and `choice` in
  `state.json.step_results[<current_step_id>].output`; a pause is a gate only when
  `state.status == "paused"` and the current runtime step maps to a declared gate.
- The gate persists options after expression resolution, so those persisted options, not a fallback
  Cockpit vocabulary or stale definition values, are displayed and submitted in their recorded order.
- A `verdict_input` must name a declared string workflow input. `resume` merges `-i` input values over
  persisted inputs, sets state to running, and re-executes the current step from `current_step_index`.
- A reject/abort choice follows the workflow's own `on_reject` behavior: `abort` makes the engine
  aborted, `skip` completes the gate, and `retry` pauses again after clearing the bound verdict input.
- Initial non-interactive gate processes normally exit after persisting `paused`; a structured resume
  therefore starts a new supervised child. Its exit status is diagnostic only: the subsequent
  persisted state determines the Cockpit state and available actions.

Before implementation, extend `engine-contract.md` with a live pinned-engine probe covering a
structured gate's pause, resume argv/output, successful option, retry, skip, abort, and invalid resume
failure. The fake executable remains the deterministic contract seam; the real test is skipped only
when the pinned executable is unavailable.

## 3. Locked decisions

1. **Gate evidence is persisted-state first.** Add an immutable `GateSnapshot` to `RunSnapshot` with
   runtime step id, declared step id, message, options, `verdict_input`, and `on_reject`. Build it only
   when the persisted state identifies a paused declared gate. `RunStateReader` exposes the raw current
   step result needed for this extraction without interpreting a malformed result as a gate.
2. **Exact options win.** The gate message and options come from the persisted result's `output` only
   when their shapes are valid. If the engine says the current step is a gate but its result is missing
   or malformed, retain the paused state, show a persistent review error, and offer Abort rather than
   inventing choices. The graph/definition supplies `verdict_input` and `on_reject` after the runtime
   id is mapped to its declared node.
3. **S03 serves structured gates only.** A paused gate without `verdict_input` shows its evidence but
   no decision controls and clearly directs the user to S04 capability. It never writes a choice to the
   PTY. A valid `verdict_input` always takes precedence over a live process condition.
4. **One owned sequential supervisor.** Refactor `EngineSupervisor` around a private spawn operation
   and add a resume-specific entry point. It permits a new child only after the previous owned child is
   reaped, retains the original run ID, creates a new process group and PTY, preserves normalized output
   history, and refuses a second simultaneous resume. It does not check that the existing run directory
   is absent, because that check applies only to initial Start.
5. **Decision state follows persisted state.** `CockpitSession.decide(choice)` validates that its latest
   snapshot is paused at a structured gate and that `choice` exactly matches one persisted option. It
   starts the resume child with argv rather than a shell. While that child is live, the command rail has
   no choices. After it reaps, polling reads the state again: running, terminal, a retry pause, or an
   unchanged pause are all rendered as persisted. A launch/CLI failure is shown as diagnostic feedback;
   it does not overwrite persisted state or synthesize a terminal outcome.
6. **Worktree comparison is baseline-to-worktree.** `GitService` uses `git diff --no-ext-diff
   --find-renames --name-status -z <baseline>` for tracked changes, combines it with
   `git ls-files --others --exclude-standard -z` for untracked files, and deduplicates by final path.
   This includes commits on a branch created after Start as well as index and working-tree changes.
   Every path below `.specify/` is discarded before presentation; `--exclude-standard` omits ignored
   untracked files. All Git path arguments use `--` and NUL-delimited parsing.
7. **Review content is bounded and non-blocking.** `GitService` returns immutable file summaries and
   lazily obtains content on selection. It identifies binary content from Git's binary diff signal or
   a NUL byte in a bounded sample. Diff and rendered text use byte limits; large content reports its
   limit and requires an explicit full-load action. Git subprocesses, diffs, and file reads run in a
   Textual thread worker; a last completed immutable review remains visible during refresh.
8. **Review refresh preservation.** `CockpitSession` owns the latest immutable review data, and
   `CockpitScreen` requests a refresh at its existing paused polling cadence through an exclusive worker.
   Snapshot publication incorporates the last completed review result. The screen retains selected path,
   filter, view (`diff` or `rendered`), and document scroll when the path still exists; otherwise it
   selects the first available file or the empty state.
9. **Editor is controlled but not a lifecycle writer.** `o` is available only for an existing selected
   file at a paused gate when `$EDITOR` is non-empty. Parse it with `shlex.split`, append the validated
   project-relative path, and run it without a shell inside Textual's suspend/restore context. Deleted
   files, binary metadata, an unset/invalid editor, non-paused state, and paths outside the worktree
   produce no editor launch. Refresh review on return and restore the selected path.
10. **Confirmation is option-neutral.** Every declared option, including one labelled `approve`, uses
    the same `ConfirmScreen`. The sheet repeats the exact choice and shows only a declared known effect
    such as `on_reject: retry`; it never assigns approve/reject semantics to arbitrary labels.

## 4. Module layout

```
workflow_cockpit/
  engine/
    supervisor.py            sequential structured-resume supervision and resume argv
  services/
    git.py                   Worktree Changes model, Git reads, content and preview helpers
    run_state.py             tolerant current gate-result extraction input
    snapshot.py              GateSnapshot, review value objects, RunSnapshot fields
    graph.py                 declared gate verdict_input/on_reject metadata
  session/
    cockpit_session.py       gate extraction, decide(), cached review refresh
  ui/
    widgets/                 changed-file index and review-document widgets
    screens/cockpit.py       Changes/Gate modes, refresh worker, editor and decision intents
    screens/confirm.py       neutral declared-choice confirmation copy
    screens/help.py          S03 keyboard and structured-gate help
    styles.tcss              review layout, file statuses, empty/error states
tests/
  unit/test_git.py           classification, filtering, content and preview behavior
  unit/test_run_state.py     gate-result extraction tolerance
  unit/test_session.py       structured decision validation and reconciliation
  textual/test_cockpit.py    review modes, confirmation, selection and editor eligibility
  contract/test_engine_contract.py  exact structured resume argv and failure handling
  contract/test_real_engine.py      structured gate outcomes when pinned engine is present
```

Keep review widgets small and component-scoped. The existing `#overview` canvas may compose the file
index and document surface; do not create a second screen or a second Git state model.

## 5. Phases

### Phase 1 - Gate and review read models

- Add `GateSnapshot`, `ChangeKind`, `ChangedFile`, `ReviewDocument`, and `ReviewSnapshot` as frozen
  value objects. Include review status/error/revision so an unchanged or failed refresh does not erase
  the last usable review.
- Extend `RunStateData` with a safe accessor for the current result and construct `GateSnapshot` in the
  session after resolving `current_step_id` through the graph. Validate result/output shapes and preserve
  exact strings and option order.
- Extend `GraphNode` parsing with `verdict_input` and `on_reject`; nested gates receive the same
  metadata as top-level gates.
- Add `GitService.worktree_changes(baseline)`, `document(path, view, full=False)`, and path-safe current
  file resolution. Treat Git exit code 1 from a diff as a normal difference, not a service failure.
- Unit tests: absent/non-gate/malformed paused data; resolved runtime id; expression-resolved message;
  option ordering/case; nested verdict gates; added/modified/deleted/renamed/conflicted/untracked files;
  `.specify` and ignored exclusions; dirty baseline; branch commit comparison; binary NUL detection;
  small and large previews; empty changes; special-character/NUL path parsing.

### Phase 2 - Session and structured resume

- Add `build_resume_argv(executable, run_id, verdict_input, choice)` and a sequential
  `EngineSupervisor.resume(...)` operation. It uses the locked project environment and a new PTY/process
  group but continues the existing normalized output tail.
- Add `CockpitSession.refresh_review()` and keep its completed result behind a lock so snapshot assembly
  is fast. Do not run Git from the ordinary 250 ms snapshot tick.
- Add `CockpitSession.decide(choice)`: refresh/read state, validate the current structured gate and exact
  option, reject stale/running/terminal calls with `SessionError`, construct the resume argv, and delegate
  to the supervisor. Retain any command exception as session diagnostic feedback while leaving persisted
  state authoritative.
- Reconcile resume exit with state exactly as initial execution: state may become running, completed,
  aborted, failed, paused for retry, or remain paused after a CLI failure. A retry pause receives fresh
  persisted gate data and decisions again.
- Unit and contract tests: invalid session calls; option mismatch/case mismatch; no duplicate concurrent
  resume; exact resume argv/environment; resume output appended; retry returns a decidable gate; skip and
  abort retain engine semantics; fake CLI failure preserves paused state and reports the error.

### Phase 3 - Review and decision surface

- Add `c`, `d`, `r`, `o`, `/`, and generated `1` through `9` bindings. `s`, `c`, `g`, and `l` remain
  reachable while paused; the default paused mode is Gate and Engine Output remains a short tail until
  expanded.
- Render the amber gate message without silent truncation, the Worktree Changes count and baseline,
  a narrow status/path index, and the selected document. Use `+`, `M`, `-`, `R`, and conflict text rather
  than color alone. Diff defaults for modified files; rendered defaults for newly created Markdown.
- Render deleted text from the baseline blob, binary path/change/size metadata without attempting text,
  and the explicit bounded-preview/full-load state for large text. Render a decidable empty review state.
- Make pause refresh use an exclusive Textual worker. Apply a result only if it belongs to the current
  run and preserve selection/filter/view/scroll as described above. Never block rendering on Git or disk.
- Generate equal-weight decision controls from `GateSnapshot.options`. Pressing a shortcut or selecting
  an option opens confirmation; only confirmation calls `session.decide`. Disable/hide choices for an
  unstructured, malformed, or resume-in-progress gate while preserving Abort.
- Implement the editor action with eligibility feedback and terminal restoration. Update command rail and
  help text so S03 advertises only structured gate decisions.
- Textual tests: automatic gate mode and highlighted Runway; mode/output reachability; diff/rendered
  switch; empty and binary/large/deleted content; selection and scroll retention across refresh; dynamic
  option order/shortcuts; cancel and confirm; choices unavailable while resuming; editor availability and
  suspended launcher invocation; `$EDITOR` unset/deleted/running rejection.

### Phase 4 - End-to-end verification

- Add a temporary real Git repository fixture that commits the Start baseline, creates branch commits,
  edits tracked files, stages/deletes/renames files, creates ignored and untracked files, and writes a
  `.specify` artifact. Assert the presented set and baseline behavior rather than command implementation
  details.
- Extend the fake `specify` fixture to persist a paused structured gate and record a resume invocation.
  Assert one confirmed decision starts exactly one `resume ... -i name=choice --json` child with the
  original run ID and project environment.
- Add pinned-real-engine tests for a `verdict_input` gate covering continue, reject-to-retry then approve,
  reject-to-skip, and reject-to-abort. Assert persisted state, not terminal output wording.
- Run `ruff check .` and the unit, Textual, contract, PTY, and available real-engine suites.

## 6. Acceptance mapping

| S03 criterion | Phase / component |
|---|---|
| Paused gate, step, message, exact options | 1 - `RunStateReader`, `GateSnapshot`, graph metadata |
| Runway highlight, automatic Gate Focus, output tail | 3 - `CockpitScreen`, existing Runway/EngineOutput |
| Paused State, Changes, Gate, and expanded output | 3 - Focus bindings and mode machine |
| Fixed-baseline Worktree Changes including pre-Start dirt | 1 - `GitService.worktree_changes` |
| Created/modified/deleted/renamed, `.specify`/ignored excluded | 1 - NUL Git status/diff parsing |
| Text diff/rendered, binary metadata, bounded large preview | 1/3 - document service and review widgets |
| Paused refresh and empty state | 1/3 - cached review + exclusive worker |
| `$EDITOR` suspension and availability constraints | 3 - editor action |
| Confirm every choice; no review-completeness gate | 3 - dynamic options plus `ConfirmScreen` |
| `verdict_input` structured resume and retry/skip preservation | 2/4 - supervisor, session, real-engine fixtures |
| Persisted state authoritative after submission | 2 - session reconciliation and polling |
| Required unit/Textual/integration coverage | 1-4 |

## 7. Deferred assumptions and risks

- S03 assumes the verified engine contract that a structured paused gate's initial child has exited. The
  resume supervisor must still support a live-process check and reject resume if the state/process pairing
  is inconsistent rather than address a stale process.
- Rename detection is Git heuristic output. Present Git's reported rename status and old/new paths; do not
  claim source attribution or calculate an independent rename algorithm.
- Exact persisted gate options can differ from static YAML due to expression evaluation. This is intended:
  static metadata chooses the transport while persisted data is the decision evidence.
- A full large-file view can consume memory. Bound default previews and make full load explicit; S06 owns
  broader resource limits and recoverable worker-error polish.
- Git commands may fail because the worktree changes concurrently. Preserve the last completed review,
  show the failure, and leave the gate decidable when its persisted state remains valid.
