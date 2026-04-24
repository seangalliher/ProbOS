"""AD-595a: BilletRegistry — authoritative billet-to-agent resolution.

Facade over DepartmentService that adds title-based resolution, roster
snapshots, and event infrastructure for billet changes. Follows the
Navy Watch Bill model: billets are permanent positions, agents rotate.

AD-595a provides the read-side API. Mutators (assign/vacate) are added
by AD-595b when the naming ceremony is wired.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from probos.events import EventType
from probos.ontology.models import Assignment, Post

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BilletHolder:
    """Snapshot of a billet and its current holder.

    Frozen to prevent accidental mutation that drifts from DepartmentService.
    """

    billet_id: str
    title: str
    department: str
    holder_agent_type: str | None
    holder_callsign: str | None
    holder_agent_id: str | None


class BilletRegistry:
    """Authoritative Watch Bill — resolves billets to current holders.

    Wraps DepartmentService for billet queries. Does not own the data —
    DepartmentService remains the source of truth for posts and assignments.

    Parameters
    ----------
    department_service : DepartmentService
        The underlying ontology department service.
    emit_event_fn : callable, optional
        Callback ``(EventType, dict) -> None`` for billet events.
    """

    def __init__(
        self,
        department_service: Any,
        emit_event_fn: Callable[[EventType, dict[str, Any]], None] | None = None,
    ) -> None:
        self._dept = department_service
        self._emit_event_fn = emit_event_fn
        # Build title→post_id index for title-based resolution
        self._title_index: dict[str, str] = {}
        self._rebuild_title_index()

    def set_event_callback(
        self, emit_fn: Callable[[EventType, dict[str, Any]], None],
    ) -> None:
        """AD-595a: Set event emission callback (public API for late binding)."""
        self._emit_event_fn = emit_fn

    def _rebuild_title_index(self) -> None:
        """Build lowercase title → post_id lookup from current posts."""
        self._title_index = {}
        for post in self._dept.get_posts():
            title_lower = post.title.lower()
            if title_lower in self._title_index:
                logger.warning(
                    "BilletRegistry: title collision for %r (posts %s and %s) — "
                    "title resolution will return the latter",
                    post.title, self._title_index[title_lower], post.id,
                )
            self._title_index[title_lower] = post.id

    def resolve(self, title_or_id: str) -> BilletHolder | None:
        """Resolve a billet title or post_id to its current holder.

        Accepts either a post_id ("chief_engineer") or a title
        ("Chief Engineer"). Case-insensitive for titles.

        Returns None if the billet does not exist.
        Returns a BilletHolder with holder fields as None if billet
        exists but is vacant.
        """
        # Try as post_id first
        post = self._dept.get_post(title_or_id)
        if not post:
            # Try as title (case-insensitive)
            post_id = self._title_index.get(title_or_id.lower())
            if post_id:
                post = self._dept.get_post(post_id)
        if not post:
            return None

        # Find holder
        assignments = self._dept.get_agents_for_post(post.id)
        holder = assignments[0] if assignments else None

        return BilletHolder(
            billet_id=post.id,
            title=post.title,
            department=post.department_id,
            holder_agent_type=holder.agent_type if holder else None,
            holder_callsign=holder.callsign if holder else None,
            holder_agent_id=holder.agent_id if holder else None,
        )

    def resolve_agent_type(self, title_or_id: str) -> str | None:
        """Convenience: resolve a billet to just the holder's agent_type."""
        holder = self.resolve(title_or_id)
        return holder.holder_agent_type if holder else None

    def resolve_callsign(self, title_or_id: str) -> str | None:
        """Convenience: resolve a billet to the holder's callsign.

        Returns None if the billet doesn't exist OR if the billet is vacant.
        Callers that need to distinguish should use resolve() directly.
        """
        holder = self.resolve(title_or_id)
        return holder.holder_callsign if holder else None

    def get_roster(self) -> list[BilletHolder]:
        """Return the full Watch Bill — all billets with current holders."""
        roster: list[BilletHolder] = []
        for post in self._dept.get_posts():
            assignments = self._dept.get_agents_for_post(post.id)
            holder = assignments[0] if assignments else None
            roster.append(BilletHolder(
                billet_id=post.id,
                title=post.title,
                department=post.department_id,
                holder_agent_type=holder.agent_type if holder else None,
                holder_callsign=holder.callsign if holder else None,
                holder_agent_id=holder.agent_id if holder else None,
            ))
        return roster

    def get_department_roster(self, department_id: str) -> list[BilletHolder]:
        """Return Watch Bill for a single department."""
        return [b for b in self.get_roster() if b.department == department_id]

    def refresh(self) -> None:
        """Rebuild the title index from current posts.

        Call after any bulk post changes. For AD-595a, posts are immutable
        after startup — this exists as a clean extension point for future
        runtime billet creation.
        """
        self._rebuild_title_index()

    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Emit an event if the callback is set."""
        if self._emit_event_fn:
            self._emit_event_fn(event_type, data)
