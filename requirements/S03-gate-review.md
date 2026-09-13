# Story 3 - Review and decide a structured gate

> As a workflow user, I want to inspect Worktree Changes and submit a declared gate choice so
> that the review loop works without leaving the Cockpit.

| Field | Value |
|---|---|
| ID | S3 |
| Requirements | FR-3, FR-5 (structured) |
| Dependencies | S1, S2 |

## Acceptance criteria

- Persisted state identifies a paused gate and its step, message, and exact declared options.
- The Runway highlights the gate and the review surface opens automatically.
- Worktree Changes compares the current worktree with the fixed Start commit, including dirty
  pre-start changes.
- Created, modified, deleted, and renamed files are listed; `.specify/` and Git-ignored files
  are excluded.
- Text files provide unified diff and rendered/current-file views; binaries show metadata;
  large files use a bounded preview.
- The review refreshes while paused and handles an empty change set.
- An existing selected file can open in `$EDITOR` while Textual is suspended. The action is
  unavailable while running, for deleted files, or when `$EDITOR` is unset.
- Every gate choice requires confirmation; opening every file is not required.
- A gate with `verdict_input` uses structured resume and preserves workflow retry/skip behavior.
- Persisted state remains authoritative after submission.

## Tests

- Unit tests cover diff classification, exclusions, dirty baselines, branch changes, binary
  detection, and gate strategy selection.
- Textual and integration tests cover review, editor suspension, confirmation, continue,
  retry, skip, empty changes, and CLI failure.
