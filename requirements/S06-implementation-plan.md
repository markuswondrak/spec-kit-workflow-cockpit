# Implementation Plan: S06 - Resilient operation

| Field | Value |
|---|---|
| Status | Planned |
| Story | [S06 - Resilient operation](S06-resilience.md) |
| Requirements | FR-6, quality requirements |
| Dependencies | S1-S5 (implemented) |
| Baseline | `PRD.md`, `TUI_DESIGN.md`, `UI_DESIGN.md`, `ARCHITECTURE.md`, `engine-contract.md` |

This plan hardens the S1-S5 loop for real runs. It does not add product surfaces; it makes
existing services survive bad files, blocked reads, child-process death, and termination
signals. Product contract stays in `PRD.md`, component names in `ARCHITECTURE.md`, and visual
rules in `UI_DESIGN.md`.

## 1. Scope

### In

- Non-blocking polling: snapshot production moves off the render path and stale/branch reads no
  longer freeze the UI.
- Last-good preservation and one `STALE` marker when a background read fails after a good read.
- Actionable error surfacing for partial JSON, missing files, malformed log events,
  child-process death, context-index failure, Git failure, and editor failure.
- Catchable-signal cleanup (`SIGINT`, `SIGHUP`, `SIGTERM`) that aborts the recorded engine group
  without confirmation and exits.
- Platform contract: Linux/macOS/WSL coverage, explicit native-Windows refusal, and a documented
  no-guarantee boundary for `SIGKILL`, host loss, power loss, and interpreter failure.
- Keyboard-accessibility and contextual-help audit across all screens.
- Resilience end-to-end fixtures for branch creation, empty changes, no-gate execution, and
  termination signals; capability-gated skips so all suites are runnable on every declared
  platform.
- A CI test workflow for the supported POSIX matrix. It runs the complete available unit,
  Textual, fake-engine contract, and PTY suites; the real-engine suite remains explicitly
  capability-gated when its pinned executable is absent.

### Out (other stories)

- `SIGKILL`/host-loss/power-loss/interpreter-failure cleanup (no guarantee by design).
- Styling templates (S7), Markdown rendering (S8), and release/distribution polish (S9). S09
  may extend the S06 CI workflow with build, wheel-install, and publication checks.
- New workflow shapes, engine changes, or new Cockpit persistence.
- Native Windows support; Windows users use WSL.

## 2. Current state after S1-S5 (already satisfies S06)

| S06 criterion | Where it already holds |
|---|---|
| Platform Linux/macOS/WSL; Windows refused | `bootstrap/preflight.py::_is_supported_platform`, `tests/unit/test_preflight.py` |
| Resize guard below minimum | `ui/screens/base.py`, `ui/widgets/ResizeGuard`, `test_resize_guard_blocks_and_recovers` |
| Cockpit keyboard controls and in-app help | `ui/screens/help.py`, bindings in `cockpit.py` |
| Polling skips unchanged state files | `services/run_state.py` inode+mtime signature; incremental `services/log_aggregator.py` |
| Partial JSON / missing files tolerated | `RunStateReader._read_json` returns cached value on parse failure |
| Malformed log events ignored | `RunLogAggregator` skips bad records; `RunStateReader._read_log` skips bad lines |
| Child-process death reported | `CockpitSession._outcome` unexpected-exit branch |
| Context-index failure non-fatal | `CockpitSession._write_context_index`, `test_context_failure_does_not_interrupt_run` |
| Editor failure surfaced | `ui/screens/review_mixin.py::action_open_editor` |
| Confirmed Abort for interactive exit | `cockpit.py::action_quit` / `action_abort` |
| Bounded Abort of a verified live group | `engine/supervisor.py::abort` |

## 3. Gaps to close

1. **No signal handling.** `SIGINT`, `SIGHUP`, and `SIGTERM` have no Cockpit handler, so a
   closed terminal or `kill` can leave the engine group running. `SignalHandler` is declared in
   `ARCHITECTURE.md` §2.4 but not implemented.
