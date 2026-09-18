# Workflow Cockpit bundle

Declarative component set for developing this repository through its own workflow:
the `lean-workflow` preset, the `arc42` documentation extension, and the `lean-flow`
workflow.

The components live elsewhere in this repository (`presets/`, `extensions/`,
`workflows/`). `specify bundle install` resolves them through the project-owned
catalog under [`catalog/`](../../catalog/README.md), not from this directory.

## Usage

```bash
# One-time bootstrap in a project checkout (see scripts/setup-speckit.sh):
scripts/setup-speckit.sh

# Manual equivalent:
specify extension catalog add <raw-catalog-url>/extension-catalog.json --name workflow-cockpit --install-allowed --priority 1
specify preset catalog add <raw-catalog-url>/preset-catalog.json --name workflow-cockpit --install-allowed --priority 1
specify workflow catalog add <raw-catalog-url>/workflow-catalog.json --name workflow-cockpit
specify bundle install bundles/workflow-cockpit
```

Rebuild the catalog artifacts after changing a component:

```bash
scripts/build-catalog.sh
```
