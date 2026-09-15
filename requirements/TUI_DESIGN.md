# Design: Workflow Cockpit TUI

| Field | Value |
|---|---|
| Status | Clarified direction |
| Stack | Python and Textual |
| Executable | `workflow-cockpit` |
| Engine boundary | Existing `specify` CLI for writes; persisted files for reads |

The visual system, screen composition, and keyboard behavior are specified in
`UI_DESIGN.md`.

## 1. Process model

One Cockpit invocation is one Textual process that owns one workflow run in one project and
worktree. Cockpit is the sole workflow-lifecycle writer.

```text
terminal
└─ workflow-cockpit (Textual)
   ├─ workflow graph and status
   ├─ gate and Feature Files review
   ├─ read-only Engine Output (`RichLog`)
   └─ managed `specify` child process in an internal PTY
```

There are no external engine or agent surfaces. Users may start any coding agent separately and
invoke the dedicated Cockpit skill there.

## 2. Launch flow

1. Discover the nearest Spec Kit project root from the current directory, unless an explicit
   path was supplied.
2. Verify Linux/macOS/WSL, terminal dimensions, Git, project initialization, and the installed
   `specify` version.
3. Refuse unsupported `specify` versions or missing prerequisites with exact guidance.
4. Read all installed workflows from the project registry and let the user choose one.
5. Show workflow summary, declared steps, current branch/worktree, and schema-driven inputs.
6. Validate required fields. Treat secret-looking inputs like ordinary engine inputs.
7. Warn, but allow, when the worktree is dirty.
8. Resolve the declared feature directory as the file review root and issue one explicit Start.
9. After the run ID exists, write its stable context index and display its path plus Cockpit
   skill usage help.

## 3. Engine Supervisor and output

One `EngineSupervisor` owns engine execution. It records the active child PID and process group,
allows at most one engine execution process at a time, and attaches every output-producing
engine command to an internal PTY. The PTY supports interactive gates but is not a user-visible
terminal.

- Initial `run` executes under the PTY.
- If a gate keeps that process alive, an interactive decision writes once to that PTY.
- If a paused command exits, structured `resume` starts as the next supervised PTY process and
  appends to the same Engine Output view.
