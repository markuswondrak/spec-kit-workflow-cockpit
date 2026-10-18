"""The machine-readable twin of the Markdown ``current_run`` pointer (FR-007).

``current_run`` is the Cockpit-owned index a user-chosen external agent reads
(ADR-0013). It is Markdown, so a program cannot read it without parsing prose.
This module writes a JSON twin next to it that carries only the pointer:
``schema_version``, ``run_id``, ``run_dir`` and ``workflow_id``. It never copies
run state, so there is nothing that can drift.

Two ``os.replace`` calls cannot be one atomic operation across two files, so the
writer commits in a fixed order (research R3): the JSON twin first, then the
Markdown index. Readers treat the Markdown file as the commit marker and report a
disagreement instead of guessing which file is authoritative. Writes never
produce a disagreement; a hand-edited or half-removed pair does.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

#: Stable project-relative locations of the pointer pair.
CURRENT_RUN_RELATIVE = Path(".specify") / "workflows" / "runs" / "current_run"
CURRENT_RUN_JSON_RELATIVE = Path(".specify") / "workflows" / "runs" / "current_run.json"

#: Bumped when the JSON pointer shape changes incompatibly.
POINTER_SCHEMA_VERSION = 1

#: Bounded read for either pointer file.
MAX_POINTER_BYTES = 64 * 1024

_RUN_ID_LINE = re.compile(r"^- Run ID: `([^`]+)`", re.MULTILINE)


class PointerState(str, Enum):
    """How the pointer pair reads back."""

    OK = "ok"
    EMPTY = "empty"
    DISAGREEMENT = "disagreement"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class CurrentRunPointer:
    """The pointer payload: identity and location only, never run state."""

    schema_version: int = POINTER_SCHEMA_VERSION
    run_id: str = ""
    run_dir: str = ""
    workflow_id: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "workflow_id": self.workflow_id,
        }

    @classmethod
    def from_dict(cls, data: object) -> CurrentRunPointer | None:
        if not isinstance(data, dict):
            return None
        run_id = data.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            return None
        schema_version = data.get("schema_version", POINTER_SCHEMA_VERSION)
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            schema_version = POINTER_SCHEMA_VERSION
        run_dir = data.get("run_dir")
        workflow_id = data.get("workflow_id")
        return cls(
            schema_version=schema_version,
            run_id=run_id,
            run_dir=run_dir if isinstance(run_dir, str) else "",
            workflow_id=workflow_id if isinstance(workflow_id, str) else "",
        )


@dataclass(frozen=True)
class PointerRead:
    """Result of reading the pointer pair, disagreement included."""

    state: PointerState
    run_id: str | None = None
    markdown_run_id: str | None = None
    json_run_id: str | None = None
    detail: str = ""

    @property
    def usable(self) -> bool:
        """True only when both files agree on one run identity."""
        return self.state is PointerState.OK and bool(self.run_id)


def default_run_dir(run_id: str) -> str:
    """The project-relative run directory of ``run_id``."""
    return (Path(".specify") / "workflows" / "runs" / run_id).as_posix()


def _atomic_write(path: Path, content: str, *, prefix: str) -> None:
    """Write ``content`` to ``path`` through a temp file and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=prefix,
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(content)
        os.replace(temp_path, path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise


def render_pointer_markdown(pointer: CurrentRunPointer) -> str:
    """A minimal Markdown pointer, used when no rendered index is supplied."""
    return "\n".join(
        [
            "# Cockpit run context",
            "",
            "This is a pointer, not run state. Read the authoritative sources in the run",
            "directory instead of trusting this file.",
            "",
            f"- Run ID: `{pointer.run_id}`",
            f"- Run directory: `{pointer.run_dir}`",
            f"- Workflow: `{pointer.workflow_id}`",
            "",
        ]
    )


class CurrentRunPointerWriter:
    """Write ``current_run.json`` then ``current_run``, and clear both together."""

    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root)

    @property
    def json_path(self) -> Path:
        return self.project_root / CURRENT_RUN_JSON_RELATIVE

    @property
    def markdown_path(self) -> Path:
        return self.project_root / CURRENT_RUN_RELATIVE

    def write(
        self,
        *,
        run_id: str,
        markdown: str | None = None,
        run_dir: str | None = None,
        workflow_id: str = "",
    ) -> CurrentRunPointer:
        """Commit the pointer pair: JSON first, then the Markdown commit marker."""
        pointer = CurrentRunPointer(
            run_id=run_id,
            run_dir=run_dir or default_run_dir(run_id),
            workflow_id=workflow_id,
        )
        payload = json.dumps(pointer.to_dict(), indent=2) + "\n"
        _atomic_write(self.json_path, payload, prefix=".current_run_json-")
        _atomic_write(
            self.markdown_path,
            render_pointer_markdown(pointer) if markdown is None else markdown,
            prefix=".current_run-",
        )
        return pointer

    def clear_if_current(self, run_id: str) -> bool:
        """Remove both files when they name ``run_id``; return whether any went."""
        removed = False
        read = CurrentRunPointerReader(self.project_root).read()
        named = {read.markdown_run_id, read.json_run_id, read.run_id}
        if run_id not in {value for value in named if value}:
            return False
        for path in (self.markdown_path, self.json_path):
            try:
                path.unlink()
                removed = True
            except OSError:
                continue
        return removed


