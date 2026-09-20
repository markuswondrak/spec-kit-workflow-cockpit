#!/usr/bin/env bash
# Bootstrap Spec Kit in a fresh clone of spec-kit-workflow-cockpit.
#
# Installs the published Extended Flow by default. Local development remains
# available explicitly so the sibling checkout can be tested before a release.
#
# Usage:
#   scripts/setup-speckit.sh [--source github|local] [--ref REF] [--path PATH]
#
#   --source  Installation source (default: github).
#   --ref     Git ref for the Workflow Cockpit catalog (default: main).
#   --path    Local checkout (default: ../spec-kit-extended-flow).
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="github"
REF="main"
FLOW_PATH="../spec-kit-extended-flow"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --source)
            [ "$#" -ge 2 ] || {
                echo "ERROR: --source requires 'github' or 'local'." >&2
                exit 1
            }
            SOURCE="$2"
            [ "$SOURCE" = "github" ] || [ "$SOURCE" = "local" ] || {
                echo "ERROR: --source must be 'github' or 'local'." >&2
                exit 1
            }
            shift 2
            ;;
        --ref)
            [ "$#" -ge 2 ] || {
                echo "ERROR: --ref requires a Git ref." >&2
                exit 1
            }
            REF="$2"
            shift 2
            ;;
        --path)
            [ "$#" -ge 2 ] || {
                echo "ERROR: --path requires a directory." >&2
                exit 1
            }
            FLOW_PATH="$2"
            shift 2
            ;;
        --help|-h)
            sed -n '2,13p' "$0"
            exit 0
            ;;
        *)
            echo "ERROR: Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

command -v specify >/dev/null 2>&1 || {
    echo "ERROR: 'specify' CLI not found. Install: uv tool install specify-cli" >&2
    exit 1
}

echo "==> Initializing Spec Kit core"
(cd "$PROJECT_ROOT" && specify init --here --force --non-interactive \
    --integration opencode --script sh)

echo "==> Disabling the Spec Kit git extension when present"
(cd "$PROJECT_ROOT" && specify extension disable git >/dev/null 2>&1 || true)

if [ "$SOURCE" = "github" ]; then
    CATALOG_BASE="https://raw.githubusercontent.com/markuswondrak/spec-kit-workflow-cockpit/$REF/catalog"
    echo "==> Registering Extended Flow catalogs ($REF)"
    (cd "$PROJECT_ROOT" && \
        specify extension catalog add "$CATALOG_BASE/extension-catalog.json" \
            --name spec-kit-extended-flow --install-allowed --priority 1 && \
        specify preset catalog add "$CATALOG_BASE/preset-catalog.json" \
            --name spec-kit-extended-flow --install-allowed --priority 1 && \
        specify workflow catalog add "$CATALOG_BASE/workflow-catalog.json" \
            --name spec-kit-extended-flow && \
        specify bundle catalog add "$CATALOG_BASE/bundle-catalog.json" \
            --id spec-kit-extended-flow --priority 1)

    echo "==> Installing released Extended Flow bundle"
    (cd "$PROJECT_ROOT" && specify bundle install spec-kit-extended-flow)
else
    if [[ "$FLOW_PATH" = /* ]]; then
        EXTENDED_FLOW_ROOT="$FLOW_PATH"
    else
        EXTENDED_FLOW_ROOT="$PROJECT_ROOT/$FLOW_PATH"
    fi
    EXTENDED_FLOW_ROOT="$(cd "$EXTENDED_FLOW_ROOT" && pwd)"

    for required in preset.yml extension.yml bundle.yml workflows/workflow.yml workflows/bugfix-workflow.yml workflows/quick-flow.yml; do
        [ -e "$EXTENDED_FLOW_ROOT/$required" ] || {
            echo "ERROR: Extended Flow path is missing '$required': $EXTENDED_FLOW_ROOT" >&2
            exit 1
        }
    done

    echo "==> Installing the bug extension"
    (cd "$PROJECT_ROOT" && specify extension add bug)

    echo "==> Installing local Extended Flow extension and preset from $EXTENDED_FLOW_ROOT"
    (cd "$PROJECT_ROOT" && \
        specify extension add --dev "$EXTENDED_FLOW_ROOT" && \
        specify preset add --dev "$EXTENDED_FLOW_ROOT" --priority 1)

    echo "==> Installing local Extended Flow workflows"
    (cd "$PROJECT_ROOT" && \
        specify workflow add --dev "$EXTENDED_FLOW_ROOT/workflows/workflow.yml" && \
        specify workflow add --dev "$EXTENDED_FLOW_ROOT/workflows/bugfix-workflow.yml" && \
        specify workflow add --dev "$EXTENDED_FLOW_ROOT/workflows/quick-flow.yml")
fi

echo "==> Done."
