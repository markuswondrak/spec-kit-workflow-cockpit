# Workflow Cockpit Catalog

This is the repository-owned Spec Kit catalog for Workflow Cockpit's dogfooding
stack. It curates released components from `spec-kit-extended-flow`; it does not
reimplement or republish them.

The catalog pins Extended Flow `v0.13.0` and points at its GitHub release assets
and tagged workflow definitions. Update all four catalog files together when
adopting a new Extended Flow release.

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
