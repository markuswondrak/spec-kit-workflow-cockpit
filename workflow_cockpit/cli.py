"""``workflow-cockpit`` entry point: discover the project, preflight, then run."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .bootstrap.compatibility import Compatibility
from .bootstrap.discovery import ProjectDiscovery, ProjectDiscoveryError
from .bootstrap.preflight import Preflight
from .services.git import GitService
from .session.cockpit_session import CockpitSession
from .ui.app import CockpitApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workflow-cockpit",
        description="Own one Spec Kit workflow run in one configured project.",
    )
    parser.add_argument(
        "--project",
        metavar="PATH",
        help="Explicit Spec Kit project root (defaults to nearest parent).",
    )
    parser.add_argument(
        "--specify",
        metavar="PATH",
        help="Explicit specify executable to use instead of PATH.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run preflight checks and exit without starting the UI.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        project = ProjectDiscovery().discover(args.project)
    except ProjectDiscoveryError as exc:
        print(f"workflow-cockpit: {exc}", file=sys.stderr)
        return 2

    compatibility = Compatibility()
    git = GitService(project.root)
    preflight = Preflight(project, compatibility, git, explicit_executable=args.specify)

    if args.check:
        report = preflight.run()
        for check in report.checks:
            marker = "OK  " if check.ok else "FAIL"
            print(f"[{marker}] {check.label}: {check.detail}")
            if not check.ok and check.repair:
                print(f"        repair: {check.repair}")
        return 0 if report.ok else 1

    def session_factory(result) -> CockpitSession:
        return CockpitSession(project.root, result, git=git)

    CockpitApp(preflight, session_factory).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
