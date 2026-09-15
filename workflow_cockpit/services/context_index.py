"""Write the stable Cockpit context index for the current run.

The index is a Markdown file at a fixed path under the engine run metadata
directory. It never copies live state: it lists the authoritative sources a
user-chosen external agent should read instead. It is the only Cockpit writer
inside ``.specify/`` and a generation failure is reported, never fatal.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .definition import WorkflowDefinition
from .feature_review import resolve_feature_directory

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


def _resolve_inside(root: Path, relative: str | None) -> Path | None:
    """Resolve a project-relative path, rejecting anything outside the root."""
    if not relative or "\x00" in relative or Path(relative).is_absolute():
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


class ContextIndexWriter:
    """Render and atomically write ``.specify/workflows/runs/current_run``."""

    def __init__(self, project_root: Path, *, feature_dir: str | None = None) -> None:
        self.project_root = Path(project_root)
        if feature_dir is not None:
            self._feature_dir = feature_dir
        else:
            self._feature_dir = resolve_feature_directory(self.project_root)

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

        feature_dir = self._feature_dir
        feature_path = _resolve_inside(root, feature_dir)
        if feature_path is not None and not feature_path.is_dir():
            feature_path = None
        if feature_path is None:
            feature_dir = None

        status_command = self._status_command(executable, run_id)

        lines: list[str] = [
            "# Cockpit run context",
            "",
            "This is a stable index for the current run, written by Workflow Cockpit. It is not",
            "run state: read the authoritative sources below instead of trusting this file.",
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
            f"- Declared feature directory source: `{feature_json}`",
            (
                f"- Declared feature directory: `{feature_path}`"
                if feature_path is not None
                else "- Declared feature directory: not declared (or unavailable); no Feature Files."
            ),
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
            "- Workflow Cockpit alone starts, resumes, decides, and aborts this run.",
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
