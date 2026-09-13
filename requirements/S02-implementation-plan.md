# Implementation Plan: S02 - Workflow runway

| Field | Value |
|---|---|
| Status | Implemented |
| Story | S02 - Workflow runway (implemented) |
| Requirements | FR-2 |
| Dependencies | S01 (implemented) |
| Baseline | `PRD.md`, `TUI_DESIGN.md`, `UI_DESIGN.md`, `ARCHITECTURE.md`, `engine-contract.md` |
| Package | Top-level `workflow_cockpit/` |

This plan realizes S02 against the engine control flow recorded in
`engine-contract.md` and the source at `/home/markus/workspace/spec-kit`. Product contract
stays in `PRD.md`; component names stay in `ARCHITECTURE.md`; visual behavior stays in
`UI_DESIGN.md`. This file only sequences the work.

## 1. Scope

### In

- Generic parser turning the effective workflow definition into a `ControlFlowGraph` covering
  linear steps, `if`/`then`/`else`, `switch`/`cases`/`default`, `while`, `do-while`,
  `fan-out`/`fan-in`, gates, and overlay-composed steps.
- Runtime projection of that graph from persisted `state.json` and `log.jsonl`: node status
  (pending, running, paused, completed, failed, skipped, aborted), active path, attempt count,
  and completed/live per-step duration.
- `Runway` widget replacing S01's `StepRail`: scrollable graph with runtime overlay, selection,
  active-path highlight, gate/attempt/timing annotations, and responsive strip layout.
- Focus as one state-driven canvas: Engine Output is the default mode with a compact run summary
  while automated steps run; Gate is the default mode at a pause; Outcome is the default mode
  after termination. No inactive pane reserves space.
- Automatic mode changes on run-state transitions preserve Engine Output scroll position, Runway
  selection, and the selected review-file token.
- Unit tests for parsing and projection; Textual tests for selection, scroll, and mode behavior.

### Out (later stories)

- Worktree Changes content, diff/rendered views, `$EDITOR` (S03).
- Structured `verdict_input` and interactive PTY gate decisions (S03/S04).
- Context index and Cockpit skill (S05).
- Catchable-signal cleanup and stale-read recovery beyond the current tolerant reads (S06).
- Agent-matched styling tokens (S07).

## 2. Verified engine contract (control flow)

Recorded from `src/specify_cli/workflows/` at `1.0.6.dev0`.

- Step types: `command`, `prompt`, `shell`, `init`, `slot`, `gate`, `if`, `switch`, `while`,
  `do-while`, `fan-out`, `fan-in`; `type` defaults to `command`.
- Control-flow payloads (all inline step arrays unless noted):
  - `if`: `condition` (string/boolean), `then`, optional `else`.
  - `switch`: `expression`, `cases` (mapping `case -> [steps]`), optional `default`.
  - `while` / `do-while`: `condition`, `steps`, optional `max_iterations` (default 10).
  - `fan-out`: `items` (expression resolving to a list), `step` (single template mapping),
    optional `max_concurrency`. Template steps are **not** overlay anchors.
  - `fan-in`: `wait_for` (list of prior step ids), optional `output` mapping.
- Declared step ids are unique and must not contain `:` (`engine.py:_validate_steps`).
- Runtime step ids are engine-generated when a step repeats:
  - loop body iterations: `"<loopId>:<bodyId>:<iteration>"` for iterations 2..N; the first pass
    runs under the plain `<bodyId>`.
  - fan-out items: `"<fanOutId>:<templateId>:<index>"`.
  - `if`/`switch` branches keep the composed plain ids.
- `state.json.step_results` is a mapping `step_id -> {type, integration, model, options, input,
  output, status, error}`. `status` is one of `pending/running/completed/failed/skipped/paused`.
  No timestamps or attempt counters are persisted.
- `state.json.current_step_index` counts **top-level** steps only; nested execution uses
  `step_offset=-1` and does not update the index. Projection must use `current_step_id` and
  `step_results`, never the index, to locate nested nodes.