2. **Polling blocks the render path.** `CockpitScreen.on_mount` runs `self.set_interval(0.25,
   self._refresh)` on the event loop, and `_refresh` calls `CockpitSession.snapshot()`, which
   runs `GitService.branch()` (a subprocess) and synchronous file reads every tick.
3. **No last-good / `STALE` handling.** `RunSnapshot.stale` is never set. `GitService` raises
   on timeout/OSError, and an unguarded call in `snapshot()` would break the poll instead of
   preserving the last branch. UI_DESIGN §10 requires a `STALE` marker on background read
   failure.
4. **Inconsistent error surfacing.** Failures land in screen-local `_diagnostic` or
   `context_error`; there is no single persistent, actionable error strip. Some paths (poll
   failure, contract-read error, stale refresh) have no presentation contract.
5. **Fixture coverage gaps.** The real-engine suite lacks branch creation, empty changes,
   no-gate execution, and termination-signal cases. Existing PTY tests signal the engine group,
   not the Cockpit process, so they do not exercise process-level signal handling.
6. **Platform capability gating.** PTY/signal tests assume POSIX; there is no shared skip
   helper, so the suite is not portable across the declared platform matrix.

## 4. Locked decisions

1. **Signals.** `SignalHandler` (coordination layer) is constructed with a session provider
   (`lambda: app.session`), not a session value, because preflight creates the session later. It
   registers `SIGINT`/`SIGHUP`/`SIGTERM` with the running asyncio loop via
   `add_signal_handler`, overriding the app's normal SIGINT exit path while mounted. The handler
   schedules one shutdown task and is idempotent (a second signal during shutdown is ignored).
   The task awaits the existing bounded `EngineSupervisor.abort()` path through
   `CockpitSession.abort()`, obtains its explicit cleanup result, and only then exits the app. It
   adds no cancellable deadline around `asyncio.to_thread`: cancelling that await would leave an
   abort thread running. If the supervisor exhausts its fixed escalation bounds without reaping,
   the result records an unsuccessful best-effort cleanup attempt and the app exits; the existing
   reaper remains responsible for any later child exit, but no new cleanup work is started.
   It never waits for confirmation. Unsupported signal APIs (non-POSIX) retain default behavior
   because Windows is unsupported.
2. **Polling off the render path.** A 250 ms timer only requests a poll; a single-exclusive
   `@work(thread=True)` worker produces the immutable state snapshot, publishes it with a
   Textual `post_message`, and the screen renders that message. Overlapping polls are
   suppressed. Branch lookup is an independently scheduled, cached worker with a short timeout;
   it must never delay state publication. Run-log timing reads are incremental and bounded per
   poll, never a full-file read. The presentation continues to see only `RunSnapshot`, per
   `ARCHITECTURE.md` §3.1.
3. **Narrow synchronization.** A session-state `RLock` protects lifecycle fields and snapshot
   publication, but is never held across Git subprocesses, file I/O, or the supervisor's bounded
   abort wait. `RunStateReader` and `RunLogAggregator` each own a private lock that covers their
   bounded I/O plus mutable cache update, so polling and decisions cannot race those caches.
4. **Last good wins.** JSON readers stat before and after a read, retry once when the signature
   changes, and classify the result precisely. A missing or invalid source before its first valid
   read remains `initializing` without `STALE`. A source that changes during either read is an
   in-progress replacement: retain the prior value and retry next poll without `STALE`. A stable
   missing, unreadable, undecodable, or invalid source after a valid read retains that value,
   sets `stale=True`, and carries a diagnostic; `stale` clears only after the affected source
   reads successfully. An incomplete trailing JSONL record is normal and does not mark stale;
   a complete newline-delimited malformed event is diagnostic-only and retains prior timings.
   Polling never raises into the event loop.
