# tests/AGENTS.md

Nested context for the test tree. Root [`AGENTS.md`](../AGENTS.md) rules still apply; this file
adds only test-specific boundaries.

- **Capability-gate platform-specific tests.** Use the helpers in `tests/support.py`
  (`requires_posix`, `requires_pty`, `POSIX`, `PTY`) instead of assuming Linux.
- **Never hardcode a machine path.** The real-`specify` suite reads
  `WORKFLOW_COCKPIT_REAL_SPECIFY` and skips when unset. This is AI Debt Register entry D-1: do not
  reintroduce a personal fallback path.
- **No network.** Tests run offline; use the fakes in `tests/fixtures/`.
- **Match the harness conventions.** Unit tests use `unittest`; UI tests use
  `App.run_test()` with the `StyledApp`/`FakeSession` helpers.
- **Keep documentation tests in `tests/docs/`.** They assert structure, links, format, budget, and
  ADR integrity for `docs/`.
- **Keep files under 500 lines and split by domain.** `tests/support.py` and
  `tests/unit/test_session.py` are over the limit (AI Debt Register D-2); do not grow them.