- Gate results expose `output.message`, `output.options`, `output.choice`, `output.on_reject`.
  A gate is paused only while `state.status == "paused"` and the current step maps to it.
- `log.jsonl` is append-only. Every event carries an ISO-8601 UTC `timestamp`
  (`engine.py:append_log`). Relevant events: `step_started`, `step_completed` (with `status`),
  `step_failed`, `step_continue_on_error`, `workflow_aborted`. Timestamps are the **only**
  source of per-step durations and attempts.
- `RunStateReader` already tolerates missing directories, independently replaced
  `state.json`/`inputs.json`, and a partial trailing `log.jsonl` record. S02 must preserve that
  tolerance.

## 3. Locked decisions

1. **Graph source**: the static graph is built from the effective **base-plus-overlay** definition
   the session already resolved at launch, not from the run directory. `WorkflowDefinitionResolver`
   currently discards the composed step list after building top-level `StepSpec`s; S02 exposes the
   composed raw steps so the graph is available before the child writes `workflow.yml`. The
   persisted-definition contract check in `CockpitSession._check_contract` remains authoritative
   for detecting a mismatch and is unchanged.
2. **Static vs runtime separation**: `ControlFlowGraph` is pure and immutable, built once per
   definition; `GraphProjector` is pure and returns an immutable projection per snapshot. No
   Textual import in either.
3. **Tolerant mapping**: a runtime step id maps to a declared node by splitting on `:` and taking
   the segment that matches a declared id (preferring the deepest declared match). Unmatched ids
   are ignored, never fatal. Declared ids cannot contain `:`, so this is unambiguous for all
   engine naming schemes.
4. **Attempts and durations** come from an incremental `log.jsonl` reader (`RunLogAggregator`),
   not from `state.json` and not from a fixed tail. It tracks a byte offset plus a partial-record
   buffer, merges new valid records into bounded per-declared-id aggregates, tolerates a partial
   trailing record, and resets on file replacement (inode change or truncation).
5. **Focus is a mode machine**, not fixed regions. Modes: `OUTPUT` (default while
   initializing/running), `GATE` (default while paused), `OUTCOME` (default when terminal), plus
   manually reachable `STATE` and `OUTPUT`. The active mode fills the canvas; inactive panes are
   `display=False` and reserve no space. A user mode choice is held until the next run-state
   transition, then cleared so the new default applies.
6. **Preservation**: the view model owns `selected_node_id`, `selected_review_path`,
   `output_at_tail`, and `output_scroll_y`. Refresh re-applies them; the RichLog is only cleared
   on truncation/reset. Auto-scroll happens only while `output_at_tail` is true.
7. **Runway replaces `StepRail`**: `build_step_rows` and `StepRail` are removed. Rendering logic
   lives in a pure `render_runway(...)` helper returning rows; the `Runway` widget maps rows to
   Textual options and owns focus/scroll. Below 112 columns Runway becomes the four-row scrollable
   strip above Focus, matching `UI_DESIGN.md:102-104`.
8. **S02 does not implement Changes or structured gates.** The Gate mode reuses S01's read-only
   paused surface plus the Runway highlight; `selected_review_path` is carried but has no content
   until S03.

## 4. Module layout

Additions to the S01 tree:

```
workflow_cockpit/
  services/
    graph.py             ControlFlowGraph, GraphNode, GraphEdge, WorkflowDefinitionParser
    projection.py        GraphProjector, GraphProjection, NodeState
    log_aggregator.py    RunLogAggregator, StepTiming
  ui/
    view_model.py        render_runway, default_focus_mode (extended)
    widgets/runway.py    Runway widget (strip + full)
  ui/screens/cockpit.py  Focus mode machine wiring
```

`WorkflowDefinition` gains an `effective_steps: tuple[dict[str, Any], ...]` field (the composed
top-level raw step mappings) populated by `WorkflowDefinitionResolver.resolve`. No existing field
changes meaning.

