# 0017. One installer with artifact policies, version markers, and a read envelope

- Status: Accepted
- Supersedes: -

## Context

Cockpit ships artifacts into a project's integration: the `cockpit-run-context` skill
(ADR-0008) and, from this decision, a machine-readable pointer and a scriptable read surface for
frontends. The skill had its own one-purpose installer (`SkillInstaller`) with hard-coded
skip-if-present behavior. Adding a second artifact with different rules — one the package owns and
must be able to replace — would have meant a second installer, a second entry point, and two places
to reason about "what does this worktree have installed".

Two further gaps made frontends guess: the Markdown `current_run` index (ADR-0013) is prose, so a
program could not read the current run identity without parsing Markdown; and there was no versioned
contract a frontend could compare against its own expectations, so a shape change would surface as a
crash rather than a repair.

## Decision

**One installer.** `IntegrationInstaller` is a core service (no UI toolkit import) and the single
install/update path for every frontend artifact. It is invoked by `workflow-cockpit install` and by
the TUI start path, and it replaces `SkillInstaller` outright — no shim, no second code path
(AGENTS.md "no backward compatibility").

- **Targets are pluggable**, keyed on the integration read from `.specify/integration.json`
  (`default_integration`, else `integration`). The shipped target is the skill, which keeps its
  per-integration directory table and its neutral `.agents/skills` open-standard fallback, so its
  behavior is unchanged. A target table without a fallback reports `skipped_unregistered` and
  installs nothing.
- **Policies.** `user_editable` artifacts are installed once and then owned by the user: an existing
  file is never overwritten, whatever its content. `managed` artifacts are owned by the package:
  they carry a version marker and are replaced when the packaged version differs.
- **Version markers.** A managed Markdown artifact carries
  `<!-- workflow-cockpit-artifact: <name> <version> -->` as its first line; a non-Markdown managed
  artifact carries the same marker in a `.workflow-cockpit-artifact` sidecar. A missing marker means
  "unknown, therefore outdated". Content hashing was rejected: a user-edited managed file would
  differ either way, and the version is the declared contract.
- **Atomicity.** Every write is a temp file in the target directory plus `os.replace`, so no reader
  observes a partial artifact (FR-016).
- **Non-fatality.** One artifact failing is reported in the `InstallReport` and the others still
  run; the installer never raises and the command exits 0. Only "no discoverable project" is exit 2.

**Machine-readable pointer.** `current_run.json` is written as the JSON twin of the Markdown
`current_run` index and carries only `schema_version`, `run_id`, `run_dir`, and `workflow_id` —
a pointer, never run state. Two `os.replace` calls cannot be atomic across two files, so the writer
commits in a fixed order: **JSON first, then the Markdown index as the commit marker**. A reader
that finds the two naming different runs reports a disagreement and trusts neither. Writes never
produce that state; a hand-edited or half-removed pair does.

**Read envelope.** `workflow-cockpit context --json` returns one versioned, bounded, read-only JSON
object describing the current run the way the UI shows it — pointer state, run identity, status,
current step (composed-aware per ADR-0015), the open gate with exactly its declared options and a
null token, the graph projection the UI renders, a bounded Feature Files index, per-source
conditions, and an optional bounded single-file read. It composes the existing readers, never
writes, never takes or releases the claim, and never signals. `schema_version` starts at 1 and is
bumped on any shape change. Exit 0 whenever an envelope is produced (including no run and source
conditions); exit 2 only for no discoverable project or invalid arguments.

**Self-update contract.** A frontend records the `schema_version` (read command) and
`protocol_version` (host `status`) it supports. On mismatch it runs `workflow-cockpit install` once,
re-reads its managed artifact, and reports residual incompatibility to the user. It never edits a
user-editable artifact. Documented in
[`contracts/installer-and-self-update.md`](../../specs/006-shared-frontend-foundation/contracts/installer-and-self-update.md).

## Consequences

- One install/update surface, one report shape (`<outcome> <relative-path> [reason]`), and one place
  where "what is installed here" is decided.
- The skill's behavior is unchanged, verified by ported tests; the skill stays `user_editable`, so a
  user edit survives every install.
- A frontend that only reads can be built with no host: the envelope plus the pointer twin cover
  identity, status, step, gate, and files. A frontend that drives lifecycle adds the host protocol
  (ADR-0016).
- The envelope reports conditions (`missing`, `partial`, `stale`, `too_large`) per source and leaves
  the fields derived from a conditioned source null. It never infers state from another source, so
  the persisted run files stay the only state model.
- `current_run.json` is a new Cockpit-owned file next to the index; the real-engine contract test
  that asserts Cockpit writes no history outside the run directory now allows it explicitly.

## Rejected alternatives

- **Keep `SkillInstaller` and add a second installer.** Two policies, two entry points, and two
  answers to "what is installed"; the installer mechanism is the point of the change.
- **Content-hash comparison for managed artifacts.** It cannot distinguish a user edit from an
  outdated package copy, and it makes the update decision depend on bytes the user may legitimately
  have changed; the declared version is the contract.
- **Only a JSON pointer (drop the Markdown index).** ADR-0013 keeps the Markdown index for
  user-chosen external agents; dropping it would break that contract.
- **A directory-swap symlink for pointer atomicity.** Non-portable, and it changes what the pointer
  path is; the fixed write order plus disagreement reporting is enough.
- **A second read model for the envelope (re-parse `state.json`).** Drift from the UI and a second
  state model; the envelope composes the same readers.
- **Calling `specify workflow status --json` for the envelope.** A subprocess on the read path,
  opaque engine transport (ADR-0004), and it cannot report a stale or missing source.