- Persisted engine state determines whether a process may be started or addressed.
- Abort sends SIGINT to the recorded engine process group (the engine's only stop mechanism),
  waits for a bounded grace period, then sends TERM/KILL only to that group if necessary.

- Read PTY output incrementally without blocking the Textual message loop.
- Decode with replacement, normalize carriage returns, and retain complete lines plus the
  current partial line.
- Render output in a bounded, read-only `RichLog` with auto-scroll enabled by default.
- Treat Engine Output as a Focus mode, not a fixed region: it owns the canvas while automated
  steps run and collapses to a diagnostic tail whenever a gate review or outcome is primary.
- Strip ANSI and terminal control sequences instead of emulating a terminal.
- Let the user pause auto-scroll, scroll the retained tail, and jump back to live output.
- Never route ordinary user keystrokes to the PTY.
- Retain a configurable bounded tail. `log.jsonl` remains the complete source.
- Capture exit status and distinguish normal completion, engine failure, Cockpit abort, and
  unexpected process death.

Persisted engine files remain authoritative for workflow state. PTY output is evidence and
diagnostic content, not a second state model.

## 4. Data boundaries

### Reads

- Run status and graph state: `.specify/workflows/runs/<run_id>/state.json`.
- Inputs: `.specify/workflows/runs/<run_id>/inputs.json`.
- Event data and timing: `.specify/workflows/runs/<run_id>/log.jsonl`.
- Workflow catalog: `.specify/workflows/workflow-registry.json`.
- Workflow definition: resolved installed workflow file.
- Branch: Git state in the current worktree.
- Review content: files under the declared feature directory.
- Human-readable output: internal workflow PTY.

A single asynchronous polling loop reads the current run at most every 500 ms and publishes
immutable snapshots to the Textual message loop. It skips unchanged files and tolerates missing
or partially written state.

### Writes

- Start and structured resume invoke the installed `specify` CLI. Abort signals the recorded
  engine process group (SIGINT) instead of invoking a CLI command.
- Unstructured gate choices are written once to the managed engine PTY.
- No engine internals are imported and no engine files are mutated directly.
- `$EDITOR` is available for repository edits only while the engine is paused at a gate.
- External agents are outside Cockpit's process and write controls. The Cockpit skill instructs
  them to edit only while the engine is paused at a gate.

## 5. Textual application structure

The application keeps these elements available through one adaptive layout:

- workflow/run identity, state, branch, and elapsed time;
- declared workflow graph with active path and attempt information;
- current step or gate;
- Feature Files review;
- read-only Engine Output;
- context-index path and current valid actions.

At wide sizes the graph and Focus area are side by side. Focus is a single state-driven canvas:
Engine Output is the default mode while automated steps run, the review surface is the default
mode when the engine pauses at a gate, and the outcome summary is the default mode after
termination. Engine Output collapses to a short diagnostic tail whenever a gate review or
outcome is primary, and expands on demand. No mode reserves space for a pane with no content, and
mode transitions preserve output scroll and the selected review file. At narrower supported
sizes the graph stacks above Focus. Below the validated minimum, Textual shows a blocking resize
screen.

## 6. Workflow graph

The graph represents declared control flow, not merely a linear history. It includes all known
nodes and edges and overlays runtime information:

- pending, running, paused, completed, failed, skipped, and aborted state;
- highlighted active path and node;
- attempt count for loops and retries;
- completed duration or live elapsed duration.

The graph parser is derived from the installed workflow definition and does not hardcode a
particular workflow.

## 7. Feature Files and editor

At Start, resolve the feature directory declared in `.specify/feature.json`. At every gate and
final summary, list every file under that directory. The feature directory is the product of the
workflow, so no Git comparison or change attribution is attempted.

This is called **Feature Files**, not run artifacts: the whole directory is listed, including
files that existed before Start.

- Include every file under the feature directory, recursively.
- List project-relative paths, sorted, so the set is stable across refreshes.
- Make no change-source attribution and compute no diff.
- For text: show the current file content.
- For binary: show path and size only.
- For large text: provide a bounded preview and explicit full-open action.
- Refresh automatically while paused while preserving selection and scroll when practical.
- Show a clear empty state when the feature directory has no files or is not declared.
- Present review as a Focus mode that is primary while the engine is paused at a gate; it is not
  allocated space during automated steps.

To open `$EDITOR`, Textual suspends its terminal control, opens the selected existing feature
file, and restores/redraws the application when the editor exits. The action is available only
at a gate, for existing non-binary files, and when `$EDITOR` is set. Cockpit restores the
selected path; exact editor scroll state is editor-owned.

## 8. Cockpit skill and context index

After Start returns a run ID, create a stable Markdown context index at
`.specify/workflows/runs/current_run`. It points to the workflow definition, `state.json`,
`inputs.json`, `log.jsonl`, relevant CLI status command, worktree, current branch source, and
the declared feature directory. The file is an index, not a copied live snapshot.

Ship a dedicated Cockpit skill for a coding agent chosen and started by the user. The skill:

- accepts the context-index path displayed by Cockpit;
- reads authoritative live sources through the paths and commands in that index;
- explains the workflow, current state, gate, and Feature Files when asked;
- states that Cockpit alone starts, resumes, decides, and aborts the run;
- never invokes workflow lifecycle commands; and
- checks that the engine is paused at a gate before editing repository files.

Cockpit does not discover agent integrations, launch agents, send prompts, manage external
windows, lock external tools, or terminate agent processes.

## 9. Gate decisions

Render exactly the workflow's declared choices. Do not synthesize universal Approve/Reject
semantics. Every selection opens a confirmation showing the choice and known workflow effect.
The user need not open every changed file first.

Decision strategies:

1. `VerdictInputDecider`: if `verdict_input` exists, invoke structured `resume -i
   <name>=<choice> --json`.
2. `InternalPtyDecider`: otherwise, map the selected declared choice to prompt input and write
   it once to the managed PTY.

After either strategy, persisted engine files remain authoritative. For PTY input, acknowledge
that input was sent but continue to render `paused` until state advances. Never resend an
unverified choice. If it remains paused, only confirmed Abort is available.

Workflow behavior such as reject -> retry or reject -> skip is preserved.

## 10. Abort and shutdown

- Abort is always available during an active or paused run and requires confirmation.
- Send SIGINT to the recorded engine process group (the engine exposes no abort command),
  follow persisted state, then terminate that group and present an aborted summary. The engine
  persists the run as interrupted/paused, so Cockpit owns the aborted outcome and does not
  resume it in the same session.
- `q` and normal interactive close enter the same confirmation while the run is active.
- On catchable `SIGINT`, `SIGHUP`, or `SIGTERM`, attempt engine abort and bounded cleanup of the
  recorded engine process group without waiting for confirmation.
- `SIGKILL`, host loss, power loss, and interpreter failure have no cleanup guarantee.

## 11. Outcomes

### Success

Show the outcome summary as the default Focus mode with final status, graph, total and step
timings, and the Feature Files set. Engine Output stays available as a collapsed diagnostic tail.
Exit the application after acknowledgment.

### Failure

Show the failed graph node and structured cause as the default Focus mode, with Engine Output as
a collapsed diagnostic tail. Acknowledgment exits the application; retry requires a new
invocation. Independently running agents remain outside the Cockpit lifecycle.

### Abort

Show the aborted state and await acknowledgment before exiting.

No special notifications are emitted for gates or completion.

## 12. Packaging and tests

- Package as a standalone Python distribution exposing `workflow-cockpit`.
- Use Textual's testing harness for user interactions.
- Unit-test parsing, graph projection, feature-file listing, compatibility checks, Engine
  Supervisor transitions, output normalization, and decision strategy selection.
- Run subprocess/PTY integration tests against fixture workflows for success, both gate paths,
  branch creation, retry/skip, no-change, no-gate, failure, abort, and termination signals.

## 13. Open validation

- Choose one minimum terminal size through a Textual prototype.
- Define and test supported `specify` versions.
- Spike PTY prompt matching and choice mapping across the supported range before implementing
  the fallback decider.
- Verify whether structured gate pauses retain the original process or require a new supervised
  `resume` process.
