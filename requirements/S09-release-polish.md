# Story 9 - Release polish for publishing

> As a maintainer, I want the project ready to publish so that users can install and evaluate it
> and contributors can build and verify it with confidence.

| Field | Value |
|---|---|
| ID | S9 |
| Requirements | Quality requirements, distribution |
| Dependencies | S1-S8 |

## Acceptance criteria

- A CI workflow runs `ruff check` and the full unit, Textual, contract, and PTY suites on push
  and pull request; any failure fails the check.
- The README covers overview, prerequisites, installation, quickstart, configuration, the
  requirements pointers, contributing, and license.
- A `LICENSE` file exists and matches the license declared in `pyproject.toml` (MIT).
- `pyproject.toml` carries complete distribution metadata (description, readme, license,
  authors, keywords, classifiers, project URLs, `requires-python`) and `python -m build`
  produces installable sdist and wheel artifacts.
- `CONTRIBUTING.md` documents local setup plus the exact test and lint commands.
- The documented install path works from the built artifact in a clean environment.

## Tests

- The CI steps are runnable locally with the same commands and pass.
- A clean-environment install of the built wheel exposes the `workflow-cockpit` entry point.
- README quickstart commands are executed as written.
