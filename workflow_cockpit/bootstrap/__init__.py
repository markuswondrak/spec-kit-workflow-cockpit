"""Bootstrap and environment discovery for the Cockpit."""

from .compatibility import Compatibility, CompatibilityError, CompatibilityResult
from .discovery import ProjectDiscovery, ProjectDiscoveryError, ProjectInfo
from .preflight import CheckResult, Preflight, PreflightReport

__all__ = [
    "CheckResult",
    "Compatibility",
    "CompatibilityError",
    "CompatibilityResult",
    "Preflight",
    "PreflightReport",
    "ProjectDiscovery",
    "ProjectDiscoveryError",
    "ProjectInfo",
]
