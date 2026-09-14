#!/usr/bin/env python3
"""A tiny fake ``specify`` used by contract tests."""

from __future__ import annotations

import json
import os
import select
import sys
import time


def _write_state(run_dir: str, state: dict) -> None:
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "state.json"), "w", encoding="utf-8") as handle:
        json.dump(state, handle)


def _interactive_gate(run_id: str, run_dir: str) -> int:
    """Emulate a live non-verdict gate prompt over the PTY (contract section 10)."""
    gate = os.environ.get("COCKPIT_TEST_INTERACTIVE_GATE", "review")
    options = [
        item
        for item in os.environ.get("COCKPIT_TEST_INTERACTIVE_OPTIONS", "approve,reject").split(",")
        if item
    ]
    expect = os.environ.get("COCKPIT_TEST_INTERACTIVE_EXPECT", options[0] if options else "")
    input_path = os.environ.get("COCKPIT_TEST_INTERACTIVE_INPUT")

    _write_state(
        run_dir,
        {
            "run_id": run_id,
            "workflow_id": "demo",
            "status": "running",
            "current_step_index": 1,
            "current_step_id": gate,
            "step_results": {"prepare": {"type": "shell", "status": "completed"}},
            "updated_at": "2026-09-13T00:00:00+00:00",
        },
    )
    sys.stdout.write(
        "\n  ┌─ Gate ─────────────────────────────────────\n"
        "  │ Review required.\n"
        "  │\n"
        + "".join(f"  │  [{i}] {option}\n" for i, option in enumerate(options, 1))
        + "  └────────────────────────────────────────────\n"
        f"  Choose [1-{len(options)}]: "
    )
    sys.stdout.flush()

    received: list[str] = []
    decision = None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        ready, _, _ = select.select([sys.stdin], [], [], 0.2)
        if not ready:
            if received:
                break
            continue
        line = sys.stdin.readline()
        if not line:
            break
        received.append(line)
        raw = line.strip()
        if raw.isdecimal() and 1 <= int(raw) <= len(options):
            decision = options[int(raw) - 1]
        elif raw.lower() in [option.lower() for option in options]:
            decision = next(option for option in options if option.lower() == raw.lower())
        if decision is not None:
            break

    if input_path:
        with open(input_path, "w", encoding="utf-8") as handle:
            json.dump(received, handle)

    if decision == expect:
        _write_state(
            run_dir,
            {
                "run_id": run_id,
                "workflow_id": "demo",
                "status": "completed",
                "current_step_index": 2,
                "current_step_id": "finish",
                "interactive_input": "".join(received),
                "decision": decision,
            },
        )
        sys.stdout.write(f"\n  decision: {decision}\n")
        sys.stdout.flush()
        return 0
    _write_state(
        run_dir,
        {
            "run_id": run_id,
            "workflow_id": "demo",
            "status": "paused",
            "current_step_index": 1,
            "current_step_id": gate,
            "interactive_input": "".join(received),
            "decision": decision,
        },
    )
    return 1


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
    if args[:2] == ["workflow", "resume"]:
        run_id = args[2] if len(args) > 2 else os.environ.get("SPECKIT_WORKFLOW_RUN_ID", "unknown")
        run_dir = os.path.join(os.getcwd(), ".specify", "workflows", "runs", run_id)
        os.makedirs(run_dir, exist_ok=True)
        decision = None
        if "-i" in args:
            index = args.index("-i")
            if index + 1 < len(args):
                _, _, decision = args[index + 1].partition("=")
        state = {
            "run_id": run_id,
            "workflow_id": "demo",
            "status": "completed",
            "current_step_id": "finish",
            "resume_decision": decision,
        }
        _write_state(run_dir, state)
        sys.stdout.write("resumed\n")
        sys.stdout.flush()
        return 0
    if args[:2] == ["workflow", "run"]:
        run_id = os.environ.get("SPECKIT_WORKFLOW_RUN_ID", "unknown")
        run_dir = os.path.join(os.getcwd(), ".specify", "workflows", "runs", run_id)
        if os.environ.get("COCKPIT_TEST_INTERACTIVE_GATE"):
            return _interactive_gate(run_id, run_dir)
        os.makedirs(run_dir, exist_ok=True)
        state = {
            "run_id": run_id,
            "workflow_id": "demo",
            "status": "completed",
            "current_step_id": "finish",
        }
        _write_state(run_dir, state)
        sys.stdout.write("\x1b[32mRunning step finish\x1b[0m\n")
        sys.stdout.flush()
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
