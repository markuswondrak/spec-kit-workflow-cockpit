# Contributing to Workflow Cockpit

## Local setup

Workflow Cockpit supports Linux, macOS, and WSL. Native Windows is unsupported; use WSL instead.
You need Python 3.10 or newer, Git, and a compatible `specify` executable (`>=1.0,<2.0`) for an
end-to-end Cockpit run.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

## Verify a change

Run the same quality commands as CI:

```bash
ruff check workflow_cockpit tests
python -m pytest tests/unit tests/textual tests/contract tests/pty tests/docs -q
python -m build
python tests/release/smoke.py dist
```

The real-`specify` contract tests skip unless `WORKFLOW_COCKPIT_REAL_SPECIFY` names a pinned,
compatible executable. Set it to include that coverage:

```bash
WORKFLOW_COCKPIT_REAL_SPECIFY=/path/to/specify python -m pytest tests/contract -q
```

## Preferred development path

Drive repository changes through the bundled unattended workflow, then observe and decide each
gate in Workflow Cockpit. This keeps development dogfooded against the product rather than relying
only on direct agent edits.

From an initialized Spec Kit project at this repository root, install the released Extended Flow
from GitHub:

```bash
scripts/setup-speckit.sh --source github --ref v0.13.0
workflow-cockpit
```

Start the Cockpit and select **Spec-Kit Extended Flow — Feature Flow** or
**Spec-Kit Extended Flow — Quick Flow**. The feature workflow runs the standard Spec-Kit sequence:
`specify`, review gates, `plan`, `tasks`, `analyze`, `implement`, `converge`, documentation
reconciliation, and finish. Review the generated specification and plan at their gates before
approving them. Use Quick Flow for trivial changes.

For local development against an unreleased sibling checkout:

```bash
scripts/setup-speckit.sh --source local --path ../spec-kit-extended-flow
```

The cockpit never modifies the workflow engine or imports its internals. Persisted run files are
authoritative.

## Releasing

Maintainers cut releases from `main` with `scripts/release.sh`, which bumps the version, commits,
creates the `vMAJOR.MINOR.PATCH` tag, and pushes both. The version lives only in
`workflow_cockpit/__init__.py`; `pyproject.toml` resolves it dynamically. The Release workflow
re-verifies the tagged commit and publishes the artifacts with generated release notes. See
[RELEASING.md](RELEASING.md) for the full flow and hotfix guidance.
