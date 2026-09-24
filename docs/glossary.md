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
| **Skill** | `cockpit-run-context`, installed at start into the project integration's skills directory and invoked in a user-chosen external agent. | A Cockpit-managed process. |
| **Overlay** | An enabled modification applied to a workflow definition before resolution. | A theme or styling template. |
| **Control Flow Graph** | The declared nodes, edges, branches, loops, and gates of a workflow. | Runtime status. |
| **Story slice** | A vertical implementation slice (`S01`-`S10`) tracked as a GitHub issue. | An epic (`E01`). |
| **ADR** | A numbered architecture decision record under `docs/decisions/`. | A backlog issue. |
| **AI Debt Register** | This set's §11 list of patterns that must not be replicated. | A general backlog. |
| **Tier** | The load policy of an architecture section (1 entry, 2 on demand, 3 reference). | Priority. |

## Naming rules

- A **Run** is owned; a **session** owns it. Never say "the app owns runs".
- **Feature Files** is the whole declared directory; never call them "changes" or "diff".
- **Engine Output** is diagnostic evidence; **run files** are authoritative state.
- **Abort** is Cockpit's lifecycle action; the engine has no abort command.
