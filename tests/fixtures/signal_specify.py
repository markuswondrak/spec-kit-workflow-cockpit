#!/usr/bin/env python3
"""A long-running fake ``specify`` used by the PTY signal tests."""

from __future__ import annotations

import json
import os
import sys
import time


def _run_dir() -> str:
    run_id = os.environ.get("SPECKIT_WORKFLOW_RUN_ID", "unknown")
    return os.path.join(os.getcwd(), ".specify", "workflows", "runs", run_id)


def main() -> int:
    args = sys.argv[1:]
    if "--version" in args:
        print("specify 1.0.0")
        return 0
    if args[:2] == ["workflow", "--help"]:
        print("Commands: run resume status list")
        return 0
    if args[:3] == ["workflow", "run", "--help"]:
        print("Usage: run [OPTIONS] --input -i --json")
        return 0
    if args[:2] == ["workflow", "run"]:
        run_dir = _run_dir()
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "state.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "run_id": os.environ.get("SPECKIT_WORKFLOW_RUN_ID"),
                    "workflow_id": "demo",
                    "status": "running",
                    "current_step_id": "main",
                },
                handle,
            )
        sys.stdout.write("running\n")
        sys.stdout.flush()
        time.sleep(120)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
