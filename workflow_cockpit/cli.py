"""``workflow-cockpit`` entry point: discover the project, preflight, then run."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import replace

from .bootstrap.compatibility import Compatibility
from .bootstrap.discovery import ProjectDiscovery, ProjectDiscoveryError
from .bootstrap.preflight import Preflight
from .services.git import GitService
from .session.cockpit_session import CockpitSession
from .session.dependencies import CockpitEnvironment, CockpitServices
from .styling.resolver import resolve_style
from .ui.app import CockpitApp

_LOG = logging.getLogger(__name__)


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
    parser.add_argument(
        "--style",
        metavar="NAME",
        help="Styling template to use instead of the project's default integration.",
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
        environment = CockpitEnvironment(project.root, result)
        services = replace(CockpitServices.for_environment(environment), git=git)
        return CockpitSession(environment, services=services)

    style = resolve_style(project.root, override=args.style)
    if style.fallback_reason:
        _LOG.warning("style fallback: %s", style.fallback_reason)

    CockpitApp(preflight, session_factory, style=style).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