## 5. Phases

### Phase 1 - Static control-flow graph

- `WorkflowDefinitionParser.parse(effective_steps) -> ControlFlowGraph`. Recurse through
  `then`/`else`, `cases`/`default`, `steps`, and `step` (fan-out template). Non-list or malformed
  branches degrade to no children; unknown step types become leaf nodes. Never raise on an
  unvalidated definition.
- `GraphNode`: `id`, `label`, `type`, `gate`, `options`, `parent_id`, `branch` (then/else/case/default/
  body/template), `depth`, `order`, `is_template`, `max_iterations`.
- `GraphEdge`: `source`, `target`, `kind` (`sequence|branch|loop|join|fanout`), `label`.
- Edges: sequence within a list; container -> branch heads; loop body tail -> loop node; fan-in ->
  each `wait_for` target; fan-out -> template.
- Expose `nodes` in declared render order, `by_id`, `roots`, and `declared_ids`.
- Tests (unit): linear, if/then/else, if without else, switch cases + default, while, do-while,
  fan-out/fan-in, nested control flow, gate metadata, a workflow with an overlay-inserted step,
  unknown/`slot` types, malformed branch lists, and duplicate-free node order.

### Phase 2 - Runtime projection

- `RunLogAggregator`: incremental read of `log.jsonl`; maintain per-declared-id `StepTiming`
  (`attempts`, `last_started`, `last_finished`, `status`). Reset on inode change, size shrink, or
  replacement. Tolerate a partial trailing record by buffering the incomplete line.
- `GraphProjector.project(graph, run_state, timing, *, now) -> GraphProjection`:
  - map `state.current_step_id` and each `step_results` key to declared ids via the segment rule;
  - node status: `paused` only for the mapped current gate while `state.status == "paused"`;
    `running` for the mapped current step while active; `completed`/`skipped`/`failed` from
    `step_results[id].status`; `aborted` for the mapped terminal step when `state.status ==
    "aborted"`; everything else `pending`;
  - active path: root-to-current chain over declared edges, plus nodes with recorded results;
  - attempts and completed/live duration per node from `StepTiming`; live duration = `now -
    last_started`; completed duration = `last_finished - last_started`;
  - parallel fan-out supports multiple simultaneously running nodes.
- Add `graph_projection: GraphProjection | None` to `RunSnapshot`; build it in
  `CockpitSession.snapshot` (parse graph once at `select`, project each tick). Projection work is
  bounded and CPU-only, so it stays on the polling path with the rest of snapshot assembly.
- Tests (unit): each status mapping; first loop iteration vs namespaced iterations; fan-out index
  ids; unmatched ids ignored; multiple running fan-out nodes; attempts from repeated
  `step_started`; completed and live durations from timestamps; partial trailing record;
  append-only growth; file replacement reset; `state` present but `log` missing.

### Phase 3 - Runway

- `render_runway(graph, projection, selected_id, width) -> list[RunwayRow]` (pure) produces
  status symbol, indentation/connectors, label, branch annotation, gate word, `#n` attempt, and
  duration; long labels truncate in the middle. Active path uses `signal`; inactive alternatives
  are dim; gate uses `hold`.
- `Runway` widget: keyboard navigation (`j`/`k`, arrows), `Tab`/`Shift+Tab` between Runway and
  Focus, selection on `enter`/`space` that updates Focus without changing the run. Preserve
  `selected_node_id` across refreshes; keep the current node within the middle third when
  following. In strip mode preserve the horizontal/vertical scroll offset.
- `CockpitScreen` replaces `#steps`/`StepRail` with `Runway`; `build_step_rows` and `StepRail` are
  deleted. The low-fidelity `01 / WORKFLOW` summary is folded into the compact run summary.
- Tests (Textual `App.run_test()`): graph renders for a branching fixture; selection survives a
  refresh and a state change; current node highlighted; narrow width enters strip mode and remains
  scrollable; selecting a node updates Focus without mutating run state.

