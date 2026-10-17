#!/usr/bin/env bash
#
# Record composition fixtures from a real Spec Kit engine.
#
# The persisted execution tree is an engine-owned structure; hand-writing it
# would test Cockpit against an invented shape. This script drives the pinned
# engine through every referenced scenario and copies the resulting run files
# into `tests/fixtures/composition/<scenario>/`. Unit and Textual tests consume
# the committed copies and need no engine.
#
# Usage:
#   scripts/record-composition-fixtures.sh [--keep-work]
#
# Environment:
#   SPECIFY_FIXTURE_CMD   Engine command (default: `uv tool run --from specify-cli==1.1.3 specify`)
#   COMPOSITION_RECORD_WORK  Throwaway project directory (default: build/composition-record)
#
# Fixtures are deterministic in shape, not in timestamps: never assert on the
# recorded clock values.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${COMPOSITION_RECORD_WORK:-$ROOT/build/composition-record}"
OUT="$ROOT/tests/fixtures/composition"
SPECIFY_CMD_STR="${SPECIFY_FIXTURE_CMD:-uv tool run --from specify-cli==1.1.3 specify}"
read -ra SPECIFY_CMD <<<"$SPECIFY_CMD_STR"

KEEP_WORK=0
for arg in "$@"; do
  case "$arg" in
    --keep-work) KEEP_WORK=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

PROJECT="$WORK/project"
SRC="$WORK/src"

specify() {
  (cd "$PROJECT" && "${SPECIFY_CMD[@]}" "$@")
}

reset_project() {
  rm -rf "$PROJECT"
  mkdir -p "$PROJECT/.specify/workflows"
}

reset_runs() {
  rm -rf "$PROJECT/.specify/workflows/runs"
}

install_child() {
  # install_child <name>
  specify workflow add --dev "$SRC/$1/workflow.yml" >/dev/null
}

latest_run() {
  ls -t "$PROJECT/.specify/workflows/runs" | head -1
}

# capture <scenario> <run_id>
capture() {
  local scenario="$1" run_id="$2" run_dir
  run_dir="$PROJECT/.specify/workflows/runs/$run_id"
  if [ ! -d "$run_dir" ]; then
    echo "run directory missing for scenario $scenario: $run_dir" >&2
    exit 1
  fi
  rm -rf "$OUT/$scenario"
  mkdir -p "$OUT/$scenario"
  for name in state.json inputs.json log.jsonl workflow.yml; do
    if [ -f "$run_dir/$name" ]; then
      cp "$run_dir/$name" "$OUT/$scenario/$name"
    fi
  done
  # The engine's own view of the run is the drift oracle for the unit tests:
  # the recorded `status --json` names the active node and every scope path.
  specify workflow status "$run_id" --json >"$OUT/$scenario/status.json" 2>/dev/null || true
  echo "  recorded $scenario (run $run_id)"
}

write_source_workflows() {
  rm -rf "$SRC"
  mkdir -p "$SRC/release-notes" "$SRC/interactive-notes" "$SRC/inner" "$SRC/middle" "$SRC/broken-child"

  cat > "$SRC/release-notes/workflow.yml" <<'YAML'
workflow:
  id: release-notes
  name: Release Notes
  version: 1.0.0
  description: Draft and review release notes.
inputs:
  approval:
    type: string
    default: ""
steps:
  - id: draft
    type: shell
    run: "true"
  - id: review
    type: gate
    message: "Approve the release notes?"
    options: [approve, reject]
    verdict_input: approval
  - id: publish-notes
    type: shell
    run: "true"
YAML

  cat > "$SRC/interactive-notes/workflow.yml" <<'YAML'
workflow:
  id: interactive-notes
  name: Interactive Notes
  version: 1.0.0
  description: Draft and review notes through an interactive prompt.
steps:
  - id: draft
    type: shell
    run: "true"
  - id: review
    type: gate
    message: "Review the interactive notes."
    options: [approve, reject]
  - id: publish-notes
    type: shell
    run: "true"
YAML

  cat > "$SRC/inner/workflow.yml" <<'YAML'
workflow:
  id: inner
  name: Inner
  version: 1.0.0
  description: Innermost called workflow with the deep gate.
inputs:
  approval:
    type: string
    default: ""
steps:
  - id: deep-draft
    type: shell
    run: "true"
  - id: deep-review
    type: gate
    message: "Approve the inner result?"
    options: [approve, reject]
    verdict_input: approval
YAML

  cat > "$SRC/middle/workflow.yml" <<'YAML'
workflow:
  id: middle
  name: Middle
  version: 1.0.0
  description: Middle workflow that calls the innermost one.
inputs:
  approval:
    type: string
    default: ""
steps:
  - id: middle-prep
    type: shell
    run: "true"
  - id: inner-call
    type: workflow
    workflow: inner
    input:
      approval: "{{ inputs.approval }}"
YAML

  cat > "$SRC/broken-child/workflow.yml" <<'YAML'
workflow:
  id: broken-child
  name: Broken Child
  version: 1.0.0
  description: Fails on its second step.
steps:
  - id: good
    type: shell
    run: "true"
  - id: boom
    type: shell
    run: "false"
  - id: never
    type: shell
    run: "true"
YAML
}