5. **One error model.** Every recoverable failure is reported as `RunSnapshot.diagnostic` (with
   `stale` when freshness is unavailable); the screen renders it as a persistent strip above the
   command rail with the failed operation, the authoritative state, and the next available
   action. A complete malformed run-log event is retained as a diagnostic while prior timing data
   remains intact; an incomplete trailing event remains silently pending. Transient success
   feedback remains on the command rail for at most two seconds.
6. **Signal vs interactive exit.** `q` and window close still require confirmed Abort while a
   run is active. Catchable signals abort without confirmation, matching FR-6.
7. **Platform boundary.** Linux, macOS, and WSL are supported and tested. Native Windows is
   refused in preflight with actionable text. The S06 CI workflow runs Linux and macOS; a
   documented WSL runner command executes the same capability-gated suite under WSL. `SIGKILL`,
   host loss, power loss, and interpreter failure are documented in in-app help and the README as
   carrying no cleanup guarantee.
8. **No new persistence.** The only Cockpit write remains the context index under engine
   metadata. A before/after filesystem test whitelists the owned run directory and `current_run`
   index, and rejects any other Cockpit-owned write outside `.specify/workflows/runs/`.

## 5. Module layout

```
workflow_cockpit/
  session/
    signals.py           new: SignalHandler (register, idempotent shutdown, bounded)
    polling.py           change: snapshot-production seam for the worker
    cockpit_session.py   change: narrow lifecycle lock, guarded Git, stale/diagnostic derivation
  services/
    run_state.py         change: expose read-failure state; strengthen file signature
    git.py               change: classify and tolerate failure with an actionable message
    snapshot.py          change: document/enforce stale + diagnostic semantics (fields exist)
  engine/
    supervisor.py        change: return an explicit bounded AbortResult after cleanup attempts
  ui/
    app.py               change: create and tear down SignalHandler around run()
    messages.py          new: SnapshotPublished Textual message
    screens/cockpit.py   change: request/consume published snapshots; error strip; STALE
    widgets/__init__.py  change: HeaderRail/CommandRail render stale and error text
.github/workflows/
  test.yml               new: Linux/macOS test matrix for S06 capability-gated suites
tests/
  support.py             change: shared platform-capability skip helpers and fakes
  unit/                  test_signals.py, test_run_state.py, test_git.py, test_polling.py
  textual/               test_resilience.py (signals, stale, error strip, keyboard journey)
  contract/              test_real_engine.py (branch, empty, no-gate, termination)
  pty/                   test_signals.py (Cockpit PID signal reaps its owned group)
```

## 6. Phases

### Phase 1 - Platform and capability contract

- Confirm `_is_supported_platform` returns the expected label for Linux, WSL, and macOS, and a
  refusal for `win32`; add unit coverage for each value.
- Add shared skip helpers (`tests/support.py`): `requires_posix`, `requires_pty`,
  `requires_real_specify`, so unit/Textual/PTY suites are runnable where capabilities permit.
- Document the supported matrix and the `SIGKILL`/host-loss no-guarantee boundary in the README
  and in the Help screen.
- Add `.github/workflows/test.yml`: run `ruff` plus unit, Textual, fake-engine contract, and PTY
  suites on supported Linux/macOS runners. The real-engine contract suite is skipped unless a
  pinned executable for the declared range is provisioned. Run the same job on a WSL-capable
  runner when available; otherwise document the exact WSL command and record its result for each
  supported release before declaring that release supported.
- Tests: `test_preflight.py` platform labels; README/help assertion that the boundary text is
  present; CI configuration smoke validation where available.

### Phase 2 - Non-blocking polling and last-good state

- `polling.py`: split "is a poll due" from "produce a state snapshot" so production can run in a
  worker; keep the injected monotonic clock and 250 ms cadence. Publish state even while branch
  refresh is pending or unavailable.
- `ui/messages.py`: add `SnapshotPublished(snapshot)`.
- `ui/screens/cockpit.py`: replace the direct `_refresh` timer body with a poll-request timer
  plus a single-exclusive thread worker that publishes `SnapshotPublished`; move the existing
  render logic into the message handler. Suppress overlapping requests.
