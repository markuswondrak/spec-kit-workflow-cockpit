"""The host over a real Unix socket: dispatch, refusals, events, lifetime."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.fakes import FakeGit, FakeReviewService, FakeSession, FakeSupervisor
from tests.fixtures import run_trees as rt
from tests.support import compatibility_result, write_registry, write_run, write_workflow
from workflow_cockpit.host import protocol as p
from workflow_cockpit.host.lifetime import HostLifetime
from workflow_cockpit.host.operations import HostOperations
from workflow_cockpit.host.server import (
    AF_UNIX_MAX_PATH,
    HostBindError,
    HostServer,
    check_socket_path,
)
from workflow_cockpit.services.run_claim import RunClaimStore
from workflow_cockpit.services.snapshot import GateSnapshot, GateState
from workflow_cockpit.session.cockpit_session import CockpitSession
from workflow_cockpit.session.dependencies import (
    CockpitEnvironment,
    CockpitServices,
    EngineRuntime,
)


def gate(state: GateState = GateState.READY, token: str | None = "token-1") -> GateSnapshot:
    return GateSnapshot(
        runtime_step_id="review",
        step_id="review",
        message="Review it",
        options=("approve", "reject"),
        state=state,
        token=token,
    )


class SocketPathTests(unittest.TestCase):
    def test_a_path_within_the_bound_is_accepted(self):
        check_socket_path(Path("/tmp/short/.workflow-cockpit.sock"))

    def test_an_over_long_path_is_refused_structurally(self):
        with self.assertRaises(HostBindError) as caught:
            check_socket_path(Path("/" + "x" * AF_UNIX_MAX_PATH + "/.workflow-cockpit.sock"))
        self.assertEqual(caught.exception.error.code, p.SOCKET_PATH_TOO_LONG)


class HostSocketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify").mkdir(parents=True, exist_ok=True)
        self.session = FakeSession()
        self.session.project_root = self.root
        self.lifetime = HostLifetime(grace_seconds=0.2)
        self.ops = HostOperations(
            self.session,
            project_root=self.root,
            lifetime=self.lifetime,
            owner_id="test-owner",
        )
        self.server = HostServer(
            project_root=self.root,
            operations=self.ops,
            session=self.session,
            lifetime=self.lifetime,
            poll_seconds=0.02,
        )
        self.task: asyncio.Task | None = None

    async def asyncTearDown(self):
        await self.stop()
        self.tmp.cleanup()

    async def start(self) -> None:
        self.task = asyncio.create_task(self.server.serve())
        for _ in range(400):
            if self.server.socket_path.exists():
                try:
                    await self.call("status")
                except OSError:
                    pass
                else:
                    return
            await asyncio.sleep(0.01)
        raise AssertionError("the host socket never became ready")

    async def stop(self) -> None:
        if self.task is None:
            return
        self.server.request_stop()
        try:
            await asyncio.wait_for(self.task, timeout=3)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self.task.cancel()
        self.task = None

    async def connect(self):
        return await asyncio.open_unix_connection(str(self.server.socket_path))

    async def call(self, op, args=None, *, id="1") -> dict:
        reader, writer = await self.connect()
        try:
            writer.write(p.encode(p.request(op, args, id=id)))
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=3)
        finally:
            writer.close()
        return p.decode(line)

    # -- dispatch -------------------------------------------------------

    async def test_status_answers_with_a_versioned_response(self):
        await self.start()
        response = await self.call("status")
        self.assertTrue(response["ok"])
        self.assertEqual(response["id"], "1")
        self.assertEqual(response["protocol_version"], p.PROTOCOL_VERSION)
        self.assertEqual(response["result"]["host"]["pid"], os.getpid())

    async def test_unknown_operation_is_refused_structurally(self):
        await self.start()
        response = await self.call("nope")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], p.UNKNOWN_OP)

    async def test_malformed_line_is_a_bad_request_and_the_connection_survives(self):
        await self.start()
        reader, writer = await self.connect()
        try:
            writer.write(b"{not json}\n")
            await writer.drain()
            first = p.decode(await asyncio.wait_for(reader.readline(), timeout=3))
            self.assertEqual(first["error"]["code"], p.BAD_REQUEST)
            self.assertIsNone(first["id"])
            writer.write(p.encode(p.request("status", id="2")))
            await writer.drain()
            second = p.decode(await asyncio.wait_for(reader.readline(), timeout=3))
            self.assertTrue(second["ok"])
            self.assertEqual(second["id"], "2")
        finally:
            writer.close()

    async def test_correlation_id_is_echoed_verbatim(self):
        await self.start()
        response = await self.call("status", id="req-42")
        self.assertEqual(response["id"], "req-42")

    # -- bind uniqueness -------------------------------------------------

    async def test_second_host_is_refused_and_the_first_is_unaffected(self):
        await self.start()
        second = HostServer(
            project_root=self.root,
            operations=self.ops,
            session=self.session,
            lifetime=HostLifetime(),
        )
        with self.assertRaises(HostBindError) as caught:
            second.bind()
        self.assertEqual(caught.exception.error.code, p.HOST_ALREADY_RUNNING)
        response = await self.call("status")
        self.assertTrue(response["ok"])

    # -- start refusal ---------------------------------------------------

    async def test_start_over_a_non_terminal_current_run_is_refused(self):
        rt.live_flat(self.root, status="running")
        await self.start()
        response = await self.call("start", {"workflow_id": "demo", "values": {"spec": "x"}})
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], p.RUN_IN_PROGRESS)
        self.assertEqual(response["error"]["details"]["run_id"], rt.RUN_ID)
        self.assertIn("adopt", response["error"]["action"])

    # -- reconnect -------------------------------------------------------

    async def test_disconnect_and_reconnect_keep_the_run_and_step(self):
        self.session.run_id = "cockpit-run-1"
        self.session.status = "running"
        self.session.current_step_id = "prepare"
        await self.start()
        first = await self.call("status")
        second = await self.call("status")
        self.assertEqual(first["result"]["run"]["run_id"], "cockpit-run-1")
        self.assertEqual(second["result"]["run"]["current_step_id"], "prepare")

    # -- decide ----------------------------------------------------------

    async def test_decide_refusals_and_application(self):
        self.session.gate = gate()
        await self.start()
        undeclared = await self.call("decide", {"option": "maybe", "token": "token-1"})
        self.assertEqual(undeclared["error"]["code"], p.UNDECLARED_OPTION)
        self.assertEqual(undeclared["error"]["details"]["options"], ["approve", "reject"])
        applied = await self.call("decide", {"option": "approve", "token": "token-1"})
        self.assertTrue(applied["ok"])
        self.assertEqual(self.session.decisions, ["approve"])

    # -- events ----------------------------------------------------------

    async def test_events_are_delivered_in_order(self):
        await self.start()
        reader, writer = await self.connect()
        try:
            # Both changes land in one poll tick, so the fan-out order is fixed.
            self.session.status = "paused"
            self.session.gate = gate()
            events = []
            for _ in range(40):
                line = await asyncio.wait_for(reader.readline(), timeout=3)
                message = p.decode(line)
                if "event" in message:
                    events.append(message)
                if len(events) >= 2:
                    break
            self.assertEqual([message["event"] for message in events], [p.STATUS_CHANGED, p.GATE_OPEN])
            sequences = [message["seq"] for message in events]
            self.assertEqual(sequences, sorted(sequences))
            self.assertEqual(len(set(sequences)), len(sequences))
            self.assertTrue(all(message["protocol_version"] == p.PROTOCOL_VERSION for message in events))
            self.assertTrue(all("id" not in message for message in events))
        finally:
            writer.close()

    # -- lifetime --------------------------------------------------------

    async def test_terminal_run_releases_the_host(self):
        self.session.status = "success"
        # A terminal run releases on the first tick, so there is no window in
        # which a client can be answered; the task itself must complete.
        self.task = asyncio.create_task(self.server.serve())
        await asyncio.wait_for(self.task, timeout=3)
        self.task = None
        self.assertTrue(self.session.closed)
        self.assertFalse(self.server.socket_path.exists())


class TerminalReleaseTests(unittest.IsolatedAsyncioTestCase):
    """A real session releases its durable claim when the host exits."""

    async def test_terminal_run_releases_the_claim_and_removes_the_socket(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        write_workflow(root)
        write_registry(root)
        supervisor = FakeSupervisor()
        environment = CockpitEnvironment(root, compatibility_result("1.0.0"))
        services = replace(
            CockpitServices.for_environment(environment),
            git=FakeGit(),
            review_source=FakeReviewService(),
        )
        engine = replace(
            EngineRuntime.for_environment(environment, clock=lambda: 10.0),
            supervisor=supervisor,
        )
        session = CockpitSession(environment, services=services, engine=engine)
        session.select("demo")
        snapshot = session.start({"spec": "search"})
        run_dir = root / ".specify" / "workflows" / "runs" / snapshot.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        session.snapshot()
        claims = RunClaimStore(root)
        self.assertIsNotNone(claims.read(snapshot.run_id))
        write_run(root, snapshot.run_id, status="completed")
        supervisor.finish(exit_code=0)

        lifetime = HostLifetime(grace_seconds=0.2)
        operations = HostOperations(
            session,
            project_root=root,
            lifetime=lifetime,
            owner_id=session.owner_id,
        )
        server = HostServer(
            project_root=root,
            operations=operations,
            session=session,
            lifetime=lifetime,
            poll_seconds=0.02,
        )
        task = asyncio.create_task(server.serve())
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError as exc:
            task.cancel()
            raise AssertionError("the host never released a terminal run") from exc
        self.assertIsNone(claims.read(snapshot.run_id))
        self.assertFalse(server.socket_path.exists())
        self.assertEqual(lifetime.state, "exited")


if __name__ == "__main__":
    unittest.main()
