# UI Design: Flight Recorder

| Field | Value |
|---|---|
| Status | Revised interactive design draft; see prototype/README.md for coverage |
| Surface | Standalone Textual TUI |
| Direction | Flight recorder; warm graphite, quiet hierarchy, evidence-first review |
| Layout | One adaptive application with integrated Engine Output |

## 1. Design idea

The Cockpit should feel like an instrument used during an operation, not a collection of
dashboard cards. Its memorable element is the **runway**: a vertical workflow graph whose line
connects the workflow definition to live execution state.

The interface is dark, sharp-edged, and quiet. Color is scarce and meaningful. Information is
layered by operational importance:

1. What state is the run in?
2. Where is it in the workflow?
3. Does the user need to act?
4. What changed?
5. What did the engine print?
6. Where can an external agent find context?

The Engine Output view is the raw flight recorder. The surrounding Cockpit is the interpreted
instrument panel. Both live in one Textual application.

## 2. Visual language

### Palette

| Token | Hex | Use |
|---|---|---|
| `ink` | `#101312` | Main background |
| `deck` | `#171C19` | Reading and working surface |
| `raised` | `#202821` | Subtle selection and document toolbar |
| `rail` | `#303B34` | Rules and inactive graph edges |
| `fog` | `#94A399` | Secondary text |
| `paper` | `#E5E9DF` | Primary text |
| `signal` | `#9CD6AD` | Running, selected path, successful action |
| `hold` | `#E8BD79` | Paused gate, warning, required attention |
| `fault` | `#EF9387` | Failure, abort, destructive confirmation |
| `cold` | `#A1BFCE` | Focus, links, context paths, neutral selection |

Color never carries meaning alone. Every colored state also has a word and symbol.

### Styling templates

The ten roles above (`ink`, `deck`, `raised`, `rail`, `fog`, `paper`, `signal`, `hold`,
`fault`, `cold`) form the required token set. Three optional accent roles round out the
palette: `selection`, `focus`, and `hover` (the selected-row, focused-control, and
hovered-control backgrounds). A template may omit accents and inherit the neutral
defaults.

A template is a data-only JSON definition; adding one requires no application code:

```json
{
  "name": "opencode",
  "label": "OpenCode",
  "aliases": ["opencode"],
  "tokens": { "ink": "#0E0F13", "deck": "#15171D", "raised": "#1D2028", "rail": "#2C313B",
              "fog": "#939AA6", "paper": "#E7EAF0", "signal": "#7CE0B0", "hold": "#E8BD79",
              "fault": "#F08A90", "cold": "#8FB8E0" },
  "accents": { "selection": "#1E3038", "focus": "#25404A", "hover": "#233A43" }
}
```

- A definition missing any required token is rejected as a whole; the neutral `cockpit`
  default is used and the rejection is logged with the offending name and missing tokens.
  Extra tokens are ignored for validation.
- Names and aliases match case-insensitively with spaces, underscores, and dashes
  collapsed: `"GitHub Copilot"`, `"github-copilot"`, and `"copilot"` all resolve to one
  template.
- Discovery precedence is fixed: built-in packaged templates first, then project-local
  `.specify/cockpit/templates/*.json`. Within a directory files are read in sorted
  filename order and the first definition for a name wins. The neutral `cockpit`
  template can never be shadowed.
- On launch the active template is the project's `default_integration` from
  `.specify/integration.json`. The `--style NAME` launch option overrides it. An unknown,
  missing, unreadable, or malformed input falls back to `cockpit` with a non-fatal
  notice; the run is never blocked. The resolved name is shown in the header.

Templates affect only colors and accent styling. Layout, wording, controls, and behavior
are identical under every template, and color never carries meaning without its symbol
and word.

### Typography

Textual uses the terminal's monospace font. Hierarchy comes from weight, case, spacing, and
alignment.

- Product mark and major state: bold uppercase.
- Workflow and step names: original case, semibold where available.
- Metadata labels: uppercase, dim, fixed-width columns.
- IDs, paths, commands, commits, and durations: monospace normal weight.
- Critical symbols remain ASCII.

### Status grammar

