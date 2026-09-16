#!/usr/bin/env python3
"""An isolated Cockpit process for real signal-delivery tests.

It builds the real ``CockpitSession`` and ``CockpitApp`` against a temp project
and a long-running fake ``specify``, starts the run, then applies the same
``SignalHandler`` the shipped app installs. The test sends a catchable signal to
this process; the handler must abort and reap the owned engine group before the
process exits.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from pathlib import Path

from packaging.version import Version

from workflow_cockpit.bootstrap.compatibility import CompatibilityResult
from workflow_cockpit.services.git import GitService
from workflow_cockpit.session.cockpit_session import CockpitSession
from workflow_cockpit.session.dependencies import (
    CockpitEnvironment,
    CockpitServices,
    EngineRuntime,
)
from workflow_cockpit.ui import app as app_module
from workflow_cockpit.ui.app import CockpitApp
from workflow_cockpit.ui.screens.cockpit import CockpitScreen
from workflow_cockpit.ui.screens.preflight import PreflightScreen

#: Textual resolves a relative ``CSS_PATH`` against the defining module; keep the
#: shipped stylesheet even though this subclass lives in the test fixtures.
SHIPPED_STYLES = Path(app_module.__file__).with_name("styles.tcss")


class HarnessApp(CockpitApp):
    """Runs the shipped app's mount path but starts directly at the cockpit.

    Textual dispatches a mount handler for every class in the MRO, so
    ``CockpitApp.on_mount`` still installs the real ``SignalHandler`` even though
    this subclass pushes the cockpit screen instead of preflight.
    """

    CSS_PATH = str(SHIPPED_STYLES)
    ready_path: Path | None = None

    def push_screen(self, screen, *args, **kwargs):
        if isinstance(screen, PreflightScreen):
            return None
        return super().push_screen(screen, *args, **kwargs)

    def on_mount(self) -> None:
        self.push_screen(CockpitScreen(self.session))
        # Fire after the base mount handler has installed the signal handler.
        self.set_timer(0.2, self._mark_ready)

    def _mark_ready(self) -> None:
        if self.ready_path is not None:
            self.ready_path.write_text("ready", encoding="utf-8")


def main() -> int:
    project = Path(sys.argv[1])
    fake = Path(sys.argv[2])
    record = Path(sys.argv[3])
    ready = Path(sys.argv[4])

    compatibility = CompatibilityResult(
        executable=fake,
        version=Version("1.0.0"),
        raw="specify 1.0.0",
        prerelease=False,
        tested_range=">=1.0,<2.0",
    )
    environment = CockpitEnvironment(project, compatibility)
    services = replace(CockpitServices.for_environment(environment), git=GitService(project))
    engine = EngineRuntime.for_environment(environment, clock=time.monotonic)
    session = CockpitSession(environment, services=services, engine=engine)
    session.select("demo")
    session.start({"spec": "signals"})

    supervisor = session._supervisor
    proc = supervisor._proc
    record.write_text(
        json.dumps(
            {
                "run_id": session.run_id,
                "engine_pid": proc.pid if proc is not None else None,
                "engine_pgid": supervisor._pgid,
            }
        ),
        encoding="utf-8",
    )

    HarnessApp.ready_path = ready
    app = HarnessApp(preflight=None, session_factory=lambda result: session)
    app.session = session
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
