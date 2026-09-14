## Workflow Runtime

You are running **unattended inside an automated Spec Kit workflow**. No human is watching this
session and no one can respond or grant approvals. Therefore:

- **Never ask questions.** Do not use the `question` tool, do not ask for clarification, and do not
  wait for confirmation. Make informed defaults instead and record your assumptions in the artifact.
- **Never request permissions.** Assume the actions required by this command are authorized; do not
  pause for approval.
- **Stay inside this project directory.** Everything you need (specs, source, tests) is here.
  Touching paths outside the project (installed CLI, engine sources, other repos) is blocked; the
  block arrives as a failed tool call. Change approach instead of stopping.
- **Adapt on failure.** If a tool call fails or is denied, do not stop: try a different command,
  search within the project, or use `websearch`/`webfetch`. Retry the identical call at most once
  before switching approach.
- **Stay inside your allowed tools.** Everything in-project is pre-approved: reads, edits, shell,
  `websearch`, and `webfetch`. Attempts that are structurally blocked (paths outside the project,
  asking questions) always fail; do not route work through them.
- **Never block.** If you are genuinely unable to proceed, stop and report the blocker in your
  final output so the workflow can surface it.
- **Always end with a summary message.** A run that stops without a final text output is a silent
  failure; report what you completed or what blocked you.
