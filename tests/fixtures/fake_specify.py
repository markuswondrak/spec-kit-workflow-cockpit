#!/usr/bin/env python3
"""A tiny fake ``specify`` used by contract tests."""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    args = sys.argv[1:]
    record = os.environ.get("COCKPIT_TEST_RECORD")
    if record:
        with open(record, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "argv": args,
                    "cwd": os.getcwd(),
                    "init_dir": os.environ.get("SPECIFY_INIT_DIR"),
                    "run_id": os.environ.get("SPECKIT_WORKFLOW_RUN_ID"),
                    "inherited": os.environ.get("COCKPIT_TEST_INHERITED_INIT_DIR"),
                },
                handle,
            )
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
        run_id = os.environ.get("SPECKIT_WORKFLOW_RUN_ID", "unknown")
        run_dir = os.path.join(os.getcwd(), ".specify", "workflows", "runs", run_id)
        os.makedirs(run_dir, exist_ok=True)
        state = {
            "run_id": run_id,
            "workflow_id": "demo",
            "status": "completed",
            "current_step_id": "finish",
        }
        with open(os.path.join(run_dir, "state.json"), "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        sys.stdout.write("\x1b[32mRunning step finish\x1b[0m\n")
        sys.stdout.flush()
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
