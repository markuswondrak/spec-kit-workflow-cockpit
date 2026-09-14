# Epic 1 - OpenCode adapter

> As an OpenCode user, I want to use the Cockpit's workflow information from the OpenCode
> sidepanel so that I can keep the agent conversation and Spec Kit run context in one workspace,
> while the standalone Cockpit remains available as the complete workflow UI.

| Field | Value |
|---|---|
| ID | E1 |
| Status | Deferred; discovery and design only |
| Scope | Optional OpenCode integration; does not change the standalone Cockpit contract |
| Dependencies | S1-S9; stable public session/read-model boundary |

## Goal

Provide an optional OpenCode adapter for projects that use OpenCode, without making OpenCode a
runtime dependency of `workflow-cockpit` and without weakening the standalone TUI's lifecycle
guarantees.

The first adapter should be a companion integration. It exposes Cockpit context and read-only run
information to OpenCode. A later phase may add lifecycle actions if a durable backend can preserve
exclusive ownership of the engine process and run state.

## Product boundary

- `workflow-cockpit` remains installable and fully usable without OpenCode.
- The existing Textual application remains the complete workflow surface.
- The adapter uses OpenCode's documented skills, custom tools, plugin hooks, or SDK as appropriate.
- The adapter never imports Spec Kit engine internals.
- Persisted engine files remain authoritative for workflow state.
- One lifecycle owner controls a run. The TUI and adapter must not independently resume, decide, or
  abort the same run.
- The adapter does not manage arbitrary coding agents, sessions, panes, or external windows.

## Candidate integration architecture

### Phase A - Companion read model

Ship an OpenCode skill and optional custom tools that consume the Cockpit context index and expose:

- current workflow and run status;
- current branch, step, gate message, and declared gate options;
- workflow graph summary and timing information;
- Feature Files listing and safe read access to their contents;
- explicit lifecycle ownership and gate-only editing rules.

The adapter may show status in the OpenCode conversation or via tool output. It does not start,
resume, decide, or abort a run. The standalone Cockpit remains responsible for those actions.

### Phase B - Optional lifecycle bridge

Investigate an adapter that can offer `start`, `decide`, and `abort` actions through OpenCode. This
must not call `specify` independently from short-lived plugin tool invocations when doing so would
lose ownership of the PTY or process group.

The preferred design is a durable Python backend process that owns `CockpitSession` and
`EngineSupervisor`, with a narrow JSON/JSON-RPC or stdio protocol consumed by the OpenCode plugin:

```text
OpenCode plugin/custom tools
        |
        | narrow request/response protocol
        v
workflow-cockpit backend
        |
        +-- CockpitSession
        +-- EngineSupervisor
        +-- persisted run files
```

The Textual TUI and OpenCode adapter would then be two clients of the same backend boundary, but
never two concurrent lifecycle owners.

## Candidate adapter tools

The names are provisional and must be validated against OpenCode's current extension API:

- `cockpit_status`
- `cockpit_current_gate`
- `cockpit_feature_files`
- `cockpit_read_feature_file`
- `cockpit_workflow_graph`
- later: `cockpit_list_workflows`, `cockpit_start`, `cockpit_decide`, `cockpit_abort`

Read operations should be safe to call repeatedly. Lifecycle operations require an explicit run
identity, current-state verification, and protection against stale or duplicate requests.

## Acceptance criteria

### Companion integration

- Installing and running the standalone Cockpit does not require Node.js, OpenCode, or an OpenCode
  configuration.
- An OpenCode user can load the current run context through the shipped skill or adapter.
- The adapter reads authoritative live sources instead of copying mutable run state into prompts.
- The adapter reports when no current run exists, the context is stale, or the run files are
  incomplete.
- The adapter exposes gate options exactly as declared by the workflow.
- The adapter clearly states that repository edits are allowed only while the engine is paused at a
  gate.
- The adapter cannot accidentally send ordinary agent text or tool calls to the engine PTY.

### Lifecycle bridge, if implemented

- At most one backend owns a run's Engine Supervisor and process group.
- TUI and adapter attempts to claim the same run are rejected or routed to the existing owner.
- Start, decision, and abort requests are validated against the latest persisted state before any
  lifecycle write or signal.
- Structured resume and interactive PTY decisions retain the existing Cockpit semantics,
  including write-once and unverified-submission behavior.
- Abort signals only a verified live process group and never a stale PID or PGID.
- Backend disconnect, plugin reload, OpenCode exit, and terminal loss do not leave an owned engine
  process unattended beyond the existing cleanup guarantees.
- The adapter can be disabled or absent without changing standalone behavior.

## Testing expectations

- Unit tests cover context resolution, path validation, stale-run detection, tool argument
  validation, and serialization of `RunSnapshot` and gate data.
- Contract tests cover the adapter protocol independently of OpenCode.
- OpenCode integration tests cover skill discovery, custom-tool loading, read-only operations,
  permission behavior, and project/worktree resolution.
- Subprocess tests cover backend ownership, disconnects, duplicate requests, and cleanup.
- Existing standalone unit, Textual, contract, and PTY suites remain unchanged and passing.

## Open questions for refinement

- Should Phase A use only a skill, custom tools, a plugin, or a combination?
- Is conversation/tool output sufficient, or is an OpenCode TUI panel/status surface required?
- What durable backend protocol is smallest while still preserving process ownership?
- How is ownership discovered and recovered after a backend or OpenCode crash?
- Should the adapter support only the current run context or also workflow selection and launch?
- Which OpenCode versions and extension APIs are supported and tested?
- How should concurrent OpenCode sessions in one worktree be rejected?

## Explicit non-goals

- Replacing the standalone Cockpit in the first adapter phase.
- Making OpenCode a required dependency of the Python package.
- Embedding the complete Textual UI inside OpenCode.
- Adding multi-run, multi-project, or historical-run management.
- Letting the agent autonomously choose or submit workflow gate decisions.
