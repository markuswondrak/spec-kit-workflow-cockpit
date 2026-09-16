# Flight Recorder / Design Preview

An interactive Textual prototype, not the product implementation. All run state,
file content, statistics and output are fixtures. No engine starts, no commands
are submitted, and no worktree files are read or modified.

## Run

From the repository root, using the existing prototype environment:

```sh
workflow_ui/prototype/.venv/bin/python workflow_ui/prototype/app.py
```

Open the principal design surface directly:

```sh
workflow_ui/prototype/.venv/bin/python workflow_ui/prototype/app.py --scene gate
```

Other scene arguments: `running`, `complete`, `failed`, `launch`.
For a new environment, install `workflow_ui/prototype/requirements.txt` first.

## Inspect

Recommended terminal: **144 columns x 46 rows**. Comfortable: **120 x 40**.
Minimum: **88 x 36**. Below 112 columns the workflow rail stacks above the
review surface. Below the minimum, a blocking resize instruction preserves the
current screen. These dimensions are validated with Textual's headless renderer
on Linux, not yet on physical macOS or WSL terminals.

| Key | Action |
| --- | --- |
| `Tab` / `Shift+Tab` | Move focus |
| `j` / `k`, arrows | Navigate workflow or changed files |
| `Enter` on a step | Inspect without advancing the run |
| `s` / `c` / `g` | Overview / Changes / Gate review |
| `d` / `r` | Diff / Read file |
| `/`, then `Esc` | Filter paths / clear filter |
| `l` / `e` | Expand output and jump to tail / collapse output |
| `1` / `2` / `3` | Confirm a declared fixture choice |
| `x` / `q` | Confirm abort while active; close after outcome |
| `?` | Field guide |
| `F2` / `F3` / `F4` / `F5` | Load running / gate / complete / failure fixture |

`End` retains the focused widget's normal meaning: last item in a list, end in
a document or log. `l` always returns output to its tail.

The preview strip is not a production command rail. Fixture shortcuts never
represent real engine operations. Confirmation loads the target-step fixture;
it does not emulate a complete execution history. `$EDITOR` is explicitly
simulated. Counts describe illustrative full files; visible content is labeled
as a fixture excerpt.

## Design Direction

The existing industrial direction is refined rather than replaced with dashboard
cards. Warm graphite surfaces, off-white text, sage execution signals, amber
decisions and muted blue context links keep long sessions calm.

The three information layers are deliberately unequal:

1. **Workflow:** a narrow, connected status rail. It locates the work, not the UI.
2. **Focus:** one workspace. At a gate the actual question leads, followed by
   a narrow file index and a generous reading surface. The context path and
   decisions remain outside the document scroller.
3. **Engine Output:** supporting evidence, normally a short tail. Failure expands
   it; it never masquerades as authoritative run state.

Gate options share the same amber treatment. An `approve` fixture is not given a
green default-action advantage over workflow-defined alternatives. Abort lives
separately on the session rail. Every decision has a confirmation sheet with its
declared next step.

Selection starts as a two-column workflow brief. Configuration replaces the
brief in place rather than opening another disconnected screen. Required input
validation is inline, and starting is an explicit button action.

## Boundaries Before Implementation

The PRD remains authoritative. This preview does not implement preflight,
dirty-worktree confirmation, arbitrary schema forms, full branching graph
parsing, binary and large-file handling, empty-change gates, stale-state errors,
unverified PTY submission, output normalization, polling, or real editor access.
Those states need follow-up interaction designs and engine integration tests;
the redesigned visual frame is not evidence that they are complete.

The product-level interaction requirements now live in
[`docs/architecture/`](../../docs/architecture/README.md) (see
[§8 Crosscutting Concepts](../../docs/architecture/08-crosscutting-concepts.md)). Prototype-only
navigation is documented here and must not leak into the production lifecycle.

## Verify

From `workflow_ui/prototype`:

```sh
.venv/bin/python -m unittest -v
```

Tests cover five terminal sizes, scene consistency, minimum document space,
decisions and cancellation, abort, list navigation, file filtering, diff/read
switching, workflow selection, required input, help and the resize guard.

Files are separated by UI domain: `app.py` owns the cockpit, `launch.py` launch
and configuration, `review.py` evidence, `components.py` shared surfaces,
`styles.tcss` visual tokens and layout, and `mock_data.py` fixtures.
