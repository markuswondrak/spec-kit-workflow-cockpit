---
name: cockpit-run-context
description: >-
  Load and explain the current Workflow Cockpit run context. Use when the user
  provides the Cockpit context-index path, or asks about the current Spec Kit
  workflow run, its status, gate, or Feature Files.
---

# Cockpit run context

Load the authoritative context for the current Workflow Cockpit run so you can
explain it to the user. You inspect; Cockpit controls.

## Input

The user gives you the context-index path displayed by Cockpit. The default and
stable path is:

```
.specify/workflows/runs/current_run
```

Accept an explicit path if the user supplies one. Read that file first. It is an
index, not run state: it lists the authoritative sources to read.

## Read the authoritative sources

Read the sources named in the index with read-only tools:

- `state.json` for the authoritative run status, current step, and errors.
- `inputs.json` for the inputs the run started with.
- `log.jsonl` for the complete event log (`tail` it; do not load it all).
- the workflow definition for declared steps, gates, and options.
- Git in the worktree for the current branch and commit.
- the declared feature directory for Feature Files.

If a source is missing or partially written, say so. Never infer workflow state
from an index or from logs when `state.json` is readable; it is authoritative.

## Explain

When asked, explain:

- the workflow and its declared steps;
- the current status and step;
- the current gate, its message, and its exact declared options;
- the Feature Files set and, on request, individual file contents.

Report options exactly as the workflow declares them. Do not synthesize
approve/reject semantics the workflow does not declare.

## Lifecycle ownership

Workflow Cockpit alone starts, resumes, decides, and aborts a run.

- Never invoke `specify workflow run`, `specify workflow resume`, or any gate
  decision or abort command. You are read-only with respect to the lifecycle.
- Do not attempt to send input to the engine or to any Cockpit process.
- If the user wants a decision or an abort, tell them to use the running Cockpit.

## Editing rules

Before you edit any repository file, read `state.json` and confirm the engine is
paused at a gate:

- `status` is `"paused"` (a structured gate), or
- `status` is `"running"` and `current_step_id` names a declared gate step
  (a live interactive prompt).

If the run is initializing, running an automated step, or terminal, do not edit
on the run's behalf. Tell the user the engine is not waiting at a gate.
