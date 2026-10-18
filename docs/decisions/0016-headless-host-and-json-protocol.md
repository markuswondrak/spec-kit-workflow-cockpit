# 0016. A headless host owns one run over a line-delimited JSON socket

- Status: Accepted
- Supersedes: -

## Context

Cockpit's lifecycle core (session, supervisor, gate coordinator, adoption, resume) was reachable
only through the Textual app. Any other frontend — an editor plugin, a script, a future web view —
would have had to re-implement start/adopt/decide/abort/resume against the persisted run files, or
drive the TUI. Both duplicate the lifecycle rules the engine boundary and ADR-0004/0006/0010/0013/
0014 exist to centralise.

The engine's own transport is opaque to Cockpit (ADR-0004), and a frontend must not need to know
whether a gate is answered by a structured resume or one PTY write. The read side already has a
scriptable surface (`workflow-cockpit context --json`, see ADR-0017); the lifecycle side needed one
too.

## Decision

`workflow-cockpit serve` starts a detached host process that owns exactly one run through the
existing `CockpitSession` and `EngineSupervisor`. It adds no lifecycle logic of its own.

- **Transport.** A Unix domain socket at `<worktree>/.workflow-cockpit.sock`, gitignored, one UTF-8
  JSON object per `\n`-terminated line in both directions, maximum line 1 MiB (over-size is a
  `bad_request` and the connection stays open). The socket lives at the worktree root because that
  is the one path every surface already knows and it needs no registry.
- **Messages.** A request carries `id` and `op`; a response echoes `id` verbatim and carries
  `ok` plus either `result` or a structured `error` object (`code`, `message`, `action`,
  `details`). Every message carries `protocol_version` (starts at 1). Events (`gate_open`,
  `status_changed`, `terminal`) carry no `id`, a `seq`, and are delivered to every connected client
  in order.
- **Operations.** `list`, `validate`, `start`, `status`, `gate`, `decide`, `abort`, `adopt`,
  `resume`. `start` refuses when the current-run pointer names a non-terminal run, naming the run
  and the adopt/abort alternatives, through the same `StartGuard` the TUI uses. `decide` accepts
  only an option the workflow declares and only with the gate's current token; mutating operations
  serialise on one asyncio lock, so a second decide sees the consumed ledger and is refused.
- **Ownership.** The host holds the existing durable claim (ADR-0013) and introduces no new owner
  record, registry, or heartbeat. A controller is identified by that claim, not by a connection:
  clients are stateless, a reconnecting frontend is the same controller, and events fan out to all
  of them.
- **Lifetime.** Run-scoped, evaluated on every event:
  `starting -> serving(run: none|running|paused|terminal) -> releasing -> exited`. The host exits
  when the run is terminal, or paused at a gate with zero connected clients past a 2 s grace window
  (so a frontend reload is not raced); it never exits while a step runs. On release it frees the
  claim and, if a verified live process group still exists, runs the same bounded best-effort abort
  the TUI runs (ADR-0006), so no engine process is ever abandoned.
- **Bind uniqueness.** The host probes the socket before binding: a live host answers and the second
  start is refused with `host_already_running`; `ECONNREFUSED`/`ENOENT` means a crashed remnant and
  is unlinked; a path longer than the AF_UNIX limit is refused with `socket_path_too_long` rather
  than silently relocated. The kernel's single bind remains the final guarantee.
- **Process model.** `serve` detaches with `subprocess.Popen(..., start_new_session=True)` (no
  double fork), stdio to `/dev/null` or the opt-in diagnostics log. The parent waits for the socket
  to answer `status`, prints that result, and exits. Blocking session work runs in worker threads,
  so the event loop that reads sockets and evaluates lifetime never stalls.
- **Portability.** `serve` is POSIX-only (Unix sockets and process groups). `context` and `install`
  stay portable; native Windows remains out of scope.

## Consequences

- A frontend implementer can build a complete adapter — read, render, and lifecycle control — from
  the read command, the installer contract, and this protocol, with no lifecycle logic of its own
  and no references to UI internals (SC-008).
- The host and the TUI cannot disagree about a decision or an abort: both call the same session,
  coordinator, adopter, and supervisor.
- `CockpitSession` gains only a read-only `owner_id` property, so the host can report the claim
  state of the run it owns. `CockpitSession` is reused, not extended.
- Host lifetime and the read envelope share one failure mode to watch: a paused run with a live
  interactive process is aborted on release, because exiting while owning a live group would
  abandon it. The run then ends `aborted` rather than staying adoptable; that is the safe trade.
- The socket is a new on-disk artifact at the worktree root; the installer-independent `serve`
  precheck appends it to `.gitignore` when absent, non-fatally.

## Rejected alternatives

- **A new daemon or systemd unit.** A new dependency and a second lifetime authority; the existing
  supervisor must stay the process-group parent (ADR-0006).
- **Double-fork detach.** `start_new_session=True` already detaches from the controlling terminal
  and starts a new session; the extra fork adds a failure mode without benefit.
- **HTTP, gRPC, or a named pipe.** HTTP adds framing and dependency weight to a single-user local
  socket; a named pipe is not a Unix socket and cannot use bind uniqueness.
- **A new owner registry, heartbeat, or PID file.** ADR-0013's claim already carries owner identity
  and liveness evidence; a second authority drifts.
- **Connection-scoped lifetime (exit when the last client disconnects).** It would kill a run
  mid-step and break the reload case; lifetime is run-scoped.
- **Re-implementing start/decide/abort in the host.** It duplicates the write-once ledger, the
  token rules, and the verified-live-group signalling rule.
- **Relocating an over-long socket path.** It introduces a second socket location contract for a
  case a shorter worktree path already solves.