### Phase 4 - Focus canvas

- `default_focus_mode(snapshot) -> str` returns `output`, `gate`, or `outcome` from run state.
  Manual `s`/`l`/`g` set a held mode; any run-state transition clears the hold.
- Rework `CockpitScreen` Focus area: only the active mode is displayed; the compact run summary
  (`NOW <step> attempt <n> <elapsed>  NEXT <next>`) heads Output mode. Gate mode keeps S01's
  read-only pause text; Outcome mode keeps S01's outcome surface.
- `CockpitViewModel` carries `selected_node_id`, `selected_review_path`, `output_at_tail`, and
  `output_scroll_y`; refresh restores them. Engine Output appends without clearing and only
  auto-scrolls when at tail. Switching modes never drops the RichLog contents.
- Tests (Textual): running defaults to Output; pause defaults to Gate; terminal defaults to
  Outcome; manual mode survives same-state refreshes but is superseded by a transition; output
  scroll position survives Gate<->Output switches; `selected_review_path` survives a transition;
  no inactive pane occupies height (layout assertions).

### Phase 5 - Integration and end-to-end

- Contract fixture workflows exercise the parser against realistic definitions: linear
  `lean-flow`, an `if`/`switch` branch, a `while` loop, and a `fan-out`/`fan-in`. Extend
  `tests/fixtures/` and reuse the pinned real-`specify` harness where a run is needed.
- Assert exact run identity and that graph status tracks the same `state.json` the header uses.
- Run the full unit + Textual + contract + PTY suites; `ruff` clean.

## 6. Acceptance mapping

| S02 criterion | Phase / component |
|---|---|
| Complete declared graph incl. branches, loops, gates, overlays | 1 - `WorkflowDefinitionParser`, `ControlFlowGraph` |
| Runtime status incl. pending/running/paused/completed/failed/skipped/aborted | 2 - `GraphProjector` |
| Attempts and completed/live per-step durations | 2 - `RunLogAggregator`, `GraphProjector` |
| Branch changes update; fixed baseline unchanged | 2/4 - `CockpitSession` unchanged baseline; Runway refresh |
| Selection, focus, scroll survive refreshes | 3/4 - `Runway`, view model |
| Graph derived generically from installed definition | 1 - parser (no workflow hardcoding) |
| Focus state-driven; Engine Output default while running; no empty reserved panes | 4 - mode machine |
| Automatic mode changes preserve output scroll and selected review file | 4 - preservation state |
| Unit tests: parsing, branches, loops, overlays, attempts, projection | 1/2 |
| Textual tests: selection and layout through state changes | 3/4 |

## 7. Deferred / assumptions

- Review-file **content** and structured gate decisions remain S03/S04; S02 only carries the
  selection token so S03 inherits stable preservation.
- The engine persists no step timestamps; durations are best-effort from `log.jsonl`. Missing log
  timestamps render as blank rather than inferring a state model from output.
- Deeply nested steps inside a loop body keep plain ids after the first level, so their attempts
  may undercount; the declared node always resolves correctly. This is accepted as engine
  behavior, not compensated for.
- `state.json` remains authoritative for status; projection never writes engine files.
- No new runtime dependency is required.

## 8. Risks

- Runtime id namespacing is versioned engine behavior. The segment-based mapping is deliberately
  tolerant so a new namespacing scheme degrades to "unmatched, ignored" instead of a crash.
- Long or high-frequency logs make whole-file rescans expensive; the incremental aggregator with a
  byte offset and bounded per-id aggregates is required, not optional.
- Automatic focus switching can fight a user who is reading. The held-mode-then-clear rule bounds
  this to a single transition.
- `current_step_index` is top-level only; any projection or scroll logic that relies on it for
  nested steps is wrong and must use `current_step_id`.
- Overlay-composed graphs depend on resolver exposure of the composed steps; a regression there
  would silently show the base graph only.
