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
from typing import TYPE_CHECKING, Any, Callable

from probos.events import EventType
from probos.ontology.models import Assignment, Post

if TYPE_CHECKING:
    from probos.cognitive.qualification import QualificationStore

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
        qualification_store: "QualificationStore | None" = None,  # AD-595d
    ) -> None:
        self._dept = department_service
        self._emit_event_fn = emit_event_fn
        self._qualification_store: "QualificationStore | None" = qualification_store  # AD-595d
        # Build title→post_id index for title-based resolution
        self._title_index: dict[str, str] = {}
        self._rebuild_title_index()

    def set_event_callback(
        self, emit_fn: Callable[[EventType, dict[str, Any]], None],
    ) -> None:
        """AD-595a: Set event emission callback (public API for late binding)."""
        self._emit_event_fn = emit_fn

    def set_qualification_store(self, store: Any) -> None:
        """AD-595d: Set qualification store for billet qualification checks."""
        self._qualification_store = store

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

    async def check_qualifications(
        self,
        billet_id: str,
        agent_type: str,
        agent_id: str = "",
        *,
        allow_untested: bool = True,
    ) -> tuple[bool, list[str]]:
        """AD-595d: Check if an agent meets a billet's qualification requirements.

        Parameters
        ----------
        billet_id : str
            Post identifier to check requirements for.
        agent_type : str
            Agent type — used to look up agent_id if not provided.
        agent_id : str
            Agent's sovereign/unique ID for qualification store lookup.
            If empty, looked up from current assignment.
        allow_untested : bool
            If True (default), agents with no test results for a required
            qualification are allowed through (cold-start tolerance).
            If False, missing test results count as failures (for promotion
            or re-qualification checks).

        Returns
        -------
        (qualified, missing) : tuple[bool, list[str]]
            True if all requirements met (or no requirements), plus list
            of missing/failed qualification test names.
        """
        post = self._dept.get_post(billet_id)
        if not post or not post.required_qualifications:
            return True, []

        if not self._qualification_store:
            # No store — can't check, allow by default
            return True, []

        # Resolve agent_id from assignment if not provided
        if not agent_id:
            assignment = self._dept.get_assignment_for_agent(agent_type)
            agent_id = assignment.agent_id if assignment and assignment.agent_id else ""

        if not agent_id:
            # Still no agent_id — can't look up results, allow by default
            return True, []

        missing: list[str] = []
        for test_name in post.required_qualifications:
            result = await self._qualification_store.get_latest(agent_id, test_name)
            if result is None:
                if not allow_untested:
                    missing.append(test_name)
                # else: cold start — no test taken yet, allow
            elif not result.passed:
                missing.append(test_name)

        return len(missing) == 0, missing

    async def assign_qualified(
        self,
        billet_id: str,
        agent_type: str,
        agent_id: str = "",
        callsign: str = "",
        *,
        allow_untested: bool = True,
    ) -> tuple[bool, list[str]]:
        """AD-595d: Check qualifications, then assign if qualified.

        Combines check_qualifications() + assign() in one call.
        If the agent doesn't meet requirements, the billet is NOT assigned.

        Parameters
        ----------
        billet_id, agent_type, agent_id, callsign :
            Same as assign() and check_qualifications().
        allow_untested : bool
            Passed through to check_qualifications(). Default True
            (cold-start tolerance).

        Returns
        -------
        (assigned, missing) : tuple[bool, list[str]]
            True if assigned, plus list of missing qualifications (empty
            if assigned, populated if rejected).
        """
        qualified, missing = await self.check_qualifications(
            billet_id, agent_type, agent_id, allow_untested=allow_untested,
        )
        if not qualified:
            logger.warning(
                "AD-595d: %s not qualified for billet %s — missing: %s",
                agent_type, billet_id, missing,
            )
            return False, missing

        result = self.assign(billet_id, agent_type, callsign=callsign)
        return result, []

    # ------------------------------------------------------------------
    # AD-595e: Qualification Gate Enforcement helpers
    # ------------------------------------------------------------------

    async def get_qualification_standing(
        self,
        agent_type: str,
        agent_id: str = "",
    ) -> dict[str, Any]:
        """AD-595e: Get qualification summary for an agent's billet.

        Returns a dict with pass_rate, missing qualifications, and whether
        the agent is qualified for their assigned billet. Used by
        CognitiveAgent for context injection.

        Graceful degradation: returns ``{"qualified": True, "standing": "unknown"}``
        if no store, no assignment, or no post.
        """
        default = {"qualified": True, "standing": "unknown", "missing": [], "pass_rate": 1.0}

        assignment = self._dept.get_assignment_for_agent(agent_type)
        if not assignment:
            return default

        post = self._dept.get_post(assignment.post_id)
        if not post or not post.required_qualifications:
            return {**default, "standing": "no_requirements"}

        if not self._qualification_store:
            return default

        if not agent_id and assignment.agent_id:
            agent_id = assignment.agent_id
        if not agent_id:
            return default

        # Check each required qualification
        passed = 0
        missing: list[str] = []
        for test_name in post.required_qualifications:
            result = await self._qualification_store.get_latest(agent_id, test_name)
            if result is None:
                # Untested — don't count as missing (cold-start tolerance)
                passed += 1
            elif result.passed:
                passed += 1
            else:
                missing.append(test_name)

        total = len(post.required_qualifications)
        pass_rate = passed / total if total > 0 else 1.0

        return {
            "qualified": len(missing) == 0,
            "standing": "qualified" if len(missing) == 0 else "deficient",
            "missing": missing,
            "pass_rate": pass_rate,
            "billet_id": assignment.post_id,
            "total_required": total,
        }

    async def check_role_qualifications(
        self,
        agent_type: str,
        agent_id: str,
        required_qualifications: list[str],
        *,
        allow_untested: bool = True,
    ) -> tuple[bool, list[str]]:
        """AD-595e: Check explicit qualification list (not billet-based).

        Used by BillRuntime for step-level qualification checks where
        the required qualifications come from the bill step definition,
        not the agent's billet.

        Returns
        -------
        (qualified, missing) : tuple[bool, list[str]]
        """
        if not required_qualifications:
            return True, []

        if not self._qualification_store:
            return True, []

        missing: list[str] = []
        for test_name in required_qualifications:
            result = await self._qualification_store.get_latest(agent_id, test_name)
            if result is None:
                if not allow_untested:
                    missing.append(test_name)
            elif not result.passed:
                missing.append(test_name)

        return len(missing) == 0, missing

    def assign(
        self,
        post_id: str,
        agent_type: str,
        callsign: str = "",
    ) -> bool:
        """Notify that an agent has been assigned to a billet.

        Validates the post exists, then emits BILLET_ASSIGNED. Does NOT
        mutate DepartmentService — the ontology already has the assignment.
        This is purely event emission for downstream consumers.

        Idempotent: safe to call multiple times for the same agent.

        If ``callsign`` is empty, falls back to the assignment's stored
        callsign from DepartmentService (set by naming ceremony or
        organization.yaml seed). This avoids polluting the event stream
        with agent_type strings when the real callsign is available.

        Parameters
        ----------
        post_id : str
            The post identifier from organization.yaml (e.g., "chief_engineer").
        agent_type : str
            The agent type filling the billet.
        callsign : str
            The agent's current callsign. Empty string means "look up from
            the assignment's stored callsign."

        Returns
        -------
        bool
            True if the post exists and event was emitted, False otherwise.
        """
        post = self._dept.get_post(post_id)
        if not post:
            logger.warning(
                "BilletRegistry.assign: unknown post_id %r for agent %s",
                post_id, agent_type,
            )
            return False

        # AD-595b: Fall back to the assignment's stored callsign if caller
        # didn't provide one, rather than polluting events with agent_type.
        if not callsign:
            assignment = self._dept.get_assignment_for_agent(agent_type)
            callsign = assignment.callsign if assignment else ""

        self._emit(EventType.BILLET_ASSIGNED, {
            "billet_id": post_id,
            "title": post.title,
            "department": post.department_id,
            "agent_type": agent_type,
            "callsign": callsign,
        })
        return True

    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Emit an event if the callback is set."""
        if self._emit_event_fn:
            self._emit_event_fn(event_type, data)