| Symbol | State | Color |
|---|---|---|
| `[ ]` | Pending | `fog` |
| `[>]` | Running | `signal` |
| `[!]` | Waiting at gate | `hold` |
| `[x]` | Completed | `signal` |
| `[-]` | Skipped | `fog` |
| `[X]` | Failed | `fault` |
| `[/]` | Aborted | `fault` |

### Shape and spacing

- Use square corners, single-cell rules, and open whitespace.
- Do not wrap every region in a box. One outer frame and structural rules are enough.
- Reserve one blank row between operational groups.
- Selected rows use a solid left marker and subtle background, not a bright border.
- Avoid gradients, rainbow syntax, oversized ASCII logos, and constant animation.

## 3. Adaptive application frame

Wide layout:

```text
+------------------------------------------------------------------------------+
| WORKFLOW COCKPIT   RUNNING       feature/search                     04:12  |
| workflow: feature-delivery       run: 01J...                       [?] HELP  |
+----------------------------+-------------------------------------------------+
| RUNWAY                     | FOCUS                                           |
| workflow graph             | current step, gate, changes, or outcome         |
|                            |                                                 |
|                            +-------------------------------------------------+
|                            | ENGINE OUTPUT                         LIVE [>]   |
|                            | read-only RichLog                               |
+----------------------------+-------------------------------------------------+
| [s] state   [c] files   [l] output   [g] gate   [x] abort        [q] exit |
+------------------------------------------------------------------------------+
```

- At 112 columns and wider, Runway occupies 29 columns; Focus receives the rest.
- Engine Output is a collapsible section within Focus, not another terminal or process pane.
- Focus may use all available height when output is collapsed.
- At 88-111 columns, Runway becomes a four-row, scrollable strip above Focus.
- Below the validated minimum, content is replaced by a resize instruction showing current
  and required dimensions.

The revised prototype uses a minimum of **88 x 36**, a comfortable size of
**120 x 40**, and a reference composition of **144 x 46**. Five sizes have been
checked using Textual's Linux headless renderer. Physical macOS/WSL terminal
validation remains open. Compact layouts retain the gate question, decisions,
context path and at least five document rows in the default gate fixture.

Focus navigation uses a quiet tab rail: Overview, Files, and Gate review only
while paused. A warm amber question strip introduces the gate; a separate pinned
decision row closes it. File basenames lead the index, parent paths sit underneath,
and the full selected path appears above the document. All declared gate choices
receive equal visual weight; none is promoted merely because it is called approve.

### Header rail

The header always shows:

- product name;
- state word and symbol;
- current branch;
- total elapsed time;
- workflow name and abbreviated run ID.

Branch changes update the field without moving the layout.

### Runway

Runway is a scrollable control-flow graph. It favors vertical flow with short horizontal
branches and compact loop annotations. The current node stays within the middle third of the
viewport when possible.

```text
  [x] prepare                         00:04
   |
   +-- condition: has_spec
   |    [x] analyze                   00:31
   |     |
   |    [!] review_spec              gate
   |     `-- retry --------------------^  #2
   |
   `-- [ ] implement
        [ ] verify
        [ ] finish
```

- Active path uses `signal`; inactive alternatives are dim.
- The current node is emphasized within the active path with bold underline.
- A gate uses `hold` and the word `gate`.
- Attempts appear as `#2`, `#3`, and so on.
- Runway is display only; it has no cursor or selection.
- Long labels truncate in the middle; Focus shows the full value.

### Focus

Focus is one large canvas, not a grid of cards. It switches among:

- State: current step and immediate workflow context.
- Files: feature-file index plus current content.
- Gate: evidence and decision surface.
- Output: Engine Output as a full-height working view.
- Outcome: success, failure, or abort summary.

The canvas is state-driven and never reserves space for a pane that has no useful content:

| Run state | Default Focus mode | Engine Output |
|---|---|---|
| initializing / running | Output, with a compact State summary header | Full canvas, live tail and auto-scroll |
| paused at a gate | Gate | Collapsed to a short diagnostic tail; `l` expands |
| completed / failed / aborted | Outcome | Collapsed to a diagnostic tail; `l` expands |

- The review surface is never permanently visible during automated steps, and Output is never an
  empty region at a gate.
- State, Files, and Gate stay directly reachable with `s`, `c`, and `g`; Output stays reachable
  with `l` in every state.
- Automatic mode changes on run-state transitions preserve Output scroll position and the selected
  review file.