class CurrentRunPointerReader:
    """Read the pointer pair and report a disagreement instead of guessing."""

    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root)

    @property
    def json_path(self) -> Path:
        return self.project_root / CURRENT_RUN_JSON_RELATIVE

    @property
    def markdown_path(self) -> Path:
        return self.project_root / CURRENT_RUN_RELATIVE

    def read(self) -> PointerRead:
        markdown_id, markdown_error = self._read_markdown()
        json_id, json_error = self._read_json()
        if markdown_id is None and json_id is None:
            if markdown_error or json_error:
                return PointerRead(
                    state=PointerState.UNREADABLE,
                    detail=" ".join(part for part in (markdown_error, json_error) if part),
                )
            return PointerRead(state=PointerState.EMPTY)
        if markdown_id is None:
            return PointerRead(
                state=PointerState.DISAGREEMENT,
                json_run_id=json_id,
                detail=(
                    f"current_run.json names {json_id!r} but the current_run index is "
                    f"{markdown_error or 'missing'}; the pointer is not trusted."
                ),
            )
        if json_id is None:
            return PointerRead(
                state=PointerState.DISAGREEMENT,
                markdown_run_id=markdown_id,
                detail=(
                    f"current_run names {markdown_id!r} but current_run.json is "
                    f"{json_error or 'missing'}; the pointer is not trusted."
                ),
            )
        if markdown_id != json_id:
            return PointerRead(
                state=PointerState.DISAGREEMENT,
                markdown_run_id=markdown_id,
                json_run_id=json_id,
                detail=(
                    f"current_run names {markdown_id!r} while current_run.json names "
                    f"{json_id!r}; the pointer is not trusted."
                ),
            )
        return PointerRead(
            state=PointerState.OK,
            run_id=markdown_id,
            markdown_run_id=markdown_id,
            json_run_id=json_id,
        )

    def _read_markdown(self) -> tuple[str | None, str]:
        path = self.markdown_path
        try:
            if not path.is_file():
                return None, ""
            if path.stat().st_size > MAX_POINTER_BYTES:
                return None, "unreadable (exceeds the pointer bound)"
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None, "unreadable"
        match = _RUN_ID_LINE.search(text)
        if match is None:
            return None, "unreadable (no run id)"
        return match.group(1), ""

    def _read_json(self) -> tuple[str | None, str]:
        path = self.json_path
        try:
            if not path.is_file():
                return None, ""
            if path.stat().st_size > MAX_POINTER_BYTES:
                return None, "unreadable (exceeds the pointer bound)"
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None, "unreadable"
        pointer = CurrentRunPointer.from_dict(data)
        if pointer is None:
            return None, "unreadable (no run id)"
        return pointer.run_id, ""