install_all_children() {
  install_child release-notes
  install_child interactive-notes
  install_child inner
  install_child middle
  install_child broken-child
}

run_workflow() {
  # run_workflow <yaml-file> [extra args...]
  local yaml="$1"; shift
  specify workflow run "$yaml" --json "$@" >/dev/null
}

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

scenario_reference() {
  reset_project
  install_all_children
  cat > "$PROJECT/release.yml" <<'YAML'
workflow:
  id: release
  name: Release
  version: 1.0.0
  description: Build, review the notes, publish.
inputs:
  approval:
    type: string
    default: ""
steps:
  - id: build
    type: shell
    run: "true"
  - id: review-release
    type: workflow
    workflow: release-notes
    input:
      approval: "{{ inputs.approval }}"
  - id: publish
    type: shell
    run: "true"
YAML
  run_workflow release.yml
  capture reference "$(latest_run)"
}

scenario_collision() {
  reset_project
  install_all_children
  cat > "$PROJECT/collision.yml" <<'YAML'
workflow:
  id: release-collision
  name: Release Collision
  version: 1.0.0
  description: A root gate id that collides with the called workflow's gate id.
inputs:
  approval:
    type: string
    default: ""
  root_approval:
    type: string
    default: ""
steps:
  - id: build
    type: shell
    run: "true"
  - id: review
    type: gate
    message: "Approve the root release?"
    options: [approve, reject]
    verdict_input: root_approval
  - id: review-release
    type: workflow
    workflow: release-notes
    input:
      approval: "{{ inputs.approval }}"
  - id: publish
    type: shell
    run: "true"
YAML
  run_workflow collision.yml
  local root_run
  root_run="$(latest_run)"
  specify workflow resume "$root_run" -i root_approval=approve --json >/dev/null
  capture collision "$root_run"
}

scenario_depth2() {
  reset_project
  install_all_children
  cat > "$PROJECT/deep.yml" <<'YAML'
workflow:
  id: deep-release
  name: Deep Release
  version: 1.0.0
  description: A gate two calls deep.
inputs:
  approval:
    type: string
    default: ""
steps:
  - id: build
    type: shell
    run: "true"
  - id: middle-call
    type: workflow
    workflow: middle
    input:
      approval: "{{ inputs.approval }}"
  - id: publish
    type: shell
    run: "true"
YAML
  run_workflow deep.yml
  capture depth2 "$(latest_run)"
}

scenario_loop_paused() {
  reset_project
  install_all_children
  cat > "$PROJECT/loop.yml" <<'YAML'
workflow:
  id: loop-release
  name: Loop Release
  version: 1.0.0
  description: Calls the same child workflow twice in a loop.
inputs:
  approval:
    type: string
    default: ""
  keep_going:
    type: string
    default: "yes"
steps:
  - id: notes-loop
    type: do-while
    condition: "{{ inputs.keep_going | contains('yes') }}"
    max_iterations: 2
    steps:
      - id: notes-call
        type: workflow
        workflow: release-notes
        input:
          approval: "{{ inputs.approval }}"
  - id: after
    type: shell
    run: "true"
YAML
  run_workflow loop.yml
  capture loop-paused "$(latest_run)"
}

