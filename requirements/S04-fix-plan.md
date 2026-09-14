# S04 Remediation Plan - Unified Gate Decisions

## 1. Purpose

This plan remediates the review findings in the current S04 implementation. The target behavior is:

- A user gets the same review, choice, confirmation, acknowledgement, and recovery experience for
  gates with and without `verdict_input`.
- The UI does not know whether a decision uses structured resume or PTY input.
- A confirmed PTY choice is written at most once, including under concurrent confirmation and Abort.
- Persisted engine state remains authoritative; process and transport details remain diagnostic.
- Unsupported workflow shapes fail closed before Start instead of becoming undecidable during a run.

The implementation must continue to satisfy S03. Structured `verdict_input` remains the preferred
transport whenever the current gate declares it.

## 2. Findings to resolve

1. PTY submission is not atomic. Two concurrent confirmations can both pass validation and write.
2. Interactive gates persist as `running`, while review refresh and editor availability require
   `paused`; the two gate types therefore have different review behavior.
3. Interactive readiness does not verify the complete recorded contract: persisted `running` state,
   the current non-verdict gate, a live owned process, and PTY stdin on that process.
4. Workflow-wide stdin selection makes a workflow containing both gate types undecidable at one of
   its gates.
5. Transport details are exposed through separate snapshot fields, session methods, UI modes, copy,
   and confirmation behavior.
6. Interactive message and options can fall back to unresolved static definition values.
7. PTY partial writes are treated as complete writes.
8. The submission identity relies on `updated_at`, which is not a guaranteed gate-attempt identity.
9. Retry and parallel/fan-out behavior have not been established for interactive gates.
10. Version matching accepts unverified variants by truncating the parsed release tuple.

## 3. Target design

### 3.1 One presentation model

Publish one `GateSnapshot` for every current declared gate, regardless of transport. It contains:

- resolved message and declared options;
- a presentation state: `ready`, `submitted`, `unverified`, or `blocked`;
- an opaque decision token when confirmation is allowed;
- acknowledgement or blocked reason;
- declared effects such as `on_reject`, when known.

`RunSnapshot.interactive` is removed. Transport, prompt strategy, PTY bytes, and the internal gate
attempt identity are not presentation data. Raw persisted status remains available through
`engine_status` and the State view, but the gate surface uses the unified gate state.

The UI calls exactly one facade operation:

```python
session.submit_decision(choice, token)
```

The token is opaque to the UI and protects both structured and PTY confirmations against stale state.

### 3.2 Decision coordinator

Add `workflow_cockpit/session/gate_decision.py` with a stateful `GateDecisionCoordinator`. It owns the
decision state machine instead of leaving it in `CockpitSession`.

Responsibilities:

- combine the current persisted state, declared graph node, process condition, and compatibility
  contract into the unified `GateSnapshot`;
- select structured resume or PTY input internally;
- issue and validate opaque decision tokens;
- serialize submission, Abort visibility, and the write-once ledger;
- reconcile `submitted`, `unverified`, advancement, and a contract-confirmed retry attempt;
- retain a consumed attempt until authoritative evidence proves that the run left it;
- never reset write-once protection merely because `updated_at` changed.

Add the two engine-boundary executors already named by `ARCHITECTURE.md`:

- `VerdictInputDecider`: build and start the validated structured resume command.
- `InternalPtyDecider`: validate the prompt contract, map a declared option, and perform one guarded
  PTY write.

These can live together in `workflow_cockpit/engine/gate_decider.py`; they should remain small and have
no UI concerns. `CockpitSession` supplies current state and lifecycle dependencies, delegates projection
and submission, and publishes the coordinator's snapshot.

Remove from `CockpitSession`:

- `_interactive_enabled`, `_submissions`, and `_reconcile_submissions()`;
- `_interactive_capable()`, `interactive_support()`, and `_interactive_support()`;
- the separate `submit_interactive()` public API;
- direct prompt-contract and choice-mapping imports.

### 3.3 Process and stdin evidence

Replace mutable `EngineSupervisor.interactive` / `set_interactive()` state with an explicit stdin policy
passed when a process is spawned. Record the policy on the active process condition so readiness checks
can prove that the currently owned child has PTY stdin.

Interactive readiness requires all of the following at the same observation:

1. The exact installed version has a verified prompt contract.
2. Persisted state is complete and has status `running`.
3. `current_step_id` resolves to the expected declared gate.
4. That gate does not declare `verdict_input`.
5. The original owned process is live, has not begun Abort, and was spawned with PTY stdin.
6. Authoritative options and message satisfy the verified contract.
7. The gate shape is supported, including retry/fan-out restrictions established in Phase 0.

