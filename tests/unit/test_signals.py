import time
import unittest
from types import SimpleNamespace

from tests.support import requires_posix
from workflow_cockpit.engine.supervisor import AbortResult
from workflow_cockpit.session.signals import SignalHandler


class FakeApp:
    def __init__(self) -> None:
        self.exits = 0

    def exit(self) -> None:
        self.exits += 1


class FakeSignalSession:
    def __init__(self, *, active=True, abort_result=None, abort_delay=0.0) -> None:
        self.run_id = "cockpit-signal" if active else None
        self.active = active
        self.aborts = 0
        self.abort_delay = abort_delay
        self.last_abort_result = None
        self._result = abort_result

    def snapshot(self):
        return SimpleNamespace(terminal=not self.active)

    def abort(self):
        self.aborts += 1
        if self.abort_delay:
            time.sleep(self.abort_delay)
        self.last_abort_result = self._result
        return self.snapshot()


@requires_posix
class SignalHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_run_aborts_once_and_exits(self):
        result = AbortResult(signalled=True, reaped=True, escalation="SIGINT")
        session = FakeSignalSession(active=True, abort_result=result)
        app = FakeApp()
        handler = SignalHandler(lambda: session, app).register()
        try:
            handler._on_signal()
            handler._on_signal()
            await handler._task
        finally:
            handler.close()
        self.assertEqual(session.aborts, 1)
        self.assertEqual(app.exits, 1)
        self.assertTrue(handler.shutting_down)
        self.assertIs(handler.last_result, result)

    async def test_inactive_run_exits_without_abort(self):
        session = FakeSignalSession(active=False)
        app = FakeApp()
        handler = SignalHandler(lambda: session, app).register()
        try:
            handler._on_signal()
            await handler._task
        finally:
            handler.close()
        self.assertEqual(session.aborts, 0)
        self.assertEqual(app.exits, 1)

    async def test_late_created_session_provider(self):
        app = FakeApp()
        state = {"session": None}
        handler = SignalHandler(lambda: state["session"], app).register()
        state["session"] = FakeSignalSession(active=True)
        try:
            handler._on_signal()
            await handler._task
        finally:
            handler.close()
        self.assertEqual(state["session"].aborts, 1)

    async def test_missing_session_exits_without_abort(self):
        app = FakeApp()
        handler = SignalHandler(lambda: None, app).register()
        try:
            handler._on_signal()
            await handler._task
        finally:
            handler.close()
        self.assertEqual(app.exits, 1)

    async def test_exhausted_cleanup_records_best_effort_result(self):
        result = AbortResult(signalled=True, reaped=False, escalation="SIGKILL")
        session = FakeSignalSession(active=True, abort_result=result)
        app = FakeApp()
        handler = SignalHandler(lambda: session, app).register()
        try:
            handler._on_signal()
            await handler._task
        finally:
            handler.close()
        self.assertFalse(result.ok)
        self.assertIs(handler.last_result, result)
        self.assertEqual(app.exits, 1)

    async def test_a_failing_abort_still_exits(self):
        class Broken(FakeSignalSession):
            def abort(self):
                raise RuntimeError("supervisor exploded")

        app = FakeApp()
        handler = SignalHandler(lambda: Broken(active=True), app).register()
        try:
            handler._on_signal()
            await handler._task
        finally:
            handler.close()
        self.assertEqual(app.exits, 1)
        self.assertIsNone(handler.last_result)

    async def test_snapshot_failure_still_attempts_abort(self):
        class BrokenSnapshot(FakeSignalSession):
            def snapshot(self):
                raise RuntimeError("state reader failed")

        session = BrokenSnapshot(active=True)
        app = FakeApp()
        handler = SignalHandler(lambda: session, app).register()
        try:
            handler._on_signal()
            await handler._task
        finally:
            handler.close()
        self.assertEqual(session.aborts, 1)
        self.assertEqual(app.exits, 1)

    async def test_close_removes_registrations_and_is_idempotent(self):
        app = FakeApp()
        handler = SignalHandler(lambda: None, app).register()
        self.assertEqual(len(handler.registered), 3)
        handler.close()
        self.assertEqual(handler.registered, ())
        handler.close()


if __name__ == "__main__":
    unittest.main()
