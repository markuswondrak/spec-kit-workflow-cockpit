# Spec Kit Workflow Cockpit

[![Test](https://github.com/markuswondrak/spec-kit-workflow-cockpit/actions/workflows/test.yml/badge.svg)](https://github.com/markuswondrak/spec-kit-workflow-cockpit/actions/workflows/test.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-2EA44F)](LICENSE)

**Let agents execute. Keep the decisions.**

A terminal cockpit for [Spec Kit](https://github.com/github/spec-kit) workflows. Follow execution, review feature documents, and
decide what happens next without leaving the terminal.

<img width="1329" height="1060" alt="Bildschirmfoto vom 2026-09-16 08-45-59" src="https://github.com/user-attachments/assets/a544b8b8-1e5b-4f56-b734-6374ffe0fe17" />

[Quickstart](#quickstart) | [Configuration](#configuration) |
[Architecture](docs/architecture/README.md) | [Contributing](CONTRIBUTING.md)

## Why Cockpit?

An automated workflow still needs a place for human judgment. Workflow Cockpit puts execution
context and review in the same interface:

- **Know where you are.** See the branch, current node, engine status, and workflow Runway.
- **Review before deciding.** Browse Feature Files and read formatted Markdown at a gate.
- **Choose explicitly.** Submit only the workflow's declared options, with confirmation.
- **Follow execution.** Watch bounded live Engine Output without treating it as workflow state.
- **Keep ownership clear.** Each Cockpit session owns exactly one run in one project/worktree.

Cockpit is a standalone Python + Textual application. It invokes the installed `specify` CLI for
workflow actions and reads persisted run files for authoritative state. It never modifies the
engine or imports its internals. Feature Files show the current feature directory, not a Git diff.

### Relationship to AgentMux

If you're familiar with [AgentMux](https://github.com/markuswondrak/AgentMux), you might wonder why 
there’s another tool. 

AgentMux was my initial attempt at building a deterministic multi-agent pipeline via tmux. Even back 
then, I wanted to combine AgentMux with Spec Kit. But while I was working on it, Spec Kit introduced 
its own native workflows — which solved the underlying pipeline problem much more cleanly and even
introduces the flexibility I actually was looking for. 

Instead of forcing Spec Kit into AgentMux, it made far more sense to just build a dedicated TUI 
directly on top of the workflow engine. 

So for Spec Kit projects, Cockpit essentially replaces AgentMux. AgentMux remains available as a 
standalone experiment for custom multi-agent setups outside of Spec Kit.

## Prerequisites

- **Python 3.10 or newer** and Git.
- **Linux, macOS, and WSL** are supported. Native Windows is explicitly unsupported; use WSL.
- **A terminal at least 88 columns by 36 rows.** Smaller windows show a resize prompt.
- **A workflow-capable `specify` CLI**, installed separately. Cockpit accepts `>=1.0,<2.0` and
  probes for the required workflow commands and flags; a version number alone is not sufficient.
- **An initialized Spec Kit project** containing `.specify/`, in a Git worktree with at least
  one commit.
- **An enabled, installed workflow** and the coding-agent integration it needs, configured and
  authenticated before starting a run.

Use your Spec Kit distribution's installation and initialization instructions. Cockpit does not
install the engine, initialize projects, or configure agent credentials. The supported CLI
contract is described in [Context and Scope](docs/architecture/03-context-and-scope.md).

## Installation

From the root of a source checkout of `spec-kit-workflow-cockpit`:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
workflow-cockpit --help
```

Keep this environment active when using the commands below. The repository is named
`spec-kit-workflow-cockpit`; the Python distribution and terminal command are `workflow-cockpit`.

To install without cloning, pull the package straight from the repository:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install "git+https://github.com/markuswondrak/spec-kit-workflow-cockpit.git"
workflow-cockpit --help
```

Pin a revision for reproducibility by appending `@<ref>` to the URL, for example
`...workflow-cockpit.git@main` or a commit hash.

To build and install a wheel instead, start from the checkout in an activated environment:

```bash
python -m pip install build
python -m build
python -m pip install dist/workflow_cockpit-*.whl
```

Use a fresh `dist/` directory so the wildcard selects one wheel. This installation path does not
assume a PyPI release is available. See [Contributing](CONTRIBUTING.md) for the clean-environment
artifact smoke check and editable development setup.

## Quickstart

In your **initialized Spec Kit project**, with a compatible `specify` on `PATH` and a workflow
already installed:

```bash
workflow-cockpit --check
workflow-cockpit
```

The first command checks the platform, Git worktree, project initialization, and engine
compatibility without opening the UI. Resolve any reported failures before continuing. It does
not check agent authentication or whether all workflow commands are installed.

1. Select a workflow with the arrow keys or `j`/`k`, then press Enter to configure it.
2. Fill in its required inputs and activate **START RUN**. A dirty worktree requires confirmation.
3. Follow progress in the Runway and Engine Output.
4. At a gate, review the Feature Files, choose a declared option, and confirm your decision.
5. Follow the run to its outcome, or use Cockpit's Abort action to stop it.

To target a project from elsewhere, pass `--project /path/to/project`. To use a particular engine
installation, pass `--specify /path/to/specify`. Both options also work with `--check`.

### Try the Bundled Lean Flow

The repository includes a workflow for developing changes with specification and plan review gates:

```text
Specify -> Spec Review -> Plan -> Plan Review -> Tasks -> Implement -> Update Docs
```

From an initialized Spec Kit project **at this checkout's root**, with the base lean commands and
your chosen agent integration already configured, register the bundled components:

```bash
specify preset add --dev ./presets/lean-workflow --priority 1
specify extension add --dev ./extensions/arc42
specify workflow add --dev ./workflows/lean-flow
```

Then follow the quickstart above, choose **Lean Flow**, and describe your change in the required
`spec` input. The `integration` input defaults to `auto`, using the project's initialized
integration. Both review gates offer `approve` or `reject`; rejection aborts this workflow.

The [lean-workflow preset](presets/lean-workflow/README.md) supplies unattended runtime instructions
and lets the agent name its feature directory under `specs/`. Priority `1` takes precedence over
the base lean preset's `10`. The [arc42 extension](extensions/arc42/README.md) supplies the final
living-documentation step. These are source-checkout tooling, not contents of the wheel.

See [Contributing](CONTRIBUTING.md#preferred-development-path) for the preferred dogfooding path
and how to refresh installed components after edits.

## Configuration

Workflow selection and input values are configured in the UI. There is no general Cockpit
configuration file.

| Setting | Purpose and default |
|---|---|
| `--project PATH` | Project root; otherwise discover the nearest `.specify/` in the current directory or its parents. |
| `--specify PATH` | Engine executable; takes precedence over `WORKFLOW_COCKPIT_SPECIFY`, then `specify` on `PATH`. |
| `--check` | Print preflight results and exit without opening the UI. |
| `--style NAME` | Override appearance; otherwise use the project's default integration, with neutral fallback. |
| `EDITOR` | Optional external editor for Feature Files while paused at a gate. |

Built-in styles are `cockpit`, `claude`, `github-copilot`, and `opencode`. Styles change colors,
not the agent integration or workflow behavior. Project defaults come from
`.specify/integration.json`; custom styling templates live in `.specify/cockpit/templates/`.
Use the [neutral template](workflow_cockpit/styling/templates/cockpit.json) as a schema example.
Custom templates should use their own names; they do not override built-ins.

Use `specify` to manage installed workflows and their definitions under `.specify/workflows/`.
Persisted files in `.specify/workflows/runs/<run-id>/` remain the authoritative run state, while
`.specify/feature.json` identifies the feature directory used for review. See
[Crosscutting Concepts](docs/architecture/08-crosscutting-concepts.md) for styling and read-model
conventions.

## Safety and Limits

Cockpit owns one engine process group, not a fleet of agents or multiple concurrent runs. It is
not a sandbox: workflow steps and agents operate with the permissions of the environment in which
you launch them. Review your workflow and agent configuration before starting.

Catchable `SIGINT`, `SIGHUP`, and `SIGTERM` delivered to the Cockpit process trigger a bounded
best-effort abort and cleanup of its recorded engine process group without a confirmation prompt.
There is **no cleanup guarantee** for `SIGKILL`, host loss, power loss, or interpreter failure:
Cockpit cannot run cleanup it never receives, and the engine process group may be left running.

## Documentation and Requirements

Documentation follows **arc42**, with twelve sections indexed in
[`docs/architecture/README.md`](docs/architecture/README.md), numbered decisions alongside it,
and a shared glossary. The layout is designed for focused reading by both people and coding
agents, not for loading the entire documentation set into every conversation.

| Start here | What it contains |
|---|---|
| [Architecture index](docs/architecture/README.md) | Goals, constraints, boundaries, components, runtime, deployment, and quality context. |
| [Functional requirements](docs/architecture/01-introduction-and-goals.md) | Product promise, goals, and functional requirements. |
| [Quality requirements](docs/architecture/10-quality-requirements.md) | Quality scenarios and acceptance targets. |
| [Backlog](https://github.com/markuswondrak/spec-kit-workflow-cockpit/issues) | Open story slices and deferred work, including the [E01 OpenCode adapter](https://github.com/markuswondrak/spec-kit-workflow-cockpit/issues/1). |
| [Decision log](docs/decisions/README.md) | Numbered architecture decision records. |
| [Glossary](docs/glossary.md) | Pinned terms such as Run, Gate, Feature File, and Runway. |
| [Agent instructions](AGENTS.md) | Always-on repository constraints and commands. |

`AGENTS.md` is the only always-on context. Load the matching architecture section on demand;
strategy, quality scenarios, and the AI Debt Register are reference-only. Code establishes
behavior; documentation establishes intent and constraints. Conflicts should be surfaced rather
than silently reconciled.

For the rationale behind this documentation approach, read the
[documentation context article](https://markus.wondrax.cloud/articles/documentation-agentic-coding.html).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for local setup, exact lint and test commands, artifact
verification, and the preferred dogfooding workflow. Develop repository changes through the bundled
Lean Flow and review its gates in Cockpit whenever practical.

[CI](.github/workflows/test.yml) runs Ruff and the unit, Textual, contract, PTY, and documentation
suites on Linux and macOS with Python 3.10 and 3.12. A dependent job builds the sdist and wheel,
then checks installation in a fresh environment. WSL verification is run locally using the same
quality commands in the contributor guide.

## License

[MIT](LICENSE).
