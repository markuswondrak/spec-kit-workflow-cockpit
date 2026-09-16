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
| **Gate** | A workflow-declared pause with a message and declared options. | A Cockpit confirmation dialog. |
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
| **Context index** | The stable `current_run` Markdown index of authoritative sources. | A copied live snapshot. |
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
