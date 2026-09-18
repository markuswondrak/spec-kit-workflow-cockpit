# Project-owned Spec Kit catalog

A catalog owned by this repository, served over HTTPS from `raw.githubusercontent.com`.
It lets `specify bundle install` resolve this repository's own components without a
local HTTP server, `--dev` symlinks, or publishing to a third-party catalog.

The catalogs are integration-agnostic and install-allowed: they are the sanctioned
mechanism for private/repository-local components (see
[spec-kit#3058](https://github.com/github/spec-kit/issues/3058)).

## Contents

| File | Purpose |
|---|---|
| `extension-catalog.json` | Points at the `arc42` extension archive. |
| `preset-catalog.json` | Points at the `lean-workflow` preset archive. |
| `workflow-catalog.json` | Points directly at `workflows/lean-flow/workflow.yml`. |
| `bundle-catalog.json` | Points at the built bundle artifact (optional; `bundle install <path>` skips it). |
| `artifacts/` | Generated archives referenced by the catalogs. |

## Build

Regenerate `artifacts/` after changing a component (versions come from each manifest):

```bash
scripts/build-catalog.sh
```

Commit the rebuilt archives so the raw URLs resolve.

## Register

Catalogs are registered per project. `scripts/setup-speckit.sh` does this; the manual
equivalent is:

```bash
BASE=https://raw.githubusercontent.com/markuswondrak/spec-kit-workflow-cockpit/main
specify extension catalog add "$BASE/catalog/extension-catalog.json" --name workflow-cockpit --install-allowed --priority 1
specify preset catalog add "$BASE/catalog/preset-catalog.json" --name workflow-cockpit --install-allowed --priority 1
specify workflow catalog add "$BASE/catalog/workflow-catalog.json" --name workflow-cockpit
```

## Why not a local directory?

Spec Kit only accepts `https://` or `http://localhost` for extension, preset, and
workflow catalog URLs, and only `https://`/localhost for their download URLs. A plain
local path or `file://` is rejected, so without a local server the catalog must be
reachable over HTTPS.
