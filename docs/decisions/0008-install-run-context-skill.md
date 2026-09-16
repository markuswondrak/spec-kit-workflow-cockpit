# 0008. The run-context skill installs into the project integration at startup

- Status: Accepted
- Supersedes: -

## Context

Cockpit ships the `cockpit-run-context` skill so a user-chosen external agent can read the current
run context. An agent only discovers a skill from its own standard skills directory, so the shipped
file is useless until it is copied there. Asking every user to copy it manually leaves the skill
missing in most projects.

## Decision

At TUI start (not during `--check`), `SkillInstaller` copies the packaged `SKILL.md` into the
project-local skills directory of the integration declared in `.specify/integration.json`:
`.claude/skills`, `.github/skills`, or `.opencode/skills`; any other or undeclared integration uses
the open-standard `.agents/skills`. The destination is outside `.specify/` and is not run state. An
existing skill directory is left untouched. The write is atomic and a failure is reported, never
fatal.

## Consequences

- The skill is present for the project's agent without a manual copy step.
- The new file is an ordinary worktree change, so a previously clean worktree can become dirty and
  Start may ask for confirmation. Users commit or ignore it as they choose.
- A user edit is never overwritten, because an existing skill directory is skipped; a changed
  bundled skill is picked up only in a project that has not installed it yet.

## Rejected alternatives

- **README instructions only:** the skill stays missing unless the user acts.
- **Overwrite on every start:** would silently discard local skill edits.
- **Install into `.specify/`:** mixes agent configuration with engine run files.
- **Install into the home directory:** leaks project state into global user configuration.
