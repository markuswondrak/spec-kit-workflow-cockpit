# 12. Glossary

| Field | Value |
|---|---|
| arc42 | 12. Glossary |
| Tier | 3 |

Reference material. Pins the vocabulary so synonyms are not treated as interchangeable. If a term
is used differently in code, the code wins for behavior; this file wins for intent.

## Terms

| Term | Meaning | Not to be confused with |
|---|---|---|
| **Run** | One execution of one workflow in one project/worktree, identified by a run ID. | A Cockpit session, which owns exactly one run. |
| **Cockpit session** | One `workflow-cockpit` process bound to one run. | Run history in `.specify/workflows/runs/`. |
| **Run descriptor** | The bounded, read-only summary of a discovered run: run ID, workflow, persisted status, step, age, and usability. | Persisted `state.json`, which is the source it reads. |
| **Adoptable run** | A discovered run whose persisted status is `paused` or `failed`, with a launch copy and no conflicting live owner. | Every discovered paused or failed run; one with a live foreign owner is not adoptable. |
| **Viewable run** | A discovered run with readable `state.json` and a launch-copy definition, eligible for view-only inspection. | An adoptable run, which must additionally be `paused` or `failed` and claimable. |
| **Ownership claim** | The durable `.cockpit-owner.json` record naming the single Cockpit owner of a run, with liveness evidence; held for every run Cockpit starts or adopts. | The engine process group, which only the supervisor signals. |
| **Adoption** | Binding a session and supervisor to an existing paused or failed run without spawning the engine. | A new Start, which allocates a fresh run ID. |
| **Failed run** | A discovered run whose persisted status is `failed`; it is adoptable and resumable once from its recorded step. | An `aborted` run, which is terminal and stays read-only. |
| **Resume action** | The confirmed, write-once lifecycle action that issues exactly one bare `specify workflow resume <run_id>` for an adopted failed run. | A gate decision, which answers a declared pause. |
| **Resume point** | The persisted current step a resume continues from, and its immediate enclosing step when nested. | The engine's exact re-run set, which the engine owns. |
| **View-only inspection** | Observing an existing run's state, graph, and logs read-only without acquiring an ownership claim, binding a supervisor, or writing lifecycle state. | Adoption, which claims ownership and can decide gates. |
| **Run deletion** | Removing one stale run directory from the launch screen after a destructive confirmation, refusing a live-owned, running, or currently open run. | Automatic pruning or engine cleanup; deletion is always explicit. |
| **Gate** | A workflow-declared pause with a message and declared options. | A Cockpit confirmation dialog. |
| **Workflow call** | A `type: workflow` step that runs another installed, enabled workflow as a private scope inside the same run. | A separate run; a call shares the run ID and run directory. |
| **Scope** | One workflow's private execution context inside a run: the root workflow or a called workflow. | A step; a scope contains steps. |
| **Scope path** | The chain of call step ids leading to a node, with item/iteration indices after fan-out and loop steps (for example `review-release > review`). | The occurrence path in the log, which is index based. |
| **Scope occurrence** | One execution of a scope; a call inside a loop yields several occurrences of the same scope. | The scope itself; occurrences are distinguished by their scope path. |
| **Execution tree** | The persisted, versioned record in `state.json` of the root and called scopes, with frozen definitions, bound inputs and per-node `phase`/`active`/`result`. | The control-flow graph, which is the declared shape. |
| **Active node** | The engine's active step: the first node whose `phase` is not `done` in a children-first walk. | The node carrying `active: true`, which every entered node carries. |
| **Frozen definition** | The called workflow's definition as the engine froze it at binding time inside the execution tree. | The installed definition, which may have changed since. |
| **Handled call failure** | A call whose own result failed under `continue_on_error` while the run continued. | A failed run; the persisted run status is unchanged. |
| **Gate affordance** | The presentation mode selected by a gate's declared choice count: equal-weight buttons for one to three choices, one compact select box for four or more. | The declared choices themselves, which are unchanged by the mode. |
| **Decision** | The user's confirmed choice among a gate's declared options. | An Abort, which is a separate lifecycle action. |
| **Verdict input** | A gate's declared `verdict_input` name, answered by structured `resume`. | The PTY fallback for gates without one. |
| **PTY** | The internal pseudo-terminal that carries engine output and fallback gate input. | A user-visible terminal. |
| **Supervisor** | `EngineSupervisor`: the single owner and reaper of the engine process group. | Any long-running task. |
| **Snapshot** | `RunSnapshot`: an immutable view published by the polling loop. | Persisted `state.json`. |
| **Gate snapshot** | `GateSnapshot`: one declared gate projected for submission. | The persisted engine pause. |
| **Feature File** | Any file under the declared feature directory, including files that predate Start. | A diff or run artifact. |
| **Feature directory** | The path declared in `.specify/feature.json`. | `.specify/workflows/runs/<id>/`. |
| **Run file** | A persisted engine file: `state.json`, `inputs.json`, `log.jsonl`, `workflow.yml`. | Cockpit-owned persistence, which does not exist. |
| **Engine Output** | The bounded, read-only `RichLog` fed from the supervisor. | `log.jsonl`, the complete source. |
| **Runway** | The scrollable control-flow graph with runtime overlay. | A linear step list. |
| **Focus** | The single state-driven canvas (State, Files, Gate, Output, Outcome). | A fixed set of panes. |
| **Context index** | The stable `current_run` Markdown pointer to the authoritative sources; it copies no value owned by another file. | A copied live snapshot; any value it copies can drift. |
| **Machine-readable pointer** | `current_run.json`: the JSON twin of the context index, carrying only `schema_version`, `run_id`, `run_dir`, and `workflow_id`. | Run state; the pointer names a run, it never describes one. |
| **Pointer disagreement** | The reported state in which the Markdown index and the JSON twin name different runs, or only one exists; neither is trusted. | A missing run, which is reported as an empty pointer. |
| **File view** | The read command's versioned, bounded, read-only JSON description of the current run, built from the persisted run files through the same readers the UI uses. | The UI itself, or a second state model. |
| **Read envelope** | The JSON object `workflow-cockpit context --json` prints: pointer, run, step, gate, projection, bounded Feature Files index, per-source conditions, and an optional file. | A snapshot, which is an in-process immutable value. |
| **Condition** | A per-source report that a source was missing, partial, stale, or too large; the fields derived from that source stay null. | A diagnostic or a log line. |
| **Schema version** | The integer that versions the read envelope's shape; a frontend compares it for equality with the version it supports. | The package version or the host protocol version. |
| **Protocol version** | The integer that versions the host protocol's message shape, carried on every message. | The read envelope's schema version; they version independently. |
| **Headless host** | The detached `workflow-cockpit serve` process that owns one run through the existing session and supervisor services and speaks the line-delimited JSON protocol. | The TUI, or a second lifecycle implementation. |
| **Owner view** | The host's operation set over the one run it owns: list, validate, start, status, gate, decide, abort, adopt, resume. | The read envelope, which is read-only. |
| **Start guard** | The shared rule that refuses Start when the current-run pointer names a non-terminal run, naming the run and the adopt-or-abort alternatives. | The ownership claim, which is a write-side lock. |
| **Integration installer** | `IntegrationInstaller`: the single install/update path for frontend artifacts, keyed on the project integration, with per-artifact policies. | A package manager or the engine's own installer. |
| **User-editable artifact** | An installer artifact installed once and then owned by the user; an existing file is never overwritten. | A managed artifact, which the package may replace. |
| **Managed artifact** | An installer artifact owned by the package, carrying a version marker and replaced atomically when the packaged version differs. | A user-editable artifact. |
| **Skill** | `cockpit-run-context`, installed at start into the project integration's skills directory and invoked in a user-chosen external agent. | A Cockpit-managed process. |
| **Overlay** | An enabled modification applied to a workflow definition before resolution. | A theme or styling template. |
| **Control Flow Graph** | The declared nodes, edges, branches, loops and calls of a workflow, and for a bound run the nested scopes built from the frozen execution tree. | Runtime status; the graph carries no persisted state. |
| **Story slice** | A vertical implementation slice (`S01`-`S10`) tracked as a GitHub issue. | An epic (`E01`). |
| **ADR** | A numbered architecture decision record under `docs/decisions/`. | A backlog issue. |
| **AI Debt Register** | This set's §11 list of patterns that must not be replicated. | A general backlog. |
| **Tier** | The load policy of an architecture section (1 entry, 2 on demand, 3 reference). | Priority. |

## Naming rules

- A **Run** is owned; a **session** owns it. Never say "the app owns runs".
- **Feature Files** is the whole declared directory; never call them "changes" or "diff".
- **Engine Output** is diagnostic evidence; **run files** are authoritative state.
- **Abort** is Cockpit's lifecycle action; the engine has no abort command.
- A **scope path** names scopes; an **occurrence path** is the engine's index-based log key. They are not interchangeable.
- A **file view** is the read command's envelope; a **snapshot** is the in-process value the UI renders. Never use them interchangeably.
- The **context index** is Markdown for agents; the **machine-readable pointer** is its JSON twin. They are one pointer pair, not two pointers.
