"""The headless host: the owner view over one run (US3).

Nothing in this package imports Textual, so the host, its protocol, and its
operations are testable without a running app (FR-033).
"""

from __future__ import annotations

from .lifetime import HostLifetime
from .operations import HostOperations
from .protocol import PROTOCOL_VERSION, HostError
from .server import SOCKET_NAME, HostServer

__all__ = [
    "HostError",
    "HostLifetime",
    "HostOperations",
    "HostServer",
    "PROTOCOL_VERSION",
    "SOCKET_NAME",
]