scenario_loop_twice() {
  reset_project
  install_all_children
  cat > "$PROJECT/loop.yml" <<'YAML'
workflow:
  id: loop-release
  name: Loop Release
  version: 1.0.0
  description: Calls the same child workflow twice in a loop.
inputs:
  approval:
    type: string
    default: ""
  keep_going:
    type: string
    default: "yes"
steps:
  - id: notes-loop
    type: do-while
    condition: "{{ inputs.keep_going | contains('yes') }}"
    max_iterations: 2
    steps:
      - id: notes-call
        type: workflow
        workflow: release-notes
        input:
          approval: "{{ inputs.approval }}"
  - id: after
    type: shell
    run: "true"
YAML
  run_workflow loop.yml
  local run_id
  run_id="$(latest_run)"
  specify workflow resume "$run_id" -i approval=approve --json >/dev/null
  capture loop-twice "$run_id"
}

scenario_fanout() {
  reset_project
  install_all_children
  cat > "$PROJECT/fanout.yml" <<'YAML'
workflow:
  id: fanout-release
  name: Fanout Release
  version: 1.0.0
  description: Fan-out over a call whose child holds an interactive gate.
steps:
  - id: prep
    type: shell
    run: "true"
  - id: fan
    type: fan-out
    items: ["alpha", "beta"]
    step:
      id: notes
      type: workflow
      workflow: interactive-notes
  - id: after
    type: shell
    run: "true"
YAML
  run_workflow fanout.yml || true
  capture fanout "$(latest_run)"
}

scenario_fanout_verdict() {
  reset_project
  install_all_children
  cat > "$PROJECT/fanout-verdict.yml" <<'YAML'
workflow:
  id: fanout-verdict
  name: Fanout Verdict
  version: 1.0.0
  description: Fan-out over a call whose child holds a verdict_input gate.
inputs:
  approval:
    type: string
    default: ""
steps:
  - id: prep
    type: shell
    run: "true"
  - id: fan
    type: fan-out
    items: ["alpha"]
    step:
      id: notes
      type: workflow
      workflow: release-notes
      input:
        approval: "{{ inputs.approval }}"
  - id: after
    type: shell
    run: "true"
YAML
  run_workflow fanout-verdict.yml || true
  capture fanout-verdict "$(latest_run)"
}

scenario_failed_child() {
  reset_project
  install_all_children
  cat > "$PROJECT/failed.yml" <<'YAML'
workflow:
  id: failed-release
  name: Failed Release
  version: 1.0.0
  description: A called workflow whose second step fails.
steps:
  - id: build
    type: shell
    run: "true"
  - id: broken-call
    type: workflow
    workflow: broken-child
  - id: publish
    type: shell
    run: "true"
YAML
  run_workflow failed.yml || true
  capture failed-child "$(latest_run)"
}

scenario_continue_on_error() {
  reset_project
  install_all_children
  cat > "$PROJECT/handled.yml" <<'YAML'
workflow:
  id: handled-release
  name: Handled Release
  version: 1.0.0
  description: A call that fails under continue_on_error and the run continues.
steps:
  - id: build
    type: shell
    run: "true"
  - id: broken-call
    type: workflow
    workflow: broken-child
    continue_on_error: true
  - id: publish
    type: shell
    run: "true"
YAML
  run_workflow handled.yml || true
  capture continue-on-error "$(latest_run)"
}

scenario_dynamic_target() {
  reset_project
  install_all_children
  cat > "$PROJECT/dynamic.yml" <<'YAML'
workflow:
  id: dynamic-release
  name: Dynamic Release
  version: 1.0.0
  description: A call whose target is chosen by an input expression.
inputs:
  target:
    type: string
    default: "release-notes"
  approval:
    type: string
    default: ""
  go:
    type: string
    default: ""
steps:
  - id: pre-gate
    type: gate
    message: "Proceed with the dynamic release?"
    options: [approve, reject]
    verdict_input: go
  - id: dyn-call
    type: workflow
    workflow: "{{ inputs.target }}"
    input:
      approval: "{{ inputs.approval }}"
  - id: publish
    type: shell
    run: "true"
YAML
  run_workflow dynamic.yml
  capture dynamic-target "$(latest_run)"
}

main() {
  mkdir -p "$OUT"
  write_source_workflows
  reset_runs
  scenario_reference
  scenario_collision
  scenario_depth2
  scenario_loop_paused
  scenario_loop_twice
  scenario_fanout
  scenario_fanout_verdict
  scenario_failed_child
  scenario_continue_on_error
  scenario_dynamic_target
  if [ "$KEEP_WORK" -eq 0 ]; then
    rm -rf "$WORK"
  fi
  echo "fixtures written to $OUT"
}

main