### Command rail

The bottom rail shows only actions valid in the current state. Disabled actions disappear.
Destructive actions are always labeled, never icon-only.

## 4. Launch screen

The launch flow is a focused sequence before engine execution.

```text
+------------------------------------------------------------------------------+
| WORKFLOW COCKPIT                                              PROJECT READY  |
| /work/acme/search-service                                                    |
+------------------------------------------------------------------------------+
| SELECT WORKFLOW                                                             |
|                                                                              |
| > feature-delivery       8 steps   2 gates   Build a feature from spec       |
|   release-check          5 steps   1 gate    Validate a release candidate    |
|   dependency-refresh     4 steps   no gates  Refresh locked dependencies     |
|                                                                              |
| ---------------------------------------------------------------------------  |
| feature-delivery                                                            |
| prepare -> analyze -> review_spec -> implement -> verify -> finish           |
|                                                                              |
| [enter] configure                                             [q] quit       |
+------------------------------------------------------------------------------+
```

Configuration replaces the description with workflow summary and input form:

```text
  FEATURE DELIVERY
  8 steps / 2 gates / shell execution

  feature description *  [Add indexed search to the catalog________________]
  test profile            [standard v]
  publish branch          [x]

  BRANCH main                  WORKTREE clean

  [enter] START RUN                                      [esc] workflows
```

- Required fields use `*` and inline validation.
- Start is singular and visually strong in `signal`.
- A dirty worktree inserts an amber warning strip above Start and requires one confirmation.
- Preflight failures use the same shell with a compact checklist and exact repair commands.

## 5. Running state

During automated work, Output is the default Focus mode and uses the full canvas. A compact
State summary keeps current intent visible; `s` shows the full State mode:

```text
+------------------------------------------------------------------------------+
| OUTPUT / RUNNING                                                  [s] state  |
| NOW implement  attempt 1  00:47  NEXT verify -> review_implementation        |
| WORKTREE 7 files  +184 -29                                                   |
+------------------------------------------------------------------------------+
| ENGINE OUTPUT                                                     LIVE [>]   |
| $ specify workflow run feature-delivery ...                                 |
| Running step implement ...                                                  |
| Building search index                                                       |
| ...                                                                          |
+------------------------------------------------------------------------------+
| [s] state   [c] files   [l] output   [x] abort                  [q] exit |
+------------------------------------------------------------------------------+
```

Engine Output behavior:

- Read-only `RichLog` fed from the managed process PTY.
- Auto-scroll while at the tail; scrolling upward automatically pauses it.
- `End` returns to the live tail; `l` toggles the drawer.
- ANSI and terminal control sequences are stripped.
- Output history is bounded and old lines are discarded with an explicit truncation marker.

The elapsed-time display updates without decorative animation. A compact `LoadingIndicator`
trails the Output heading while the engine process is running so a silent output gap still reads as
activity; it is absent while paused or stopped.

## 6. Gate review

When paused, Gate becomes the default Focus mode. It combines the decision with evidence rather
than showing a detached modal. Engine Output collapses to a short tail and can be expanded with
`l`.

```text
| GATE / REVIEW SPEC                                             WAITING [!]   |
| Is the specification complete enough to plan?                               |
|                                                                            |
| FEATURE FILES  4 files in specs/042-search                                 |
| specs/042-search/spec.md            | # Feature Specification              |
| specs/042-search/checklist.md       | ## Acceptance scenarios              |
| specs/042-search/plan.md            | ## Implementation plan               |
| specs/042-search/tasks.md           | ## Tasks                             |
|                                     |                                      |
| CONTEXT  .specify/workflows/runs/current_run                              |
|                                                                            |
| DECIDE  [1] approve   [2] retry   [3] skip                 [x] abort run   |
+------------------------------------------------------------------------------+
| ENGINE OUTPUT / LAST 3 LINES                                      [l] open  |
+------------------------------------------------------------------------------+
```

- Gate message is never silently truncated.
- The file list shows project-relative paths; there is no change status marker.
- The file list remains narrow; document content receives most horizontal space.
- Text files show their current content; Markdown files render as formatted documents with the
  same bounded preview and `load full` action.