- `cockpit_session.py`: add a narrow lifecycle lock. Capture `_branch` through an independently
  scheduled, guarded `_refresh_branch()` that keeps the last good value and records a diagnostic
  on failure. Do not hold that lock while running Git, reading files, or waiting for Abort.
- `services/git.py`: use a short branch-refresh timeout and return a typed, classified failure on
  timeout/OSError; never let a Git failure abort a poll.
- `services/run_state.py`: signature includes size as well as inode+mtime. Stat before and after
  each JSON read, retry once on a changing signature, and expose per-source freshness so the
  session distinguishes a never-valid startup file, an in-progress replacement, a stable failed
  read after a good value, and an expected incomplete trailing JSONL record. Read the displayed
  JSONL tail from a bounded end-of-file window rather than `read_bytes()` on the full log. Give
  the reader a private lock covering its bounded I/O and cache update.
- `services/log_aggregator.py`: cap each incremental read and retain the offset/partial record,
  so a rapidly growing `log.jsonl` cannot delay subsequent state snapshots. Record complete,
  newline-delimited bad events as diagnostics without discarding prior timing data. Give the
  aggregator a private lock covering its bounded I/O and cache update.
- Tests (unit): poll worker publishes exactly one snapshot per due tick; unchanged state files do
  not re-parse; a slow or failed Git probe cannot delay state publication; Git failure preserves
  the previous branch; a failed state read after a good read keeps the last status and marks
  stale; an unstable before/after file signature, startup-incomplete state, and a partial trailing
  event do not mark stale; a stable malformed state or complete bad event reports a diagnostic.
  Tests (Textual): UI stays interactive while a slow Git probe runs; `STALE` appears and clears
  after recovery.

### Phase 3 - Signal-driven shutdown

- Add `session/signals.py::SignalHandler(session_provider, app)`:
  - register the three catchable signals on the running loop; override the active app SIGINT
    behavior while mounted; keep registrations for removal;
  - on signal, set a shutting-down flag and schedule one shutdown task;
  - shutdown obtains the current session from the provider, runs `session.abort()` in a worker
    when a run is active and not terminal, awaits that bounded operation to its explicit cleanup
    result, then exits the app; with no active run it exits immediately;
  - do not cancel or time out the `asyncio.to_thread` await independently of the supervisor;
    record an exhausted supervisor escalation as best-effort cleanup before exit;
  - ignore repeat signals and remove handlers on close.
- `engine/supervisor.py`: make `abort()` return an immutable `AbortResult` that records whether a
  live group was signalled, whether its owned child was reaped, and the highest escalation used.
  The method remains bounded by its configured grace periods. `CockpitSession.abort()` propagates
  that result to `SignalHandler` while preserving the existing interactive-Abort snapshot API.
- `ui/app.py`: construct the handler once the loop is running and remove it on teardown. Verify
  that a signal during an active run always reaches the abort path rather than an immediate quit.
- Tests (unit): idempotence; active-run abort called once; inactive-run exits without abort; hard
  supervisor-bound cleanup result; handler removal; and the late-created session provider. Tests
  (PTY/integration): start an isolated Cockpit process against a long-running fixture, deliver
  each catchable signal to the Cockpit PID, and assert its owned group is reaped before the
  Cockpit process exits. Tests (Textual): a simulated signal during an active run shows the
  aborting path and exits without a confirmation prompt.

### Phase 4 - Error surfacing and accessibility

- Define the persistent error strip: failed operation, authoritative state, next available
  action (UI_DESIGN §10). Route `RunSnapshot.diagnostic` and each service's current error
  (`context_error`, review error, editor error, Git failure, poll failure) through it; keep the
  last good graph with a `STALE` marker. Complete malformed state/log records identify the source
  and remain actionable; incomplete startup JSON and a trailing JSONL record remain normal
  pending writes.
- Keep transient success feedback limited to two seconds.
- Add `?` help bindings and short screen-specific help for Preflight and Launch, then audit that
  every action on Preflight, Launch, Cockpit, Confirm, and Help is reachable and operable by
  keyboard and no screen traps focus.
