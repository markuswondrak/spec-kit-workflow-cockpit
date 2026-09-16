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
- Location: `tests/unit/test_session.py` (531), `tests/support.py` (504)
- Why it is debt: large files resist focused review and hide unrelated responsibilities; the
  project rule caps files at 500 lines.
- Do not replicate: do not keep growing an over-limit file by appending cases.
- Safe alternative: split by functional domain (for example one module per session concern) and
  share fixtures from a smaller support module.

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
