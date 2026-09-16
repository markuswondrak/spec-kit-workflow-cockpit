# workflow_ui/prototype/AGENTS.md

Nested context for the visual prototype. Root [`AGENTS.md`](../../AGENTS.md) rules still apply;
this file adds only prototype-specific boundaries.

- **Visual-only.** This tree is a mock with mock data. It is not shipped, not imported by
  `workflow_cockpit`, and excluded from `ruff` and the wheel.
- **Never move behavior here.** Prototype navigation is disposable; do not let it leak into the
  production lifecycle.
- **Keep the palette aligned.** Token roles and values must match
  [§8 Crosscutting Concepts](../../docs/architecture/08-crosscutting-concepts.md) and the styling
  templates; a prototype-only color is a bug.
- **No engine, session, or run-file access.** The prototype must not read `.specify/`, spawn
  processes, or handle signals.