- Tests (Textual): partial JSON then good state, missing file, malformed log event, Git failure,
  context-index failure, and editor failure each preserve the last good surface and show an
  actionable strip; keyboard-only journey covers each screen and help overlay.

### Phase 5 - Resilience end-to-end fixtures

- Extend real-engine/near-real fixtures to cover: branch creation, a gate over an empty feature
  directory, no-gate execution, and termination signals. The termination fixture launches an
  isolated Cockpit process and signals its PID, not its engine child directly.
- Assert exact run identity, last-good behavior after a mid-run malformed write, Abort and
  signal close after cleanup, and no leftover engine group.
- Assert the no-history rule: after a session, no new Cockpit-owned files exist outside
  `.specify/workflows/runs/<run_id>` and the `current_run` index.
- Tests are capability-gated so they run on Linux/macOS/WSL and skip cleanly where unsupported.

### Phase 6 - Verification

- Run the full unit, Textual, fake-engine contract, and PTY suites with `ruff` locally and on the
  Linux/macOS CI matrix; record which tests require POSIX/PTY/real-`specify` and therefore skip
  on other platforms. Run the documented equivalent command under WSL.
- Re-check the acceptance matrix in section 7 against named tests.

## 7. Acceptance mapping

| S06 criterion | Phase / component |
|---|---|
| Linux/macOS/WSL; Windows explicitly unsupported | 1 - Preflight platform checks + tests |
| English UI, keyboard accessible, in-app help | 4 - accessibility audit, Help screen |
| Blocking resize message below minimum size | Already S1; re-asserted in Phase 4 |
| Polling does not block and skips unchanged files | 2 - worker + message, `RunStateReader` |
| Partial JSON / missing / malformed / child failure / context / editor preserve last good + actionable errors | 2 and 4 - stale model, error strip, guarded Git |
| Interactive exit requires confirmed Abort while active | Already S1; preserved in Phase 3/4 |
| Catchable signals abort and clean up without confirmation | 3 - `SignalHandler` |
| No cleanup guarantee for `SIGKILL`/host loss/power loss/interpreter failure | 1 - documentation |
| No history outside engine metadata | 5 - no-history assertion |
| Unit/Textual/subprocess-PTY suites run in CI where capabilities permit | 1, 5, and 6 - CI matrix and capability-gated suites |
| Fixtures: success, both gates, branch, retry/skip, empty, no-gate, failure, abort, termination | 5 - end-to-end fixtures |
| No workflow-engine changes or internals imports | All phases - existing boundary preserved |

## 8. Deferred / assumptions

- S06 owns the test CI workflow required by its acceptance criteria. S09 extends it with build,
  clean-wheel-install, documentation, and release checks.
- Signal behavior for `SIGKILL`, host loss, power loss, and interpreter failure is explicitly out
  of scope and only documented.
- The poll worker reuses the existing `PollingLoop` cadence and clock; no new timer system.
- App-provided fakes continue to back unit and Textual tests. Only the isolated Cockpit-process
  integration fixture sends a real catchable signal; unit tests call the handler seam directly.

## 9. Risks

- **Textual signal interaction.** The implementation must install and test an explicit active
  `SIGINT` override, so this is a Phase 3 acceptance condition rather than a fallback decision.
- **Thread races.** Moving snapshot production to a worker introduces concurrency with decision
  and abort workers. Narrow lifecycle/read-model locks are the mitigation; Phase 2 tests
  interleave a poll with a submission and an abort.
- **Over-eager stale marking.** The implementation compares before/after file signatures and
  retries once, distinguishing an in-progress replacement, a never-valid startup write, and an
  incomplete trailing event from stable corruption of a previously valid source; only stable
  corruption produces `STALE`.
- **Signal test flakiness.** Delivering real signals in tests can be racy; prefer driving
  `SignalHandler` directly in unit tests and reserve real-signal delivery for one PTY test with
  generous bounds.