Writing and Abort are serialized by the supervisor lock. `write_input()` must reject a write after Abort
has been claimed, even if the process has not reaped yet.

### 3.4 Write result semantics

`PtySession` must write the complete payload, retrying interrupted writes and accounting for the byte
count returned by `os.write()`.

The engine boundary returns one of three outcomes:

- `NOT_WRITTEN`: zero bytes were written; no acknowledgement is published.
- `WRITTEN`: the complete mapped input was written exactly once.
- `UNCERTAIN`: a partial write or ambiguous I/O failure occurred.

Both `WRITTEN` and `UNCERTAIN` consume the gate attempt permanently. `UNCERTAIN` is shown as unverified
and allows only Abort. The coordinator reserves the attempt under its lock before invoking the engine
boundary, so a concurrent call cannot also write.

Prefer the contract's verified 1-based index mapping because it emits only ASCII digits plus one newline
and cannot inject content from an option label. If a supported engine requires value mapping, reject
options containing CR, LF, NUL, or other control characters before enabling submission.

## 4. Phase 0 - Complete the engine contract

Extend the real-engine spike before changing runtime behavior. Record evidence in
`requirements/engine-contract.md` and encode only proven behavior.

Verify against every supported `specify` version:

1. Exact version identity, including release, prerelease, postrelease, and local variants. Replace
   release-tuple truncation with an explicit allow-list or exact supported-version predicate.
2. Both accepted choice mappings. Select index mapping if it is verified for all supported versions.
3. Whether persisted `running` state contains resolved gate message/options. Test expressions in both.
   If authoritative resolved values are unavailable, constrain compatible interactive gates to values
   proven equal to the engine prompt and reject dynamic values before Start.
4. `reject` behavior for `on_reject: retry`, `skip`, and `abort`, including process exit and persisted
   transitions. Establish the exact command and stdin policy required to make a retry gate ready again.
5. A workflow containing a structured gate and an interactive gate in both orders.
6. Interactive gates inside sequential loops and parallel/fan-out nodes.

Capability rule:

- Implement a shape only when the spike proves deterministic prompt ownership and continued structured
  preference.
- If mixed or parallel interactive gates cannot be supported safely without modifying the engine,
  reject that effective workflow before Start with an actionable compatibility error. Never start a run
  that Cockpit cannot decide later.
- Add the limitation to `PRD.md`, `ARCHITECTURE.md`, and S04 only if the real contract requires it.

## 5. Phase 1 - Unified domain model

1. Extend gate extraction so a verified live interactive prompt produces the same `GateSnapshot` shape
   as a structured pause.
2. Keep persisted evidence authoritative. Do not parse prompt output to infer readiness or choices.
3. Add gate presentation state and the opaque token to `GateSnapshot`; remove `InteractiveSupport`,
   `SubmissionRecord`, and `RunSnapshot.interactive` after callers migrate.
4. Replace `stable_pause_key()` with coordinator-owned attempt tracking. Define a new attempt only after
   an observed transition away from the consumed gate or a contract-proven retry transition.
5. Add pure unit tests for structured, interactive, blocked, submitted, unverified, advanced, retry, and
   stale-token projections.

## 6. Phase 2 - Safe engine executors

1. Implement `VerdictInputDecider` from the current structured branch of `CockpitSession.decide()`.
2. Implement `InternalPtyDecider` using the verified contract and the active process's recorded stdin
   policy.
3. Make PTY writes complete-or-classified and serialize them with Abort.
4. Add the coordinator lock and reserve-before-write transition.
5. Treat any partial or uncertain write as consumed and unverified; never retry it.
6. Ensure ordinary Textual input has no path to either decider.
7. Add deterministic concurrency tests using barriers for double confirmation and submission-vs-Abort.

## 7. Phase 3 - Session integration and capability validation

1. Construct the coordinator when a workflow is selected and give it the effective graph, exact engine
   contract, supervisor, and monotonic clock.
2. Validate unsupported mixed, dynamic, retry, and parallel shapes before Start according to Phase 0.
3. Pass an explicit stdin policy to each start/resume spawn instead of mutating supervisor configuration.
4. Replace `decide()` and `submit_interactive()` with `submit_decision(choice, token)`.
5. Delegate gate projection and reconciliation from `snapshot()` to the coordinator.
6. Keep `CockpitSession` as the sole presentation facade, but not as the owner of transport rules or the
   decision state machine.

