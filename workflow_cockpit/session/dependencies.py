"""Semantic dependency groups for one Cockpit session.

The groups mirror the architecture layers: the fixed project/engine identity, the
non-lifecycle read/context collaborators, and the engine lifecycle owner with its
timing seam. Each group can be built from an environment and overridden per test
with ``dataclasses.replace``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..bootstrap.compatibility import CompatibilityResult
from ..engine.supervisor import EngineSupervisor
from ..services.context_index import ContextIndexWriter
from ..services.definition import WorkflowDefinitionResolver
from ..services.feature_review import FeatureReviewService
from ..services.git import GitService
from ..services.registry import WorkflowRegistry


@dataclass(frozen=True)
class CockpitEnvironment:
    """Fixed identity of the one project/worktree and the pinned engine."""

    project_root: Path
    compatibility: CompatibilityResult

    @property
    def executable(self) -> Path:
        return self.compatibility.executable


@dataclass(frozen=True)
class CockpitServices:
    """Non-lifecycle collaborators: catalog, definition, worktree, review, context."""

    registry: WorkflowRegistry
    resolver: WorkflowDefinitionResolver
    git: GitService
    review_source: FeatureReviewService
    context_writer: ContextIndexWriter

    @classmethod
    def for_environment(cls, environment: CockpitEnvironment) -> CockpitServices:
        root = environment.project_root
        return cls(
            registry=WorkflowRegistry(root),
            resolver=WorkflowDefinitionResolver(root),
            git=GitService(root),
            review_source=FeatureReviewService(root),
            context_writer=ContextIndexWriter(root),
        )


@dataclass(frozen=True)
class EngineRuntime:
    """The one lifecycle owner plus the timing seam used to observe and decide it."""

    supervisor: EngineSupervisor
    clock: Callable[[], float] = time.monotonic

    @classmethod
    def for_environment(
        cls,
        environment: CockpitEnvironment,
        clock: Callable[[], float] | None = None,
    ) -> EngineRuntime:
        return cls(
            supervisor=EngineSupervisor(environment.executable, environment.project_root),
            clock=clock or time.monotonic,
        )
