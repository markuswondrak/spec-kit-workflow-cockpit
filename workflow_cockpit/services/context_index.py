"""Write the stable Cockpit context index for the current run.

The index is a Markdown file at a fixed path under the engine run metadata
directory. It is a pointer, never a copy: it names the one run Cockpit binds to
this worktree and lists the authoritative sources a user-chosen external agent
should read instead. Every value owned by another file (run status, feature
directory, ownership) stays in that file; the index only points at it, so it
cannot drift. It is the only Cockpit writer inside ``.specify/`` and a
generation failure is reported, never fatal.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .definition import WorkflowDefinition

#: Stable project-relative location of the context index.
CONTEXT_INDEX_RELATIVE = Path(".specify") / "workflows" / "runs" / "current_run"

#: Name of the shipped skill that consumes this index.
SKILL_NAME = "cockpit-run-context"

#: One-line guidance shown by Cockpit next to the context path.
SKILL_GUIDANCE = f'In your agent, invoke the "{SKILL_NAME}" skill with this path.'


class ContextIndexError(Exception):
    """Raised when a context index cannot be rendered or written."""


@dataclass(frozen=True)
class ContextIndex:
    """Result of one successful context-index write."""

    path: Path
    relative: str


def _validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not run_id.strip():
        raise ContextIndexError("A run ID is required to write the context index.")
    if "\x00" in run_id:
        raise ContextIndexError("The run ID contains an invalid character.")
    if run_id in (".", "..") or "/" in run_id or "\\" in run_id:
        raise ContextIndexError("The run ID must be a single path segment.")
    return run_id


class ContextIndexWriter:
    """Render and atomically write ``.specify/workflows/runs/current_run``.

    The index is a pure pointer: it records the Cockpit-owned run binding and the
    paths to the authoritative sources. It never resolves or caches values owned
    by another file (the declared feature directory, run status, ownership), so
    there is nothing that can go stale between runs.
    """

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)

    @property
    def index_path(self) -> Path:
        return self.project_root / CONTEXT_INDEX_RELATIVE

    @property
    def relative_path(self) -> str:
        return CONTEXT_INDEX_RELATIVE.as_posix()

    def render(
        self,
        *,
        run_id: str,
        definition: WorkflowDefinition,
        branch: str | None = None,
        executable: Path | str | None = None,
    ) -> str:
        """Return the context-index Markdown for one run."""
        run_id = _validate_run_id(run_id)
        root = self.project_root.resolve()
        runs_dir = root / ".specify" / "workflows" / "runs"
        run_dir = runs_dir / run_id

        installed_definition = (
            Path(definition.source).resolve()
            if definition.source is not None
            else root / ".specify" / "workflows" / definition.id / "workflow.yml"
        )
        overlays_dir = root / ".specify" / "workflows" / "overlays" / definition.id
        feature_json = root / ".specify" / "feature.json"
        ownership_claim = run_dir / ".cockpit-owner.json"

        status_command = self._status_command(executable, run_id)

        lines: list[str] = [
            "# Cockpit run context",
            "",
            "This is a stable index for the current run, written by Workflow Cockpit. It is a",
            "pointer, not run state: it never copies values owned by another file. Read the",
            "authoritative sources below and resolve them yourself instead of trusting this file.",
            "",
            f"- Run ID: `{run_id}`",
            f"- Workflow: {definition.name} (`{definition.id}`)",
            f"- Worktree root: `{root}`",
            "",
            "## Authoritative sources",
            "",
            f"- Status: `{run_dir / 'state.json'}`",
            f"- Inputs: `{run_dir / 'inputs.json'}`",
            f"- Logs: `{run_dir / 'log.jsonl'}`",
            f"- Status command: `{status_command}`",
            f"- Workflow definition (launch copy): `{run_dir / 'workflow.yml'}`",
            f"- Workflow definition (installed base): `{installed_definition}`",
            f"- Enabled overlays directory: `{overlays_dir}`",
            "- Current branch and commit: read Git in the worktree, for example",
            f"  `git -C {root} branch --show-current` and `git -C {root} rev-parse --short HEAD`.",
            f"- Declared feature directory: read `feature_directory` from `{feature_json}`.",
            f"- Ownership claim: `{ownership_claim}` (Cockpit-owned owner identity and liveness).",
            "",
            "## Gate check before editing",
            "",
            "Read `state.json` before changing any repository file. The engine is at a gate only",
            'when `status` is `"paused"` (structured gate) or `status` is `"running"` with',
            "`current_step_id` naming a declared gate step (a live interactive prompt). A terminal",
            "status means the run is over: do not edit on its behalf.",
            "",
            "## Lifecycle ownership",
            "",
            "- Workflow Cockpit alone owns this run: it starts a new run or adopts an existing",
            "  paused run, then resumes, decides, and aborts it.",
            "- An adopted run's launch-copy `workflow.yml` and persisted run files stay authoritative.",
            "- Never run `specify workflow run`, `specify workflow resume`, or any decision or",
            "  abort command. Inspection is read-only and safe.",
            f"- {SKILL_GUIDANCE}",
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _status_command(executable: Path | str | None, run_id: str) -> str:
        base = str(executable) if executable else "specify"
        return f"{base} workflow status {run_id} --json"

    def write(
        self,
        *,
        run_id: str,
        definition: WorkflowDefinition,
        branch: str | None = None,
        executable: Path | str | None = None,
    ) -> ContextIndex:
        """Atomically write the context index and return its path."""
        content = self.render(
            run_id=run_id,
            definition=definition,
            branch=branch,
            executable=executable,
        )
        index_path = self.index_path
        runs_dir = index_path.parent
        try:
            runs_dir.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=runs_dir,
                prefix=".current_run-",
                suffix=".tmp",
                delete=False,
            )
            temp_path = Path(handle.name)
            try:
                with handle:
                    handle.write(content)
                os.replace(temp_path, index_path)
            except OSError:
                temp_path.unlink(missing_ok=True)
                raise
        except OSError as exc:
            raise ContextIndexError(f"Could not write the context index: {exc}") from exc
        return ContextIndex(path=index_path, relative=self.relative_path)

    def clear_if_current(self, run_id: str) -> bool:
        """Remove the index when it names ``run_id``; return whether it was removed.

        Used after a run directory is deleted so the stable index never points at
        a missing run. A missing or unreadable index is not an error.
        """
        try:
            run_id = _validate_run_id(run_id)
            text = self.index_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, ContextIndexError):
            return False
        if f"- Run ID: `{run_id}`" not in text:
            return False
        try:
            self.index_path.unlink()
        except OSError:
            return False
        return True
