"""``workflow-cockpit`` entry point: discover the project, then run one surface.

Four surfaces share one project discovery and one set of global flags:

* the default Textual cockpit (no subcommand),
* ``context --json``: the versioned, bounded, read-only file view,
* ``install``: the single install/update path for frontend artifacts,
* ``serve``: the detached headless host that owns one run.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import replace

from . import diagnostics
from .bootstrap.compatibility import Compatibility
from .bootstrap.discovery import ProjectDiscovery, ProjectDiscoveryError
from .bootstrap.preflight import Preflight
from .services.file_view import FileViewError, build_envelope, envelope_json
from .services.git import GitService
from .services.integration_installer import IntegrationInstaller
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
    subcommands = parser.add_subparsers(dest="command")
    context = subcommands.add_parser(
        "context",
        help="Print the versioned read envelope of the current run as JSON.",
    )
    context.add_argument(
        "--json",
        action="store_true",
        help="Emit the JSON envelope (the only output shape this command produces).",
    )
    context.add_argument(
        "--file",
        metavar="RELATIVE_PATH",
        help="Also read one Feature File, bounded to the UI's preview limit.",
    )
    subcommands.add_parser("install", help="Install/update the frontend artifacts.")
    serve = subcommands.add_parser("serve", help="Start the detached headless host.")
    serve.add_argument(
        "--foreground",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def _discover(args) -> tuple[object | None, int]:
    try:
        return ProjectDiscovery().discover(args.project), 0
    except ProjectDiscoveryError as exc:
        print(f"workflow-cockpit: {exc}", file=sys.stderr)
        return None, 2


def _run_context(args) -> int:
    project, code = _discover(args)
    if project is None:
        return code
    try:
        view = build_envelope(project.root, file_path=args.file)
    except FileViewError as exc:
        print(f"workflow-cockpit: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(envelope_json(view))
    return 0


def _run_install(args) -> int:
    project, code = _discover(args)
    if project is None:
        return code
    report = IntegrationInstaller(project.root).install()
    for line in report.lines():
        print(line)
    for failure in report.failures:
        _LOG.warning("artifact %s failed: %s", failure.artifact, failure.reason)
    return 0


def _run_serve(args) -> int:
    project, code = _discover(args)
    if project is None:
        return code
    from .host.launcher import launch, serve_foreground

    if args.foreground:
        return serve_foreground(project.root, explicit_executable=args.specify)
    return launch(project.root, explicit_executable=args.specify)


def _run_tui(args) -> int:
    project, code = _discover(args)
    if project is None:
        return code
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

    install = IntegrationInstaller(project.root).install()
    for outcome in install.outcomes:
        _LOG.log(
            logging.INFO if outcome.ok else logging.WARNING,
            "frontend artifact %s: %s",
            outcome.artifact,
            outcome.outcome,
        )

    CockpitApp(preflight, session_factory, style=style).run()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    diagnostics.configure()
    args = build_parser().parse_args(argv)
    if args.command == "context":
        return _run_context(args)
    if args.command == "install":
        return _run_install(args)
    if args.command == "serve":
        return _run_serve(args)
    return _run_tui(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
