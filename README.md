# Workflow Cockpit

A standalone Python + Textual TUI that owns exactly one Spec Kit workflow run in one
project/worktree. It lets a user select and start a workflow, observe its execution, review
worktree changes at gates, and submit the workflow's declared decision. It uses an installed
`specify` CLI for writes and the engine's persisted run files for reads; the engine is never
modified and its internals are never imported.

See [`docs/architecture/README.md`](docs/architecture/README.md) for the architecture context,
[`docs/decisions/README.md`](docs/decisions/README.md) for the decision log, and
[`AGENTS.md`](AGENTS.md) for the repository rules and commands. The product backlog lives in
[`requirements/README.md`](requirements/README.md).

## Supported platforms and resilience

Workflow Cockpit supports Linux, macOS, and WSL. Native Windows is explicitly unsupported; run
under WSL instead. The test matrix runs the capability-gated unit, Textual, fake-engine contract,
and PTY suites on Linux and macOS. The real-`specify` contract suite skips unless a pinned
executable for the declared version range is provisioned.

Catchable `SIGINT`, `SIGHUP`, and `SIGTERM` delivered to the Cockpit process trigger a bounded
best-effort abort and cleanup of the recorded engine process group without a confirmation
prompt. There is **no cleanup guarantee** for `SIGKILL`, host loss, power loss, or interpreter
failure: Cockpit cannot run cleanup it never receives, and the engine process group may be left
running.

Run the capability-gated suite under WSL with the same command used by CI:

```bash
python -m pytest tests/unit tests/textual tests/contract tests/pty
```

## Preset: Lean Workflow Cockpit

The bundled [`presets/lean-workflow`](presets/lean-workflow) preset makes the core Spec Kit
commands safe to run unattended inside a workflow:

- `speckit.specify` is replaced so the agent names the feature itself and always creates
  `specs/<feature-name>` (writing `.specify/feature.json` for the downstream commands).
- `speckit.plan`, `speckit.tasks`, and `speckit.implement` keep their lean bodies and gain a shared
  **Workflow Runtime** preamble: never ask questions, never request permissions, make informed
  defaults, and report a blocker instead of hanging.

### Install

From the repository root, with an initialized Spec Kit project:

```bash
# priority 1 < lean's 10, so this preset's commands win over the lean originals
specify preset add --dev ./presets/lean-workflow --priority 1
```

Verify:

```bash
specify preset list
specify preset resolve speckit.specify
specify preset resolve speckit.tasks
```

Remove:

```bash
specify preset remove lean-workflow
```

Re-apply after editing the preset, since the installed `.specify/presets/<id>/` and
`.opencode/commands/` copies are generated scaffolding:

```bash
specify preset remove lean-workflow
specify preset add --dev ./presets/lean-workflow --priority 1
```

## License

MIT
