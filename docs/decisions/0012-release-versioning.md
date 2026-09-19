# 0012. The package version is single-sourced and releases are tag-driven from main

- Status: Accepted
- Supersedes: -
- Amends: -

## Context

The package version was written twice, as `version` in `pyproject.toml` and `__version__` in
`workflow_cockpit/__init__.py`, with nothing enforcing that the two agreed. No git tags existed and
no release workflow existed, so versioning, tagging, and distribution were entirely manual and
undocumented. A release process that can silently ship a wheel whose metadata disagrees with the
importable version is worse than no process.

The project is small, pre-1.0, and distributed through GitHub rather than PyPI. The mechanism should
match that scale instead of importing release infrastructure it does not need.

## Decision

1. `__version__` in `workflow_cockpit/__init__.py` is the only package version. `pyproject.toml`
   declares `dynamic = ["version"]` and resolves it through
   `[tool.setuptools.dynamic] version = {attr = "workflow_cockpit.__version__"}`. There is no static
   version field to keep in sync.
2. Releases are Semantic Versioning tags of the form `vMAJOR.MINOR.PATCH`. A release is cut only
   from a commit that is an ancestor of `main`.
3. `.github/workflows/release.yml` triggers on `v*` tags. It re-verifies the tagged commit by
   calling `test.yml` as a reusable workflow, refuses a tag that is not on `main` or that does not
   match `__version__`, builds and smoke-installs the sdist and wheel, and publishes a GitHub
   Release with generated notes and the artifacts.
4. GitHub is the distribution channel. PyPI publishing is deliberately not configured.
5. `test.yml` still runs on every push and every pull request; only release publication is
   restricted to `main`.

## Consequences

- The version cannot drift: `pyproject.toml` has no version to disagree with `__version__`.
- A tag is the release trigger, so the released commit is exactly the verified commit.
- Release notes come from merged pull requests and commit messages; there is no second changelog to
  maintain.
- A first release must be tagged manually; the pipeline cannot create the tag that triggers it.
- Adopting PyPI later means adding a gated publish job, not reworking the version source.

## Rejected alternatives

- **`setuptools-scm` (derive the version from git tags):** adds a build-time dependency and makes
  builds depend on git history, while the runtime `__version__` would still need a fallback for
  source checkouts. The dynamic-attribute approach is simpler and keeps one editable value.
- **Keeping a static version in `pyproject.toml`:** preserves the exact two-place drift this
  decision removes.
- **Publishing releases manually with `gh release create`:** leaves verification, version matching,
  and main-only enforcement to human discipline rather than the pipeline.
- **Maintaining a `CHANGELOG.md`:** duplicates what generated GitHub release notes already provide
  for a pre-1.0 project with one contributor.
- **Publishing to PyPI now:** the project is installed from GitHub; PyPI adds credential and
  provenance setup without a consumer that needs it yet.
