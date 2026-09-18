#!/usr/bin/env bash
# Bootstrap Spec Kit in a fresh clone of spec-kit-workflow-cockpit.
#
# Installs the core scaffolding, registers this repository's project-owned
# HTTPS catalog (no local server), and installs the bundle that declares the
# dogfooding components (lean-workflow preset, arc42 extension, lean-flow
# workflow).
#
# Usage:
#   scripts/setup-speckit.sh [ref]
#
#   ref  Git ref whose raw catalog files are used (default: main).
set -euo pipefail

REF="${1:-main}"
BASE="https://raw.githubusercontent.com/markuswondrak/spec-kit-workflow-cockpit/$REF"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v specify >/dev/null 2>&1 || {
    echo "ERROR: 'specify' CLI not found. Install: uv tool install specify-cli" >&2
    exit 1
}

echo "==> Initializing Spec Kit core"
(cd "$PROJECT_ROOT" && specify init --here --force --non-interactive \
    --integration opencode --script sh)

echo "==> Registering project catalog ($REF)"
(cd "$PROJECT_ROOT" && \
    specify extension catalog add "$BASE/catalog/extension-catalog.json" \
        --name workflow-cockpit --install-allowed --priority 1 && \
    specify preset catalog add "$BASE/catalog/preset-catalog.json" \
        --name workflow-cockpit --install-allowed --priority 1 && \
    specify workflow catalog add "$BASE/catalog/workflow-catalog.json" \
        --name workflow-cockpit)

echo "==> Installing workflow-cockpit bundle"
(cd "$PROJECT_ROOT" && specify bundle install "$PROJECT_ROOT/bundles/workflow-cockpit")

echo "==> Done."
