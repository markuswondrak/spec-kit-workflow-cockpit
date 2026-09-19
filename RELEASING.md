# Releasing Workflow Cockpit

This is the maintainer runbook for cutting a release. Contributors do not need it; see
[CONTRIBUTING.md](CONTRIBUTING.md) for setup and verification.

## Versioning

Releases use Semantic Versioning tags of the form `vMAJOR.MINOR.PATCH`. While the package is
pre-1.0, `MINOR` may carry breaking changes and `PATCH` carries fixes and compatible additions.

The package version has exactly one source of truth: `__version__` in
`workflow_cockpit/__init__.py`. `pyproject.toml` declares a dynamic version that resolves to that
attribute, so there is no second value to keep in sync. Never edit the version in `pyproject.toml`;
it has no static version field.

The dogfooding components under `presets/`, `workflows/`, `extensions/`, and `bundles/` version
independently (their manifests and the catalog JSON). Their versions are unrelated to the package
version and are bumped only when those components change.

## Cutting a release

Releases are only cut from `main`. The release workflow refuses a tag whose commit is not an
ancestor of `main`, and refuses a tag that does not match the package version exactly.

1. Confirm `main` is green in the [Test workflow](.github/workflows/test.yml).
2. Update `__version__` in `workflow_cockpit/__init__.py` to the new `X.Y.Z`.
3. If the change is user-visible, merge that bump through a normal pull request. Include release
   notes wherever the change is described; the release body is generated from merged pull requests
   and commit messages between tags.
4. Tag `main`, then push the tag:

   ```bash
   git switch main
   git pull --ff-only
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

5. Watch the [Release workflow](.github/workflows/release.yml). It verifies the tagged commit,
   guards the tag, builds the sdist and wheel, smoke-installs them, and publishes a GitHub Release
   with the generated notes.

If a guard or the verify job fails, delete the tag (`git push origin :vX.Y.Z`), fix `main`, and tag
again. Do not publish a release from a red commit.

## Hotfixes

1. Branch from the released tag, not from the tip of `main`:

   ```bash
   git switch -c hotfix/X.Y.Z vPREVIOUS
   ```

2. Apply the minimal fix, bump `__version__` to the next `PATCH`, and open a pull request into
   `main`.
3. Once merged, tag `main` with `vX.Y.Z` as in the normal flow. The guard only checks that the
   tagged commit is on `main`, so the fix must land there before it can be released.

## Distribution

GitHub is the distribution channel. Install from the repository:

```bash
python -m pip install "git+https://github.com/markuswondrak/spec-kit-workflow-cockpit.git@vX.Y.Z"
```

PyPI publishing is intentionally not configured. Add it later through Trusted Publishing if a
PyPI presence is wanted; the release workflow would gain an `id-token: write` publish job gated on a
`pypi` environment.
