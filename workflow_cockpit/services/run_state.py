"""Tolerant reads of engine run files, skipping unchanged content."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_UNSET = object()


@dataclass(frozen=True)
class RunStateData:
    status: str = "initializing"
    current_step_id: str | None = None
    current_step_index: int = 0
    step_results: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    updated_at: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    log_tail: tuple[dict[str, Any], ...] = ()
    complete: bool = False

    def current_result(self) -> dict[str, Any] | None:
        """The recorded result mapping for the current runtime step, if any."""
        if not self.current_step_id:
            return None
        result = self.step_results.get(self.current_step_id)
        return result if isinstance(result, dict) else None


@dataclass
class _CacheEntry:
    signature: tuple[int, int] | None
    value: Any


class RunStateReader:
    """Read ``state.json``/``inputs.json``/``log.jsonl`` with a tolerant cache.

    Files are considered unchanged when inode, size, and mtime are stable, so an
    atomic replacement with identical content is still detected via the inode.
    """

    def __init__(self, project_root: Path, run_id: str, log_tail: int = 80) -> None:
        self.run_dir = Path(project_root) / ".specify" / "workflows" / "runs" / run_id
        self.log_tail = log_tail
        self._state_cache: _CacheEntry | None = None
        self._inputs_cache: _CacheEntry | None = None
        self._log_cache: _CacheEntry | None = None

    @staticmethod
    def _signature(path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return (stat.st_ino, stat.st_mtime_ns)

    def _read_json(self, path: Path, cache: _CacheEntry | None) -> tuple[Any, _CacheEntry]:
        signature = self._signature(path)
        if signature is None:
            return _UNSET, _CacheEntry(None, _UNSET)
        if cache is not None and cache.signature == signature and cache.value is not _UNSET:
            return cache.value, cache
        try:
            with open(path, encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return cache.value if cache and cache.value is not _UNSET else _UNSET, _CacheEntry(
                signature, cache.value if cache else _UNSET
            )
        return value, _CacheEntry(signature, value)

    def _read_log(self) -> tuple[dict[str, Any], ...]:
        path = self.run_dir / "log.jsonl"
        signature = self._signature(path)
        if signature is None:
            return ()
        if self._log_cache is not None and self._log_cache.signature == signature:
            return self._log_cache.value
        try:
            raw = path.read_bytes()
        except OSError:
            return ()
        text = raw.decode("utf-8", errors="replace")
        lines = text.split("\n")
        if not text.endswith("\n"):
            lines = lines[:-1]
        entries: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                entries.append(record)
        tail = tuple(entries[-self.log_tail :])
        self._log_cache = _CacheEntry(signature, tail)
        return tail

    def read(self) -> RunStateData | None:
        if not self.run_dir.is_dir():
            return None
        state, self._state_cache = self._read_json(self.run_dir / "state.json", self._state_cache)
        if state is _UNSET or not isinstance(state, dict):
            inputs, self._inputs_cache = self._read_json(
                self.run_dir / "inputs.json", self._inputs_cache
            )
            return RunStateData(
                inputs=(inputs.get("inputs", {}) if isinstance(inputs, dict) else {}),
                log_tail=self._read_log(),
                complete=False,
            )
        inputs, self._inputs_cache = self._read_json(
            self.run_dir / "inputs.json", self._inputs_cache
        )
        status = state.get("status")
        step_results = state.get("step_results")
        return RunStateData(
            status=str(status) if isinstance(status, str) and status else "initializing",
            current_step_id=(
                state.get("current_step_id")
                if isinstance(state.get("current_step_id"), str)
                else None
            ),
            current_step_index=(
                state.get("current_step_index")
                if isinstance(state.get("current_step_index"), int)
                else 0
            ),
            step_results=step_results if isinstance(step_results, dict) else {},
            error=state.get("error") if isinstance(state.get("error"), str) else None,
            updated_at=state.get("updated_at") if isinstance(state.get("updated_at"), str) else None,
            inputs=(inputs.get("inputs", {}) if isinstance(inputs, dict) else {}),
            log_tail=self._read_log(),
            complete=True,
        )
