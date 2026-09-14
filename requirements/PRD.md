# PRD: Spec Kit Workflow Cockpit

| Field | Value |
|---|---|
| Status | Clarified |
| Date | 2026-09-12 |
| Product | Standalone `workflow-cockpit` Python package and CLI |
| Scope | Product requirements; implementation detail lives in `TUI_DESIGN.md` |

## 1. Product promise

Workflow Cockpit gives an existing Spec Kit workflow user one local workspace in which to
choose and start a workflow, observe its execution, review worktree changes at gates, and
submit the workflow's declared decision.

The first release is valuable only when this complete single-run loop works. It is not merely
a status dashboard.

## 2. Product boundary

- The Cockpit is a standalone product, not a `specify` subcommand and not part of the Spec
  Kit repository.
- It uses an installed `specify` CLI and an already initialized local Spec Kit project.
- The workflow engine remains unchanged. Writes use existing CLI commands; reads use the
  engine's persisted run files.
- One Cockpit session owns exactly one run in one project/worktree.
- The Cockpit shows only its current run. It does not aggregate external runs or provide its
  own history database.
- Run history remains in `.specify/workflows/runs/` and can be inspected with Spec Kit tools.
- The target user already understands Spec Kit workflows. New-user onboarding is not an MVP
  goal.

## 3. Goals

- Complete start -> observe -> gate -> review -> adjust -> decide within one terminal
  workspace.
- Show the workflow graph and runtime state with near-instant updates.
- Show readable live workflow output without requiring a second terminal.
- Support every installed workflow, including gates with and without `verdict_input`.
- Preserve workflow-defined gate choices and semantics.
- Keep the active branch, start commit, run status, and current step unambiguous.
- Provide a dedicated Cockpit skill that a user can invoke in an agent of their choice to load
  the current run context.
- Keep agent selection, process management, panes, conversations, and edits outside Cockpit.

## 4. Non-goals

- Workflow authoring, installation, removal, enablement, or catalog management.
- Multiple projects, multiple worktrees, multiple runs, or historical-run navigation in one
  Cockpit session.
- Multi-user use or shared Cockpit sessions.
- A hosted service, CI/CD dashboard, or full IDE.
- Launching, embedding, selecting, locking, or terminating coding agents.
- Native Windows support; Windows users use WSL.
- Changes to the Spec Kit workflow engine.
- External notifications, localization, or Cockpit-owned run persistence.

## 5. Supported environment

- Linux, macOS, and WSL.
- English-only UI.
- Git, an installed compatible `specify`, and a Spec Kit initialized project are required.
- The implementation stack is Python with Textual.
- The Cockpit declares a tested `specify` version range (initial minimum: `>=1.0`). It refuses
  to launch outside that range and explains how to install a compatible version.
- Preflight validates the project, `specify`, and Git state before starting the application.
  Missing prerequisites produce actionable errors; the Cockpit does not install them.
- Below the minimum usable terminal size, the UI blocks with a resize message.

## 6. Core journey

### 6.1 Launch and select

1. The user runs `workflow-cockpit` in or below a Spec Kit project. The CLI discovers the
   nearest project root; an explicit project path may also be supplied.
2. Preflight verifies the environment and compatibility.
3. The Cockpit lists all workflows installed in that project.
4. The Cockpit shows a workflow summary, its step list, active branch/worktree, and a
   schema-driven form for declared inputs.
5. Required inputs are validated. Sensitive-looking inputs receive no special treatment and
   are subject to the engine's normal persistence behavior.
6. One explicit Start action begins the run. A dirty worktree triggers a warning but does not
   block Start.

### 6.2 Execute and observe

1. At Start, the Cockpit resolves the feature directory declared in `.specify/feature.json` as
   the file review root.
2. One Engine Supervisor starts the workflow in an internally managed PTY and streams readable
   output into a read-only Textual log component.
3. The Cockpit shows overall status, active branch, workflow graph, current path, node status
   and attempt count, total elapsed time, and per-step elapsed time.
4. The UI follows branch changes automatically.
5. The Cockpit polls the current run state frequently enough that updates appear within 500 ms.
6. While automated steps run, Engine Output is the primary workspace. The review surface appears
   as the primary workspace only when the engine pauses at a gate, and the outcome summary only
   after termination.

### 6.3 Review and adjust at a gate

1. At Start, Cockpit writes a stable context file in the run metadata directory. It points to
   authoritative run status, inputs, logs, workflow definition, and relevant paths.
2. Cockpit ships a dedicated skill that users can invoke from an agent of their choice with
   the displayed context-file path. Cockpit does not launch or manage that agent.
3. The context and skill state that Cockpit alone controls the run, current engine status must
   be checked before acting, and repository edits should only be made while paused at a gate.
4. The Cockpit presents Feature Files: every file under the declared feature directory,
   including files that existed before Start.
5. Files are listed by project-relative path. Nothing under the feature directory is excluded
   and no change-source attribution is attempted.
6. Text files show their current content. Binary files show metadata only. Large text files show
   a bounded preview with an explicit full-open action.
7. Files refresh automatically while paused. The user may open an existing selected file in
   `$EDITOR` by suspending Textual and restoring it when the editor exits. Editor actions are
   disabled while automated steps run and for binary files.
8. A feature directory with no files shows a clear empty state and the gate remains decidable.

### 6.4 Decide

