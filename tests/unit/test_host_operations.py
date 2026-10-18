"""Owner-view operations: TUI-equivalent surfaces, refusals, serialisation."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from tests.fakes import FakeSession
from tests.fixtures import run_trees as rt
from workflow_cockpit.host import protocol as p
from workflow_cockpit.host.lifetime import HostLifetime
from workflow_cockpit.host.operations import HostOperations
from workflow_cockpit.services.snapshot import GateSnapshot, GateState


def gate(state: GateState = GateState.READY, token: str | None = "token-1") -> GateSnapshot:
    return GateSnapshot(
        runtime_step_id="review",
        step_id="review",
        message="Review it",
        options=("approve", "reject"),
        state=state,
        token=token,
    )


class HostOperationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".specify").mkdir(parents=True, exist_ok=True)
        self.session = FakeSession()
        self.session.project_root = self.root
        self.lifetime = HostLifetime()
        self.ops = HostOperations(
            self.session,
            project_root=self.root,
            lifetime=self.lifetime,
            owner_id="test-owner",
        )

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def dispatch(self, op, args=None):
        return await self.ops.dispatch(op, args)

    async def refusal(self, op, args=None) -> p.HostError:
        with self.assertRaises(p.HostError) as caught:
            await self.ops.dispatch(op, args)
        return caught.exception

    # -- read-only surfaces ---------------------------------------------

    async def test_list_matches_the_workflow_listing(self):
        result = await self.dispatch("list")
        self.assertEqual([entry["id"] for entry in result["workflows"]], ["demo"])

    async def test_validate_matches_the_tui_validation(self):
        result = await self.dispatch("validate", {"workflow_id": "demo", "values": {"spec": ""}})
        self.assertFalse(result["valid"])
        self.assertIn("spec", result["errors"])
        ok = await self.dispatch("validate", {"workflow_id": "demo", "values": {"spec": "x"}})
        self.assertTrue(ok["valid"])

    async def test_status_reports_host_claim_and_run(self):
        result = await self.dispatch("status")
        self.assertEqual(result["host"]["state"], "starting")
        self.assertEqual(result["claim"], "none")
        self.assertEqual(result["run"]["run_id"], self.session.run_id)

    async def test_gate_reports_message_options_token_and_ledger(self):
        self.session.gate = gate()
        result = await self.dispatch("gate")
        payload = result["gate"]
        self.assertEqual(payload["message"], "Review it")
        self.assertEqual(payload["options"], ["approve", "reject"])
        self.assertEqual(payload["token"], "token-1")
        self.assertEqual(payload["ledger"]["state"], "ready")
        self.assertTrue(payload["selectable"])

    async def test_gate_without_an_open_gate_is_a_structured_refusal(self):
        error = await self.refusal("gate")
        self.assertEqual(error.code, p.GATE_NOT_OPEN)

    # -- start ----------------------------------------------------------

    async def test_start_is_refused_over_a_non_terminal_current_run(self):
        rt.live_flat(self.root, status="running")
        error = await self.refusal("start", {"workflow_id": "demo", "values": {"spec": "x"}})
        self.assertEqual(error.code, p.RUN_IN_PROGRESS)
        self.assertIn(rt.RUN_ID, error.message)
        self.assertIn("adopt", error.action)
        self.assertEqual(error.details["run_id"], rt.RUN_ID)
        self.assertFalse(self.session.started)

    async def test_start_proceeds_with_no_current_run(self):
        rt.no_run(self.root)
        result = await self.dispatch("start", {"workflow_id": "demo", "values": {"spec": "x"}})
        self.assertTrue(self.session.started)
        self.assertEqual(result["run"]["run_id"], self.session.run_id)

    # -- decide ---------------------------------------------------------

    async def test_decide_rejects_an_undeclared_option_and_keeps_the_gate_open(self):
        self.session.gate = gate()
        error = await self.refusal("decide", {"option": "maybe", "token": "token-1"})
        self.assertEqual(error.code, p.UNDECLARED_OPTION)
        self.assertEqual(error.details["options"], ["approve", "reject"])
        self.assertEqual(self.session.gate.state, GateState.READY)
        self.assertEqual(self.session.decisions, [])

    async def test_decide_rejects_a_stale_token(self):
        self.session.gate = gate()
        error = await self.refusal("decide", {"option": "approve", "token": "old"})
        self.assertEqual(error.code, p.STALE_TOKEN)
        self.assertEqual(self.session.decisions, [])

    async def test_decide_applies_a_declared_option(self):
        self.session.gate = gate()
        result = await self.dispatch("decide", {"option": "approve", "token": "token-1"})
        self.assertEqual(self.session.decisions, ["approve"])
        self.assertEqual(result["option"], "approve")

    async def test_near_simultaneous_decides_serialise(self):
        self.session.gate = gate(token="token-2")
        results = await asyncio.gather(
            self.ops.dispatch("decide", {"option": "approve", "token": "token-2"}),
            self.ops.dispatch("decide", {"option": "approve", "token": "token-2"}),
            return_exceptions=True,
        )
        successes = [r for r in results if not isinstance(r, Exception)]
        refusals = [r for r in results if isinstance(r, p.HostError)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(refusals), 1)
        self.assertIn(refusals[0].code, (p.GATE_NOT_OPEN, p.STALE_TOKEN))
        self.assertEqual(self.session.decisions, ["approve"])

    # -- abort / adopt / resume -----------------------------------------

    async def test_abort_reports_the_bounded_best_effort_result(self):
        result = await self.dispatch("abort")
        self.assertTrue(self.session.aborted)
        self.assertTrue(result["abort"]["signalled"])
        self.assertTrue(result["abort"]["reaped"])

    async def test_adopt_of_a_stale_claim_recovers_without_signalling(self):
        result = await self.dispatch("adopt", {"run_id": "cockpit-stale"})
        self.assertIsNotNone(result["run"])
        self.assertEqual(self.session.adopted_run, "cockpit-stale")
        self.assertFalse(self.session.aborted)

    async def test_adopt_of_a_live_foreign_claim_is_refused(self):
        def refuse(_run_id):
            raise RuntimeError("Another live Cockpit owns this run; refusing to adopt it.")

        self.session.adopt = refuse
        error = await self.refusal("adopt", {"run_id": "cockpit-foreign"})
        self.assertEqual(error.code, p.CLAIM_LIVE_FOREIGN)
        self.assertIn("cockpit-foreign", str(error.details))

    async def test_resume_is_flagged_user_only(self):
        self.session.adopted_run = "cockpit-adopted"
        self.session.status = "failed"
        status = await self.dispatch("status")
        token = status["resume"]["token"]
        self.assertTrue(status["resume"]["available"])
        result = await self.dispatch("resume", {"token": token})
        self.assertTrue(result["user_only"])
        self.assertEqual(self.session.resumed_tokens, [token])

    # -- errors ---------------------------------------------------------

    async def test_unknown_operation_is_a_structured_refusal(self):
        error = await self.refusal("nope")
        self.assertEqual(error.code, p.UNKNOWN_OP)

    async def test_missing_arguments_are_bad_requests(self):
        for op, args in (("start", {}), ("validate", {}), ("decide", {}), ("adopt", {})):
            with self.subTest(op=op):
                error = await self.refusal(op, args)
                self.assertEqual(error.code, p.BAD_REQUEST)


if __name__ == "__main__":
    unittest.main()
