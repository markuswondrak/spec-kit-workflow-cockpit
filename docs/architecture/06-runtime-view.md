# 6. Runtime View

| Field | Value |
|---|---|
| arc42 | 6. Runtime View |
| Tier | 2 |

## Launch and start

```mermaid
sequenceDiagram
    participant U as User
    participant C as cockpit
    participant S as specify
    participant R as run files
    U->>C: workflow-cockpit [--project PATH]
    C->>C: discover root, preflight, compatibility
    C->>C: list workflows, present inputs
    U->>C: Start
    C->>C: generate run ID, verify run dir absent
    C->>S: workflow run <id> -i name=value (no shell)
    C->>R: write current_run context index
    S->>R: write state.json / inputs.json / log.jsonl
```

A dirty worktree warns but does not block Start. The run ID is allocated before spawn and passed
through `SPECKIT_WORKFLOW_RUN_ID`; directory scanning never claims ownership.

## Observe

```mermaid
sequenceDiagram
    participant P as PollingLoop (250 ms)
    participant R as RunStateReader
    participant G as GraphProjector
    participant V as CockpitViewModel
    participant W as widgets
    P->>R: read state/inputs/log (skip unchanged)
    R-->>P: tolerant RunStateData
    P->>G: overlay runtime on declared graph
    G-->>P: projection
    P->>V: publish immutable RunSnapshot
    V->>W: update without stealing focus or scroll
```

`PtySession` streams output through `OutputNormalizer` into a bounded `RichLog`. `log.jsonl` remains
the complete source; output is diagnostic, not a second state model.

## Gate decision

```mermaid
flowchart TB
    gate{Declared gate} -->|has verdict_input| structured[resume -i name=choice --json]
    gate -->|otherwise| pty[write selected choice once to managed PTY]
    structured --> persisted[(persisted state authoritative)]
    pty --> persisted
    persisted -->|advanced| observe[continue observing]
    persisted -->|not advanced| abortOnly[show sent-once state; offer Abort only]
```

Every declared choice is confirmed before dispatch. A PTY submission is sent at most once and never
resent while state stays paused. Mixed, dynamic, loop/fan-out, and interactive-retry gate shapes
are rejected before Start when deterministic prompt ownership cannot be proven.

## Abort and lifecycle

```mermaid
stateDiagram-v2
    [*] --> Running
    Running --> Aborting: confirmed Abort or catchable signal
    Aborting --> Reaped: SIGINT, bounded grace, TERM/KILL if needed
    Reaped --> Aborted: clear PID/PGID, record Cockpit-owned outcome
    Running --> Completed
    Running --> Failed
    Aborted --> [*]
    Completed --> [*]
    Failed --> [*]
```

The engine exposes no abort command, so Cockpit sends SIGINT to the recorded engine process group.
A paused run whose command already exited is aborted locally with no signal. `SIGKILL`, host loss,
and power loss carry no cleanup guarantee.

## Process and state reconciliation

| Process | Persisted state | Cockpit interpretation |
|---|---|---|
| live | running/initializing | Running; continue polling and reading output. |
| reaped normally | paused | Paused with no signalable process; Abort only. |
| reaped | completed | Success after output drain and reap. |
| reaped | failed/aborted | Engine terminal result with persisted step/cause when available. |
| reaped | missing/nonterminal | Unexpected process death; preserve output tail and report failure. |
| live | any, after confirmed Abort | Aborting; signal only the verified owned group. |
| reaped | any, after Cockpit Abort began | Cockpit-aborted after cleanup completes. |

## Dogfooding workflow

Repository changes run through `workflows/lean-flow/workflow.yml`:
`specify -> review-spec -> plan -> review-plan -> tasks -> implement -> update-documentation`. The
final step invokes the `arc42-context` extension command `speckit.arc42.update-docs`, which updates
the affected architecture documents in the same change. See [§7 Deployment View](07-deployment-view.md).
