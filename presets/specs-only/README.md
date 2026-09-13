# Specs-Only Specify

A single-command preset that overrides `speckit.specify` so it works headlessly:

- The **agent chooses the feature name** from the workflow input instead of asking the user.
- **Every feature lives under `specs/`** (`specs/<feature-name>`); the resolved path is written to
  `.specify/feature.json` so `speckit.plan`, `speckit.tasks`, and `speckit.implement` can find it.

Nothing else is overridden. `plan`, `tasks`, `implement`, and `constitution` stay on the lean
preset (or the core pack), because this preset is installed with a lower priority number and is
only consulted for `speckit.specify`.

## Why this preset exists

The bundled **lean** `speckit.specify` is interactive. Its first step is:

> **Ask the user** for the feature directory path … Do not proceed until provided.

In the automated `lean-flow` workflow there is no user to answer, so the specify step finished
without creating `specs/` or `.specify/feature.json`, and every downstream command stalled. The
cockpit runs the engine non-interactively, so this had to be fixed at the command level.

Upstream, editing a bundled preset in place is **against Spec Kit's preset semantics** — the
installed `.specify/presets/lean/` and `.opencode/commands/` copies are generated scaffolding
(gitignored) and are overwritten by `specify init`. A dedicated preset that overrides only the one
command is the idiomatic mechanism, so that is what this directory is.

## Install

```bash
# priority 1 < lean's 10, so this preset wins only for speckit.specify
specify preset add --dev ./presets/specs-only --priority 1
```

Verify:

```bash
specify preset list
specify preset resolve speckit.specify
```

Remove:

```bash
specify preset remove specs-only
```

## License

MIT
