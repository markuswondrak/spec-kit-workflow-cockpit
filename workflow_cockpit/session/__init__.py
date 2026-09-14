"""Coordination layer connecting the read model, engine, and presentation."""

from .cockpit_session import CockpitSession, SessionError, generate_run_id
from .gate_decision import GateDecisionCoordinator, GateDecisionError
from .polling import PollingLoop

__all__ = [
    "CockpitSession",
    "GateDecisionCoordinator",
    "GateDecisionError",
    "PollingLoop",
    "SessionError",
    "generate_run_id",
]