- Binary files show path and size.
- Large files show preview limits and a deliberate `load full` action.
- The context path is selectable terminal text; clipboard integration remains terminal-owned.
- `o` suspends Textual and opens the selected existing non-binary file in `$EDITOR`. Cockpit
  restores the selected path afterward.
- Gate choices are numbered dynamically and preserve workflow labels and order.

### Decision confirmation

Confirmation is a narrow sheet over Focus:

```text
| CONFIRM GATE DECISION                                                       |
|                                                                            |
| approve                                                                    |
| The workflow will continue to: implement                                   |
|                                                                            |
| [enter] CONFIRM                                           [esc] go back    |
```

Abort uses `fault`; ordinary workflow choices use `hold`.

### Unverified PTY submission

```text
| GATE INPUT SENT, STATE NOT ADVANCED                                         |
| The choice was written once. Cockpit will not write it again.               |
| Expand Engine Output to inspect the prompt state.                           |
|                                                                            |
| [l] engine output                                           [x] abort run  |
```

## 7. Files mode

Files mode is available whenever useful; editor actions appear only at a paused gate.

- File order: lexical project-relative path.
- Show file count and the declared feature directory.
- Text files show their current content; Markdown files render formatted; there is no diff view.
- `/` filters feature paths.
- Empty state: `No feature files to review yet`.
- Undeclared feature directory state: a persistent error with the `.specify/feature.json` guidance.

## 8. Outcomes

### Success

```text
| RUN COMPLETE [x]                                                           |
|                                                                            |
| feature-delivery                                              06:42         |
| 8 completed   1 skipped   2 gates                                          |
| Feature Files  11 files in specs/042-search                                |
|                                                                            |
| Branch  feature/indexed-search                                             |
|                                                                            |
| [c] review files   [l] engine output                [enter] close         |
```

### Failure

```text
| RUN FAILED [X]                                                             |
|                                                                            |
| verify / attempt 1                                           after 00:18   |
| Test command exited with status 1.                                         |
|                                                                            |
| Engine Output expanded below with the failure tail in view.                |
|                                                                            |
| [c] review files   [l] engine output              [enter] close         |
```

### Abort

A confirmed Abort shows a blocking `ABORTING` sheet while the engine process group is interrupted
and reaped, then exits Textual directly. Success and failure outcomes still await acknowledgment via
Enter.

## 9. Keyboard model

| Key | Action |
|---|---|
| `j` / `k` or arrows | Move within focused graph/list/log |
| `Tab` / `Shift+Tab` | Move between Runway and Focus |
| `s` | State mode |
| `c` | Files mode |
| `l` | Toggle the Engine Output drawer (expand/collapse) |
| `End` | Return Engine Output to the live tail |
| `g` | Gate mode when paused |
| `o` | Suspend Textual and open `$EDITOR` when allowed |
| `/` | Filter the current list |
| `x` | Begin confirmed Abort |
| `?` | Contextual help overlay |
| `q` | Exit; while active this enters Abort confirmation |

Gate shortcuts are generated as `1` through `9`. Gates with more choices use selection plus
Enter rather than ambiguous multi-digit shortcuts.

## 10. Feedback and errors

- Transient success feedback appears on the command rail for at most two seconds.
- Recoverable errors occupy a persistent strip above the command rail until dismissed.
- Errors state the failed operation, authoritative run state, and next available action.
- Background read errors preserve the last good graph and add a `STALE` marker.
- Focus, file selection, output scroll, and document scroll survive background refreshes.
- Unexpected child-process exit expands Engine Output and keeps the final lines visible.

## 11. Accessibility and degradation

- All meaning is available without color through symbols and labels.
- Focus uses both a left marker and reverse/background contrast.
- Use terminal-compatible semantic colors; symbols and labels carry all state meaning.
- Long paths use middle truncation.
- Mouse support is optional; every operation works by keyboard.

## 12. Prototype checkpoints

1. A branching graph remains legible at the minimum width.
2. Gate message, file list, meaningful content, context path, and decisions fit without clipping.
3. The state-driven canvas gives Output the full area while running and the review surface the
   full area at a gate, with no empty reserved region.
4. Expanded output supports long workflow output and strips controls without UI corruption.
5. Responsive stacking behaves correctly on Linux, macOS, and WSL terminals.
6. Refreshes preserve the current-node highlight, file selection, document scroll, and output-tail mode.
