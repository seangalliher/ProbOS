"""Build Queue — persistent queue for automated builder dispatch (AD-371)."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.cognitive.builder import BuildResult, BuildSpec

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Valid status transitions
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"dispatched", "failed"},
    "dispatched": {"building", "failed"},
    "building": {"reviewing", "failed"},
    "reviewing": {"merged", "failed"},
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class QueuedBuild:
    """A build spec tracked through the dispatch lifecycle."""

    id: str
    spec: BuildSpec
    status: str = "queued"
    priority: int = 5
    created_at: float = 0.0
    dispatched_at: float | None = None
    completed_at: float | None = None
    worktree_path: str = ""
    builder_id: str = ""
    result: BuildResult | None = None
    error: str = ""
    file_footprint: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# BuildQueue
# ---------------------------------------------------------------------------


class BuildQueue:
    """Persistent queue of builds awaiting execution."""

    def __init__(self) -> None:
        self._builds: list[QueuedBuild] = []

    # -- enqueue / dequeue ---------------------------------------------------

    def enqueue(
        self,
        spec: BuildSpec,
        priority: int = 5,
        file_footprint: list[str] | None = None,
    ) -> QueuedBuild:
        """Add a spec to the queue."""
        build = QueuedBuild(
            id=uuid.uuid4().hex[:12],
            spec=spec,
            priority=priority,
            created_at=time.monotonic(),
            file_footprint=list(file_footprint) if file_footprint is not None else list(spec.target_files),
        )
        self._builds.append(build)
        logger.info("build-queue enqueue id=%s title=%r priority=%d", build.id, spec.title, priority)
        return build

    def dequeue(self) -> QueuedBuild | None:
        """Get the highest-priority queued item (lowest number, FIFO within same priority)."""
        queued = [b for b in self._builds if b.status == "queued"]
        if not queued:
            return None
        # Sort by priority (ascending), then by created_at (ascending = FIFO)
        queued.sort(key=lambda b: (b.priority, b.created_at))
        return queued[0]

    def peek(self) -> QueuedBuild | None:
        """Like dequeue but doesn't affect ordering."""
        return self.dequeue()

    # -- status updates ------------------------------------------------------

    def update_status(self, build_id: str, status: str, **kwargs: Any) -> bool:
        """Update status and any additional fields. Returns False if invalid transition."""
        build = self.get(build_id)
        if build is None:
            return False
        valid = _VALID_TRANSITIONS.get(build.status, set())
        if status not in valid:
            logger.warning(
                "build-queue invalid transition id=%s %s→%s",
                build_id, build.status, status,
            )
            return False
        old_status = build.status
        build.status = status
        for key, value in kwargs.items():
            if hasattr(build, key):
                setattr(build, key, value)
        logger.info("build-queue status id=%s %s→%s", build_id, old_status, status)
        return True

    # -- queries -------------------------------------------------------------

    def get(self, build_id: str) -> QueuedBuild | None:
        """Get a queued build by ID."""
        for b in self._builds:
            if b.id == build_id:
                return b
        return None

    def get_by_status(self, status: str) -> list[QueuedBuild]:
        """Get all builds with a given status."""
        return [b for b in self._builds if b.status == status]

    def get_all(self) -> list[QueuedBuild]:
        """Get all builds regardless of status."""
        return list(self._builds)

    # -- cancel --------------------------------------------------------------

    def cancel(self, build_id: str) -> bool:
        """Cancel a queued build. Returns False if not in queued status."""
        build = self.get(build_id)
        if build is None or build.status != "queued":
            return False
        build.status = "failed"
        build.error = "cancelled"
        build.completed_at = time.monotonic()
        logger.info("build-queue cancel id=%s", build_id)
        return True

    # -- conflict detection --------------------------------------------------

    def has_footprint_conflict(self, footprint: list[str]) -> bool:
        """Check if any active build has overlapping file footprint."""
        fp_set = set(footprint)
        for b in self._builds:
            if b.status in ("dispatched", "building"):
                if fp_set & set(b.file_footprint):
                    return True
        return False

    # -- properties ----------------------------------------------------------

    @property
    def active_count(self) -> int:
        """Number of builds in dispatched/building status."""
        return sum(1 for b in self._builds if b.status in ("dispatched", "building"))
