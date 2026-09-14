# Lean Workflow Cockpit

A preset for running the core commands unattended inside a workflow:

- `speckit.specify` is **replaced**: the agent chooses the feature name from the workflow input
  instead of asking the user, and every feature lives under `specs/` (`specs/<feature-name>`). The
  resolved path is written to `.specify/feature.json` so `speckit.plan`, `speckit.tasks`, and
  `speckit.implement` can find it.
- `speckit.plan`, `speckit.tasks`, and `speckit.implement` keep their lean content. A shared
  **Workflow Runtime** preamble (`commands/workflow-runtime.md`) is prepended to each, telling the
  agent it runs unattended: never ask questions, never request permissions, make informed
  defaults, and report a blocker instead of hanging.

`speckit.constitution` and every non-core command are untouched.

## Why this preset exists

The bundled **lean** `speckit.specify` is interactive. Its first step is:

> **Ask the user** for the feature directory path … Do not proceed until provided.

In the automated `lean-flow` workflow there is no user to answer, so the specify step finished
without creating `specs/` or `.specify/feature.json`, and every downstream command stalled. The
cockpit runs the engine non-interactively, so this had to be fixed at the command level.

The same non-interactivity means an agent can stall by asking a question or waiting for an
approval. The Workflow Runtime preamble makes that runtime explicit in the prompt. Command
composition (`strategy: prepend` from one shared file) applies it to every step without copying
the lean bodies.

Upstream, editing a bundled preset in place is **against Spec Kit's preset semantics** — the
installed `.specify/presets/lean/` and `.opencode/commands/` copies are generated scaffolding
(gitignored) and are overwritten by `specify init`. A dedicated preset that overrides only the
commands it needs is the idiomatic mechanism, so that is what this directory is.

## Install

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

## License

MIT
