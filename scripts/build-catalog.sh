#!/usr/bin/env bash
# Rebuild the project-owned catalog archives under catalog/artifacts/.
#
# Component archives are plain zips whose root contains the component manifest
# (extension.yml / preset.yml) or the bundle manifest (bundle.yml). Versions are
# read from the manifests, so a version bump only needs a rerun of this script
# plus the matching catalog JSON + bundle pin update.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/catalog/artifacts"

command -v zip >/dev/null 2>&1 || {
    echo "ERROR: 'zip' not found." >&2
    exit 1
}

manifest_version() {
    # First 'version:' scalar in the file (skips 'speckit_version:').
    grep -m1 '^[[:space:]]*version:' "$1" |
        sed -E 's/^[[:space:]]*version:[[:space:]]*"?([^"#]+)"?.*/\1/' |
        tr -d '[:space:]'
}

ARC42_VERSION="$(manifest_version "$ROOT/extensions/arc42/extension.yml")"
PRESET_VERSION="$(manifest_version "$ROOT/presets/lean-workflow/preset.yml")"
BUNDLE_VERSION="$(manifest_version "$ROOT/bundles/workflow-cockpit/bundle.yml")"

mkdir -p "$OUT"
rm -f "$OUT"/arc42-*.zip "$OUT"/lean-workflow-*.zip "$OUT"/workflow-cockpit-*.zip

(cd "$ROOT/extensions/arc42" && zip -qr "$OUT/arc42-$ARC42_VERSION.zip" .)
(cd "$ROOT/presets/lean-workflow" && zip -qr "$OUT/lean-workflow-$PRESET_VERSION.zip" .)
(cd "$ROOT/bundles/workflow-cockpit" && zip -qr "$OUT/workflow-cockpit-$BUNDLE_VERSION.zip" .)

echo "Built catalog artifacts:"
ls -1 "$OUT"
