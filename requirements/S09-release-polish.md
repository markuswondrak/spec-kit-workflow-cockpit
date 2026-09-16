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
- The README describes the relationship to [AgentMux](https://github.com/markuswondrak/AgentMux)
  and how `workflow-cockpit` complements its deterministic multi-agent pipeline; ongoing
  further development of AgentMux is an explicit part of this story's scope.
- Development follows the dogfooding principle: changes to this repository are driven through
  the bundled [`presets/lean-workflow`](../presets/lean-workflow) preset and observed/decided in
  the cockpit itself, and `CONTRIBUTING.md` documents this as the preferred development path.
- The README describes the arc42 documentation layout and links to
  [the documentation context article](https://markus.wondrax.cloud/articles/documentation-agentic-coding.html).

## Tests

- The CI steps are runnable locally with the same commands and pass.
- A clean-environment install of the built wheel exposes the `workflow-cockpit` entry point.
- README quickstart commands are executed as written.
- The AgentMux relationship is documented in the README and the linked repository is reachable.
- A documented dogfooding run drives a repository change through the bundled preset into the
  cockpit and is reproducible from the `CONTRIBUTING.md` instructions.
