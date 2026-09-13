"""Coordination layer connecting the read model, engine, and presentation."""

from .cockpit_session import CockpitSession, SessionError, generate_run_id
from .polling import PollingLoop

__all__ = ["CockpitSession", "PollingLoop", "SessionError", "generate_run_id"]
