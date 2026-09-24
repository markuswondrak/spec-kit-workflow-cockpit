# Workflow Cockpit Catalog

This is the repository-owned Spec Kit catalog for Workflow Cockpit's dogfooding
stack. It curates released components from `spec-kit-extended-flow`; it does not
reimplement or republish them.

The catalog pins Extended Flow `v0.18.0` and points at its GitHub release assets
and tagged workflow definitions. Update all four catalog files together when
adopting a new Extended Flow release; see
[Adopting a new Extended Flow release](#adopting-a-new-extended-flow-release).

## Adopting a new Extended Flow release

Adopting a release means updating the catalog **and** refreshing the components already
installed in this worktree. Editing the catalog files alone does not touch `.specify/`,
so the installed preset, extension, and workflow definitions keep running the old code.

1. **Bump the catalog together.** Point all four catalog files at the new release and
   update their `version` fields:
   - `catalog/extension-catalog.json`
   - `catalog/preset-catalog.json`
   - `catalog/workflow-catalog.json`
   - `catalog/bundle-catalog.json`

   Update the pinned versions asserted in `tests/docs/test_release_assets.py` in the same
   change, then run `python -m pytest tests/docs -q`.

2. **Reinstall so `.specify/` matches the catalog.** The registered catalogs are pinned to
   a tag (see `.specify/preset-catalogs.yml`); a fresh registration plus bundle install
   replaces the installed extension, preset, and workflow definitions:

   ```bash
   scripts/setup-speckit.sh --source github
   ```

   This script is both the bootstrap and the upgrade path. When the catalogs are already
   registered, `specify bundle install spec-kit-extended-flow` refreshes the components on
   its own.

3. **Verify the installed state, not just the catalog.** Confirm the reinstall actually
   landed before trusting the next run:

   | Check | Expected |
   |---|---|
   | `.specify/presets/spec-kit-extended-flow/preset.yml` | new `version` |
   | `.specify/extensions/extendedflow/extension.yml` | new `version` |
   | `.specify/presets/.registry`, `.specify/bundle-records.json` | new `version`, recent `installed_at` |
   | `.specify/workflows/<flow>/workflow.yml` | matches the released definition |

4. **Start a new Cockpit run.** Workflow definitions are copied into
   `.specify/workflows/<flow>/workflow.yml` at install time and frozen per run as a launch
   copy under `.specify/workflows/runs/<run_id>/workflow.yml`. A run that already started
   keeps using its old copy, so adoption only takes effect for runs started after the
   reinstall.

For an unreleased local checkout, use `scripts/setup-speckit.sh --source local --path
../spec-kit-extended-flow` in step 2 instead.

## Install

```bash
BASE=https://raw.githubusercontent.com/markuswondrak/spec-kit-workflow-cockpit/main/catalog
specify extension catalog add "$BASE/extension-catalog.json" --name workflow-cockpit --install-allowed --priority 1
specify preset catalog add "$BASE/preset-catalog.json" --name workflow-cockpit --install-allowed --priority 1
specify workflow catalog add "$BASE/workflow-catalog.json" --name workflow-cockpit
specify bundle catalog add "$BASE/bundle-catalog.json" --id workflow-cockpit --priority 1
specify bundle install spec-kit-extended-flow
```

The local development alternative is documented in `CONTRIBUTING.md` and uses
`scripts/setup-speckit.sh --source local --path ../spec-kit-extended-flow`.