1. The Cockpit displays exactly the gate options declared by the workflow.
2. Every choice requires confirmation. Viewing every changed file is encouraged but not
   required.
3. Workflow-defined semantics, including retry or skip behavior, are preserved.
4. Gates with `verdict_input` use the engine's structured resume command.
5. Other gates are answered by writing the selected option to the internally managed engine
   PTY and then
   following persisted engine state.
6. A PTY submission is sent at most once. If state does not advance, the Cockpit continues to
   show the authoritative paused state and offers only Abort.
7. Abort is always a separate Cockpit lifecycle action and requires confirmation. The engine
   exposes no abort command; Cockpit sends SIGINT (interrupt) to the recorded engine process
   group, waits a bounded grace period, then terminates only that group with TERM/KILL if
   needed. The engine persists the run as interrupted/paused, so Cockpit records the aborted
   outcome itself and never resumes that run in the same session.

### 6.5 Finish

- Success: show the final result, graph, timings, and Feature Files summary, then close
  after user acknowledgment.
- Failure: show the failed node and cause and keep Engine Output visible until acknowledgment.
  The failed run cannot restart or resume in that session; another attempt requires a new
  session.
- Abort: show the aborted result and await acknowledgment.
- Explicitly exiting the application while a run is active follows the confirmed Abort path.
- On terminal loss or process termination, Cockpit makes a best-effort attempt to abort and
  clean up its engine process.
- No badge, terminal bell, OS notification, email, or chat notification is required.

## 7. Functional requirements

### FR-1 - Launch and run ownership

- Discover the project root and all installed workflows.
- Present workflow summary, step list, and schema-driven validated inputs.
- Start exactly one run and control it exclusively through existing engine CLI commands.
- Show and manage only that run.

### FR-2 - Workspace and observability

- Render workflow state, review content, and engine output in one Textual application.
- Present one state-driven workspace: Engine Output is primary while automated steps run, the
  review surface is primary at a gate, and neither reserves empty space when inactive.
- Stream normalized, bounded engine output into a read-only log component and keep direct
  engine input inaccessible to the user.
- Render the workflow definition as a graph with active path, runtime node status, and attempt
  count.
- Show run and step timings, errors, and current branch.
- Poll the current run asynchronously at an interval of at most 500 ms.

### FR-3 - Gate review

- Detect gates and display their message and exact declared options.
- Show the declared feature directory's files before a decision.
- Refresh review content live and support an optional `$EDITOR` fallback.

### FR-4 - Cockpit skill and context

- Write a stable context index for the current run under its engine metadata directory.
- Ship a dedicated Cockpit skill that can be invoked in a user-chosen external coding agent.
- Let the skill accept the displayed context-index path and direct the agent to authoritative
  live sources rather than copying changing state.
- State the lifecycle ownership and safe-editing rules in both the context index and skill.
- Display the context-file path and skill invocation help without launching an agent.

### FR-5 - Decisions and abort

- Confirm and submit every declared gate option without changing workflow semantics.
- Prefer `verdict_input`; use automated PTY input otherwise.
- Never send the same unverified PTY decision twice.
- Provide a separately confirmed Abort action.
- Reject mixed, dynamic, loop/fan-out, and interactive-retry gate shapes before Start when the
  verified engine contract cannot prove deterministic prompt ownership.

### FR-6 - Lifecycle

- Confirm Abort when the user exits during an active run.
- Attempt Abort and cleanup of the recorded engine process group on catchable termination
  signals. Abrupt host loss and `SIGKILL` carry no cleanup guarantee.
- Handle success, failure, and abort according to section 6.5.
- Persist no Cockpit history outside engine run metadata.

### FR-7 - Agent-matched styling templates

- Ship selectable styling templates, including a neutral default and one per supported coding
  agent integration (for example `opencode`).
- Select the active template from the project's default integration, with an explicit override.
- Fall back to the default template when the integration or template is unknown or malformed,
  without failing the run.
- Keep layout, wording, controls, and behavior identical across templates; templates change
  only visual tokens.
- Keep text and focus states legible under every shipped template.

## 8. Quality requirements

- The UI remains responsive during process execution, polling, diffing, and large-file
  review.
- Partially written or missing engine state files and process crashes do not crash the UI.
- All controls are keyboard accessible and help is available in-app.
- Automated coverage includes unit tests, Textual `App.run_test()` interaction tests, and
  subprocess/PTY integration tests.
- Demo fixtures cover linear success, `verdict_input`, interactive PTY gates, branch creation,
  retry/skip, no-change gates, no-gate runs, failure, and abort.

## 9. Success criteria

- An existing Spec Kit user completes the full single-run loop without another terminal.
- The user can always identify the active branch, current workflow node, engine status, and
  available gate action.
- Every installed compatible workflow can be started, and every declared gate can be
  submitted through the Cockpit.
- The user can inspect Feature Files at gates and use the optional Cockpit skill in an
  independently started agent.
- Normal exit and supported termination signals do not leave a Cockpit-owned workflow process
  running unattended.

## 10. Remaining validation items

- Choose and document one minimum terminal size through a Textual layout prototype.
- Validate PTY prompt automation against every `specify` version in the supported range.
- Verify whether structured gate pauses keep the original engine process alive or require a
  new supervised `resume` process.
- Confirm the registry and workflow-definition formats needed for schema-driven inputs and a
  complete control-flow graph.
