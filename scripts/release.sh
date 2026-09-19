#!/usr/bin/env bash
# Cut a release of workflow-cockpit.
#
# Bumps the package version in workflow_cockpit/__init__.py, commits the bump on
# main, creates the matching annotated tag, and pushes both to origin. The
# Release workflow (triggered by the v* tag) then re-verifies the tagged commit
# and publishes the GitHub Release.
#
# Usage:
#   scripts/release.sh [minor|major|patch|current] [--dry-run] [-y|--yes]
#
#   minor      Increment the minor version and reset patch to 0 (default).
#   major      Increment the major version and reset minor and patch to 0.
#   patch      Increment the patch version; use for a hotfix.
#   current    Release the current __version__ unchanged; use for the first release.
#   --dry-run  Print the planned version and exit without touching anything.
#   -y, --yes  Skip the confirmation prompt.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/release.sh [minor|major|patch|current] [--dry-run] [-y|--yes]

  minor      Increment the minor version and reset patch to 0 (default).
  major      Increment the major version and reset minor and patch to 0.
  patch      Increment the patch version; use for a hotfix.
  current    Release the current __version__ unchanged; use for the first release.
  --dry-run  Print the planned version and exit without touching anything.
  -y, --yes  Skip the confirmation prompt.
EOF
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INIT_FILE="$ROOT/workflow_cockpit/__init__.py"

BUMP="minor"
DRY_RUN=0
ASSUME_YES=0

for arg in "$@"; do
    case "$arg" in
        minor|major|patch|current) BUMP="$arg" ;;
        --dry-run) DRY_RUN=1 ;;
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown argument '$arg'" >&2; usage >&2; exit 2 ;;
    esac
done

command -v git >/dev/null 2>&1 || { echo "ERROR: git not found." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found." >&2; exit 1; }

read -r current next <<<"$(python3 - "$INIT_FILE" "$BUMP" <<'PY'
import re
import sys

path, bump = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
match = re.search(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"$', text, re.MULTILINE)
if match is None:
    raise SystemExit(f"ERROR: no X.Y.Z __version__ in {path}")

major, minor, patch = (int(group) for group in match.groups())
if bump == "major":
    major, minor, patch = major + 1, 0, 0
elif bump == "minor":
    minor, patch = minor + 1, 0
elif bump == "patch":
    patch += 1

current = ".".join(str(part) for part in match.groups())
print(current, f"{major}.{minor}.{patch}")
PY
)"

echo "Release plan: $current -> $next (bump: $BUMP)"

if [[ "$DRY_RUN" == "1" ]]; then
    exit 0
fi

# A release is cut from an up-to-date main with a clean working tree.
current_branch="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
if [[ "$current_branch" != "main" ]]; then
    echo "ERROR: releases are cut from main (currently on '$current_branch')." >&2
    exit 1
fi
if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
    echo "ERROR: working tree is not clean; commit or stash first." >&2
    exit 1
fi

git -C "$ROOT" fetch --quiet origin main
if [[ "$(git -C "$ROOT" rev-parse HEAD)" != "$(git -C "$ROOT" rev-parse origin/main)" ]]; then
    echo "ERROR: local main is not in sync with origin/main; pull first." >&2
    exit 1
fi

if [[ "$ASSUME_YES" != "1" ]]; then
    read -r -p "Commit, tag v$next, and push to origin/main? [y/N] " reply
    case "$reply" in
        y|Y) ;;
        *) echo "Aborted."; exit 1 ;;
    esac
fi

python3 - "$INIT_FILE" "$next" <<'PY'
import re
import sys

path, version = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
updated, count = re.subn(
    r'^__version__ = "[^"]+"$',
    f'__version__ = "{version}"',
    text,
    count=1,
    flags=re.MULTILINE,
)
if count != 1:
    raise SystemExit(f"ERROR: could not update {path}")
open(path, "w", encoding="utf-8").write(updated)
PY

git -C "$ROOT" commit -am "Release v$next"
git -C "$ROOT" tag -a "v$next" -m "v$next"
git -C "$ROOT" push origin main
git -C "$ROOT" push origin "v$next"

echo "Pushed v$next. The Release workflow verifies and publishes the tag."
