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

Use `scripts/release.sh`. It requires a clean `main` that is in sync with `origin/main`, bumps the
version, commits `Release vX.Y.Z`, creates the annotated tag, and pushes both. Preview the result
without changing anything with `--dry-run`:

```bash
scripts/release.sh --dry-run   # e.g. 0.1.0 -> 0.2.0
scripts/release.sh             # minor bump (default); prompts before pushing
scripts/release.sh minor -y    # same, without the prompt
```

1. Confirm `main` is green in the [Test workflow](.github/workflows/test.yml).
2. Run the script. Bump kinds:
   - `minor` (default) for features and compatible changes,
   - `patch` for a hotfix,
   - `major` for a breaking change,
   - `current` to release the existing `__version__` unchanged, used for the very first release.
3. Watch the [Release workflow](.github/workflows/release.yml). It verifies the tagged commit,
   guards the tag, builds the sdist and wheel, smoke-installs them, and publishes a GitHub Release
   with the generated notes.

The script pushes the bump commit and the tag together, so the tagged commit is always the version
commit. If a guard or the verify job fails, delete the tag (`git push origin :vX.Y.Z`), fix `main`,
and release again. Do not publish a release from a red commit.

## Hotfixes

1. Branch from the released tag, not from the tip of `main`:

   ```bash
   git switch -c hotfix/X.Y.Z vPREVIOUS
   ```

2. Apply the minimal fix and open a pull request into `main`. Do not bump the version there; the
   release script owns the bump.
3. Once merged, cut the patch release from `main`:

   ```bash
   scripts/release.sh patch
   ```

   The guard only checks that the tagged commit is on `main`, so the fix must land there before the
   patch can be released.

## Distribution

GitHub is the distribution channel. Install from the repository:

```bash
python -m pip install "git+https://github.com/markuswondrak/spec-kit-workflow-cockpit.git@vX.Y.Z"
```

PyPI publishing is intentionally not configured. Add it later through Trusted Publishing if a
PyPI presence is wanted; the release workflow would gain an `id-token: write` publish job gated on a
`pypi` environment.
