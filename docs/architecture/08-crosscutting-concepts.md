# 8. Crosscutting Concepts

| Field | Value |
|---|---|
| arc42 | 8. Crosscutting Concepts |
| Tier | 2 |

This is the **gold-standard reference** for the codebase's conventions. Every change must follow
these patterns. Each concept shows a correct excerpt and an explicit incorrect contrast.

## Services without Textual imports

Domain services must be importable and testable without a running app. Textual imports belong only
in `workflow_cockpit/ui/`.

Correct (`workflow_cockpit/services/log_aggregator.py`):

```python
from __future__ import annotations

import json
import threading
from pathlib import Path

from .graph import resolve_declared_id


class RunLogAggregator:
    def __init__(self, declared_ids: frozenset[str], *, max_read_bytes: int = MAX_READ_BYTES) -> None:
        self._declared_ids = declared_ids
        self._max_read_bytes = max_read_bytes
        self._lock = threading.RLock()
```

Incorrect:

```python
from textual.reactive import reactive   # NO: pulls the UI framework into a service

class RunLogAggregator:
    progress = reactive(0)              # NO: rendering state does not belong here
```

A service that needs to notify the UI publishes a plain message the UI subscribes to; it never
imports a widget or app.

## Render-path isolation

Blocking work runs in a Textual worker thread and hand results back through messages. The render
path only reads already-computed state.

Correct (`workflow_cockpit/ui/screens/run_poll_mixin.py:48`):

```python
@work(thread=True, group="poll", exclusive=True)
def _produce_snapshot(self) -> None:
    snapshot = self._loop.produce()
    self.post_message(SnapshotPublished(snapshot, self._loop.last_error))

def _snapshot_now(self) -> RunSnapshot:
    # Never create a snapshot from the UI thread.
    return self._snapshot or RunSnapshot(run_id="")
```

Incorrect:

```python
def _apply_snapshot(self) -> None:
    snapshot = self.session.snapshot()   # NO: blocking read on the render path
    self._paint(snapshot)
```

The same rule covers Git (`group="branch"`) and file reads (`group="review"`,
`group="review-document"`), all declared `exclusive` so only one runs per group.

## Bounded reads

Every read that could grow without limit is bounded per call. `log.jsonl` is tailed, output is
capped, and large files are previewed.

Correct (`workflow_cockpit/services/log_aggregator.py`):

```python
#: Bytes read from the log per ``update`` so a growing file cannot stall a poll.
MAX_READ_BYTES = 256 * 1024

with path.open("rb") as handle:
    handle.seek(self._offset)
    chunk = handle.read(self._max_read_bytes)
```

Incorrect:

```python
text = path.read_text()          # NO: a multi-GB file blocks the worker and OOMs the app
events = text.splitlines()
```

`RunStateReader` keeps a bounded `log_tail` (default 80 records) and `EngineOutput` discards old
lines with an explicit truncation marker. `log.jsonl` remains the complete source on disk.

`RunCatalog` bounds a whole discovery pass: a maximum number of run directories plus per-file caps
for `state.json`, `workflow.yml`, and the `current_run` pointer, each read with a before/after
signature check so an in-progress write is reported unusable rather than read torn. Discovery and
adoption preparation run in a `@work(thread=True)` worker, never on the render path.

## Immutable snapshots

State crosses the presentation boundary as frozen, self-contained values. No shared mutable model
is handed to widgets.

Correct (`workflow_cockpit/services/snapshot.py`):

```python
@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    output_tail: tuple[str, ...] = ()
```

Incorrect:

```python
class RunSnapshot:              # NO: widgets mutate shared state during refresh
    def __init__(self):
        self.steps = []
        self.output_tail = []
```

The `CockpitViewModel` maps a snapshot to renderable state while preserving selection, focus, and
scroll across refreshes.

## Output normalization

Engine output is decoded tolerantly and stripped of terminal control before display. Cockpit does
not emulate a terminal.

Correct (`workflow_cockpit/engine/normalizer.py`): decode with replacement, normalize carriage
returns, strip ANSI/control sequences, and retain complete lines plus the current partial line.

Incorrect:

```python
self.log.write(raw_bytes)       # NO: leaks ANSI/control sequences into RichLog
```

## Tolerance and recovery

Persisted files are written independently and may be missing, partial, or replaced atomically.
Readers skip unchanged content, detect replacement, and keep the last good value.

Correct:

```python
try:
    stat = path.stat()
except OSError:
    return dict(self._timings)              # keep last good timings
if self._signature != (stat.st_ino, stat.st_dev) or stat.st_size < self._offset:
    self._reset((stat.st_ino, stat.st_dev))  # atomic replacement detected
```

Incorrect:

```python
data = json.loads(path.read_text())     # NO: one partial write crashes the poll
self._timings = {}
```

Recoverable failures occupy one persistent error strip that states the failed operation,
authoritative run state, and the next available action. Background read failures add a `STALE`
marker rather than clearing good data.

## Theme and palette

Styling is a pure-data layer resolved once at startup, before the app is constructed. It imports
no Textual and touches no session, supervisor, gate, or run-state code, so resolution cannot block
or alter a run. A template that is missing any of the ten required roles is rejected as a whole and
`cockpit` is used with a non-fatal notice.

Correct: templates change colors only; layout, wording, controls, and behavior are identical under
every template, and color never carries meaning without a symbol and word.

Incorrect:

```python
if template.name == "opencode":   # NO: behavior must not branch on the active template
    self.show_extra_gate_button()
```

## Accessibility

- Every state has a symbol and a word; color is redundant.
- All controls are keyboard reachable and help is available in-app (`?`).
- Long paths use middle truncation; the full value is reachable in Focus.
- Critical symbols remain ASCII.

## Testing seams

| Layer | Test type |
|---|---|
| Registry, definition resolution, graph parsing, projection, feature files, compatibility, deciders | Unit tests (`tests/unit/`) |
| Run discovery, ownership claims, launch-copy parsing, adoption binding (no TUI, no engine internals) | Unit tests (`tests/unit/`) |
| Screens, focus, modes, confirmation, outcomes, styling | Textual `App.run_test()` (`tests/textual/`) |
| Executable/project/run identity, lifecycle, output, gate submission, cleanup, signals | Contract and PTY integration (`tests/contract/`, `tests/pty/`) |
| Documentation structure, links, format, budget, ADRs | `tests/docs/` |

Because services have no Textual imports, most behavior is testable without a running app. The
documentation tests enforce that this set stays navigable, linked, image-free, and within budget.
