# 11. AI Debt Register

| Field | Value |
|---|---|
| arc42 | 11. AI Debt Register |
| Tier | 3 |

Reference material. Not auto-loaded. This register lists patterns **present in the codebase** that
are known debt. They stay until fixed deliberately; no change may replicate them.

## Entry format

```markdown
### D-<n>: <short pattern name>
- Location: <path:line or path>
- Why it is debt: <what breaks or decays>
- Do not replicate: <the trap to avoid>
- Safe alternative: <the pattern to use instead>
```

## Known debt

### D-1: Environment-specific absolute path baked into test support
- Location: `tests/support.py` (`REAL_SPECIFY` fallback `/home/markus/.../specify`)
- Why it is debt: the suite silently depends on one developer's machine and skips differently for
  everyone else, so a real-engine regression can go unnoticed.
- Do not replicate: never commit a personal absolute path into shared code or tests.
- Safe alternative: read the executable from an environment variable only
  (`WORKFLOW_COCKPIT_REAL_SPECIFY`) and skip when it is unset.

### D-2: Source files over the 500-line limit
- Location: `tests/unit/test_session.py` (530)
- Why it is debt: large files resist focused review and hide unrelated responsibilities; the
  project rule caps files at 500 lines.
- Do not replicate: do not keep growing an over-limit file by appending cases.
- Safe alternative: split by functional domain (for example one module per session concern) and
  share fixtures from a smaller support module. `tests/support.py` was split this way: the doubles
  moved to `tests/fakes.py`, and new session concerns go to `tests/unit/test_session_runs.py`.

### D-3: Prototype test module inside a package directory
- Location: `workflow_ui/prototype/test_prototype.py`
- Why it is debt: product code and its tests share a directory and the directory is excluded from
  lint, so the module's style and coverage drift from `tests/`.
- Do not replicate: do not place test modules beside application modules in this repository.
- Safe alternative: keep prototype checks under `tests/` (or treat the prototype as disposable and
  test it only in `tests/textual/`).

### D-4: Tracked constitution regenerated from an untracked template
- Location: `.specify/memory/constitution.md`
- Why it is debt: the file is tracked, but `speckit.constitution` renders it from an untracked
  template, so any manual edit (including documentation links) can be silently overwritten.
- Do not replicate: do not treat generated scaffolding as a durable source of truth.
- Safe alternative: keep durable guidance in `AGENTS.md` and `docs/architecture/`; treat the
  constitution as a regenerable pointer only.

### D-5: Session facade over its size cap
- Location: `workflow_cockpit/session/cockpit_session.py`
- Why it is debt: the facade already exceeded the 500-line rule (AGENTS.md, "Keep functionality
  component scoped and files under 500 lines") and the resume seam added a thin
  `resume_run`/`resume_decision` delegate plus one snapshot reconciliation branch, so it grew
  further. Large facades resist focused review and hide unrelated responsibilities.
- Do not replicate: do not add new orchestration directly to the facade by default.
- Safe alternative: keep domain logic in its own module (the resume lifecycle already lives in
  `workflow_cockpit/session/resume.py`); when the facade next needs a change, extract a concern
  (for example the gate/resume projection and status reconciliation) into a `session/` mixin or a
  pure `lifecycle` helper rather than appending to the facade.
