"""Owner-view operations over the existing session services (FR-017/020).

The host does not re-implement lifecycle logic. Every operation delegates to the
same :class:`CockpitSession`, gate coordinator, adoption, and resume services the
TUI calls, so the host and the TUI can never disagree about what a decision or an
abort means. Mutating operations serialise on one asyncio lock, and every
blocking session call runs in a worker thread so the event loop stays responsive.

Refusals are structured: an operation raises :class:`HostError` with a code from
``contracts/host-protocol.md`` and an actionable message.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ..services.run_claim import ClaimState, RunClaimStore
from ..services.snapshot import GateSnapshot, GateState
from ..services.start_guard import StartGuard
from . import protocol as p
from .lifetime import HostLifetime


def run_summary(snapshot: Any) -> dict[str, Any] | None:
    """A bounded, JSON-safe view of one run snapshot."""
    if snapshot is None or not getattr(snapshot, "run_id", ""):
        return None
    return {
        "run_id": snapshot.run_id,
        "workflow_id": snapshot.workflow_id,
        "workflow_name": snapshot.workflow_name,
        "status": snapshot.status,
        "engine_status": snapshot.engine_status,
        "current_step_id": snapshot.current_step_id,
        "branch": snapshot.branch,
        "process_live": bool(snapshot.process_live),
        "adopted": bool(snapshot.adopted),
        "read_only": bool(snapshot.read_only),
    }


def gate_payload(gate: GateSnapshot | None) -> dict[str, Any] | None:
    """The open gate with exactly the declared options, its token, and its ledger."""
    if gate is None:
        return None
    return {
        "id": gate.step_id,
        "runtime_step_id": gate.runtime_step_id,
        "message": gate.message,
        "options": list(gate.options),
        "on_reject": gate.on_reject,
        "scope_path": [str(part) for part in gate.scope_path],
        "token": gate.token,
        "ledger": {
            "state": gate.state.value,
            "acknowledged": gate.acknowledged,
            "reason": gate.reason,
            "reason_kind": gate.reason_kind,
        },
        "selectable": bool(gate.selectable),
        "blocked": gate.state is GateState.BLOCKED,
    }


class HostOperations:
    """Dispatch owner-view operations onto one session."""

    def __init__(
        self,
        session: Any,
        *,
        project_root: Path | str,
        lifetime: HostLifetime | None = None,
        claims: RunClaimStore | None = None,
        owner_id: str | None = None,
        guard: StartGuard | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session
        self.project_root = Path(project_root)
        self.lifetime = lifetime
        self.claims = claims or RunClaimStore(self.project_root)
        self.owner_id = owner_id
        self.guard = guard or StartGuard(self.project_root)
        self._clock = clock
        self._lock = asyncio.Lock()

    async def dispatch(self, op: str, args: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Run one operation; mutating operations serialise on one lock."""
        if op not in p.OPERATIONS:
            raise p.HostError(
                p.UNKNOWN_OP,
                f"{op!r} is not a host operation.",
                "use one of: " + ", ".join(sorted(p.OPERATIONS)),
                {"op": op},
            )
        handler = getattr(self, f"_op_{op}")
        payload = dict(args or {})
        if op in p.MUTATING_OPERATIONS:
            async with self._lock:
                return await handler(payload)
        return await handler(payload)

    # -- read-only operations ------------------------------------------

    async def _op_list(self, args: Mapping[str, Any]) -> dict[str, Any]:
        entries = await asyncio.to_thread(self.session.list_workflows)
        return {
            "workflows": [
                {
                    "id": entry.id,
                    "name": entry.name,
                    "version": entry.version,
                    "description": entry.description,
                    "enabled": bool(entry.enabled),
                }
                for entry in entries
            ]
        }

    async def _op_validate(self, args: Mapping[str, Any]) -> dict[str, Any]:
        workflow_id = self._require_workflow_id(args)
        values = args.get("values")
        values = dict(values) if isinstance(values, Mapping) else {}
        await self._select(workflow_id)
        resolved, errors = await asyncio.to_thread(self.session.validate, values)
        return {
            "workflow_id": workflow_id,
            "values": resolved,
            "errors": errors,
            "valid": not errors,
        }

    async def _op_status(self, args: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = await asyncio.to_thread(self.session.snapshot)
        run_id = getattr(snapshot, "run_id", "") or None
        claim = self._claim_state(run_id)
        host = self.lifetime.snapshot() if self.lifetime is not None else {
            "state": "serving",
            "run": "none",
        }
        return {
            "host": host,
            "claim": claim,
            "run": run_summary(snapshot),
            "resume": self._resume_affordance(),
            "user_only": False,
        }

    async def _op_gate(self, args: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = await asyncio.to_thread(self.session.snapshot)
        gate = getattr(snapshot, "gate", None)
        if gate is None:
            raise p.HostError(
                p.GATE_NOT_OPEN,
                "The run is not at a declared gate.",
                "read status until the run pauses at a gate",
            )
        return {"gate": gate_payload(gate)}

    # -- mutating operations -------------------------------------------

    async def _op_start(self, args: Mapping[str, Any]) -> dict[str, Any]:
        workflow_id = self._require_workflow_id(args)
        refusal = self.guard.check()
        if refusal is not None:
            raise p.HostError(
                p.RUN_IN_PROGRESS,
                refusal.message,
                refusal.action,
                refusal.details(),
            )
        values = args.get("values")
        values = dict(values) if isinstance(values, Mapping) else {}
        await self._select(workflow_id)
        snapshot = await self._call(self.session.start, values)
        return {"run": run_summary(snapshot)}

    async def _op_decide(self, args: Mapping[str, Any]) -> dict[str, Any]:
        option = args.get("option")
        if not isinstance(option, str) or not option:
            raise p.HostError(p.BAD_REQUEST, "decide needs an 'option' string.", "send a declared option")
        token = args.get("token")
        token = token if isinstance(token, str) else None
        snapshot = await asyncio.to_thread(self.session.snapshot)
        gate = getattr(snapshot, "gate", None)
        if gate is None or gate.state is not GateState.READY:
            raise p.HostError(
                p.GATE_NOT_OPEN,
                "No gate is open for a decision.",
                "read gate until a declared gate is open",
            )
        if not token or token != gate.token:
            raise p.HostError(
                p.STALE_TOKEN,
                "The gate changed; this decision is stale and was not submitted.",
                "read gate again and decide with the current token",
            )
        if option not in gate.options:
            raise p.HostError(
                p.UNDECLARED_OPTION,
                f"{option!r} is not one of the gate's declared options.",
                "choose one of the declared options",
                {"options": list(gate.options)},
            )
        snapshot = await self._call(self.session.submit_decision, option, token)
        return {"run": run_summary(snapshot), "option": option}

    async def _op_abort(self, args: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = await self._call(self.session.abort)
        result = getattr(self.session, "last_abort_result", None)
        return {
            "run": run_summary(snapshot),
            "abort": {
                "signalled": bool(getattr(result, "signalled", False)),
                "reaped": bool(getattr(result, "reaped", False)),
                "escalation": getattr(result, "escalation", None),
            },
        }

    async def _op_adopt(self, args: Mapping[str, Any]) -> dict[str, Any]:
        run_id = args.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise p.HostError(p.BAD_REQUEST, "adopt needs a 'run_id' string.", "name the run to adopt")
        try:
            snapshot = await asyncio.to_thread(self.session.adopt, run_id)
        except Exception as exc:  # noqa: BLE001 - map every adoption refusal
            message = str(exc)
            code = p.CLAIM_LIVE_FOREIGN if "live Cockpit" in message else p.BAD_REQUEST
            raise p.HostError(
                code,
                message,
                "wait for the foreign owner to exit, or pick another run",
                {"run_id": run_id},
            ) from exc
        return {"run": run_summary(snapshot)}

    async def _op_resume(self, args: Mapping[str, Any]) -> dict[str, Any]:
        token = args.get("token")
        token = token if isinstance(token, str) else None
        decision = getattr(self.session, "resume_decision", lambda: None)()
        if decision is None or not getattr(decision, "available", False):
            reason = getattr(decision, "reason", "") or "This run cannot be resumed."
            raise p.HostError(p.BAD_REQUEST, reason, "adopt a failed run before resuming")
        snapshot = await self._call(self.session.resume_run, token)
        return {
            "run": run_summary(snapshot),
            "user_only": True,
            "reason": "Resuming a failed run is a user-only operation.",
        }

    def _resume_affordance(self) -> dict[str, Any] | None:
        """The projected resume affordance, so a frontend can read its token."""
        decision = getattr(self.session, "resume_decision", lambda: None)()
        if decision is None:
            return None
        return {
            "available": bool(getattr(decision, "available", False)),
            "reason": getattr(decision, "reason", ""),
            "step_id": getattr(decision, "step_id", None),
            "step_label": getattr(decision, "step_label", ""),
            "token": getattr(decision, "token", None),
        }

    # -- helpers --------------------------------------------------------

    def _require_workflow_id(self, args: Mapping[str, Any]) -> str:
        workflow_id = args.get("workflow_id")
        if not isinstance(workflow_id, str) or not workflow_id:
            raise p.HostError(
                p.BAD_REQUEST,
                "This operation needs a 'workflow_id' string.",
                "list workflows and pass one of their ids",
            )
        return workflow_id

    async def _select(self, workflow_id: str) -> None:
        try:
            await asyncio.to_thread(self.session.select, workflow_id)
        except Exception as exc:  # noqa: BLE001 - an unknown workflow is a bad request
            raise p.HostError(
                p.BAD_REQUEST,
                str(exc),
                "list workflows and pass one of their ids",
                {"workflow_id": workflow_id},
            ) from exc

    async def _call(self, func: Callable[..., Any], *args: Any) -> Any:
        try:
            return await asyncio.to_thread(func, *args)
        except p.HostError:
            raise
        except Exception as exc:  # noqa: BLE001 - a session refusal becomes structured
            raise p.HostError(p.BAD_REQUEST, str(exc), "read status and retry") from exc

    def _claim_state(self, run_id: str | None) -> str:
        if run_id is None:
            return ClaimState.NONE.value
        try:
            state = self.claims.claim_state(run_id, self.owner_id)
        except Exception:  # noqa: BLE001 - a claim read must not fail an operation
            return ClaimState.NONE.value
        return state.value if isinstance(state, ClaimState) else str(state)