## 8. Phase 4 - Identical user experience

Drive all gate behavior from `snapshot.gate`, not from persisted `paused` or a transport-specific field.

1. Use one heading such as `GATE / REVIEW` for both transports.
2. Use the same option list, keyboard shortcuts, confirmation title, explanatory copy, and command rail.
3. Do not mention `verdict_input`, PTY, prompt writes, or structured resume in ordinary gate UI or help.
   Keep transport diagnostics in Engine Output or the State view when needed.
4. Show declared options while blocked, submitted, or unverified, but disable selection.
5. Refresh Feature Files initially and periodically whenever a gate snapshot is active, including a live
   interactive gate.
6. Enable `$EDITOR` while awaiting either gate type. A live process blocked on its private PTY prompt is
   a gate wait, not an automated editing step; ordinary terminal input still never reaches that PTY.
7. Present both raw engine states through one derived `awaiting decision` visual state in the header and
   Runway while retaining raw persisted status in State.
8. After PTY submission, acknowledge once and continue rendering authoritative persisted state. On
   unverified submission, keep review and Engine Output available and offer only confirmed Abort.

Delete UI state and branches that expose transport, including `_pending_transport`, interactive-only
workers, `GateDecision.mode == "interactive"`, and transport-specific confirmation copy.

## 9. Phase 5 - Verification

### Unit tests

- Exact version matching rejects unverified version variants.
- Readiness requires `running`, a non-verdict gate, live ownership, PTY stdin, and complete state.
- Structured gates always choose structured resume.
- Opaque stale tokens are rejected before any lifecycle write.
- Concurrent submissions produce exactly one PTY write.
- Submission racing Abort has one deterministic winner; input is never written after Abort ownership.
- Complete, zero-byte, partial, and failed writes produce the specified result states.
- A changed `updated_at` alone never permits resend.
- Control characters cannot enter a value-mapped payload.
- Contract-supported retry creates a new attempt only after authoritative advancement.

### Textual tests

Parameterize the same gate-surface tests over structured and interactive snapshots. Except for raw State
and Engine Output evidence, assert identical:

- heading, message, options, shortcuts, command rail, and confirmation;
- initial and periodic Feature Files refresh;
- file selection, filtering, full-file view, and editor eligibility;
- cancelled and confirmed decisions;
- submitted and unverified acknowledgement;
- disabled resend and Abort-only recovery.

Do not preload review data in the interactive fixture; assert that the screen requests it.

### Contract and PTY tests

- Success with one mapped input and persisted advancement.
- Delayed advancement while submission remains non-resendable.
- No advancement becoming unverified.
- Abort-only recovery after unverified or uncertain submission.
- Ordinary key input never reaches the PTY.
- Concurrent confirmation and Abort races.
- Retry/skip/abort outcomes supported by the recorded contract.
- Mixed and fan-out workflows either work end-to-end or are rejected before Start, matching Phase 0.
- Real-engine tests assert persisted state rather than prompt text.

Run:

```text
ruff check .
python -m unittest discover -s tests/unit
python -m unittest discover -s tests/textual
python -m unittest discover -s tests/contract
python -m unittest discover -s tests/pty
```

Run the opt-in real-engine suite for every version admitted by the interactive contract.

## 10. Acceptance mapping

| S04 requirement | Planned enforcement |
|---|---|
| Ready prompt maps confirmed choice to PTY | Exact contract plus `InternalPtyDecider` |
| Ordinary input never reaches PTY | Single coordinator submission seam and PTY tests |
| Choice written at most once | Reserve-before-write ledger, coordinator lock, Abort serialization |
| Acknowledge write; persisted state authoritative | Unified submitted/unverified gate states |
| No resend; Abort-only recovery | Consumed attempt retained until authoritative advancement |
| Engine Output remains available | Unified gate surface retains output modes |
| Structured transport preferred | Coordinator selects `VerdictInputDecider` first per current gate |
| Same end-user experience | One snapshot, one submit API, parameterized UI parity tests |

## 11. Completion criteria

The remediation is complete when:

- no presentation code references interactive transport or a pause key;
- `CockpitSession` delegates gate decisions and contains no PTY mapping or write-once ledger;
- structured and interactive gate UI parity tests share the same assertions and pass;
- every S04 PTY scenario named in the story has a real subprocess test;
- supported workflow shapes finish, retry, skip, and abort according to persisted engine state;
- unsupported shapes are rejected before Start with no engine child spawned;
- lint and all available unit, Textual, contract, PTY, and real-engine tests pass.
