"""AD-865: Route a resolved crew sub-task through the department chief.

AD-864's :class:`~probos.cognitive.crew_assignment.AssignmentDecision` resolves a
sub-task straight to a worker ``agent_id``. AD-865 makes the org chart
load-bearing: the worker's **department chief** is the delegating authority.
:class:`CrewDelegator` walks the chain of command for the worker's post, finds
the in-department superior whose ``authority_over`` includes the worker's post,
and issues a validated :class:`~probos.cognitive.orders.Order` to the worker's
post via :class:`~probos.cognitive.orders.OrderManager`. ``OrderManager`` owns
the authority validation — an out-of-chain delegation returns ``None`` and we
honor that rejection rather than forcing the work.

This is a **pure decision** sibling of AD-864: no ``WorkItem`` mutation, no
LLM call, no order auto-acknowledgement. ``delegate`` never raises — every
collaborator failure honest-degrades to direct assignment (the worker still
gets the work; we just couldn't route it through a chief). The runtime
orchestrator that reads these decisions and mutates ``WorkItem.assigned_to`` is
AD-867, out of scope here. ``chief_agent_id``/``order_id`` are recorded as
provenance for that AD.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.cognitive.crew_assignment import AssignmentDecision
    from probos.cognitive.orders import OrderManager
    from probos.ontology import VesselOntologyService
    from probos.ontology.models import Post
    from probos.substrate.registry import AgentRegistry

logger = logging.getLogger(__name__)

# Delegation reason constants — why a sub-task routed (or didn't).
_REASON_DELEGATED = "delegated_via_chief"
_REASON_DIRECT_NO_CHIEF = "direct_no_chief"
_REASON_OUT_OF_CHAIN = "out_of_chain"
_REASON_SELF_ASSIGNED = "self_assigned"
_REASON_UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class DelegationDecision:
    """The outcome of routing one :class:`AssignmentDecision` through a chief.

    ``worker_agent_id`` is always the ultimate ``WorkItem.assigned_to`` (carried
    through every branch except ``unresolved``). ``chief_agent_id`` and
    ``order_id`` are provenance for AD-867: present only when a chief was
    resolved / an :class:`Order` was issued. ``delegated`` is ``True`` only when
    an in-chain ``Order`` was actually issued. ``reason`` records the branch:

    - ``"delegated_via_chief"`` — chief issued a validated Order to the worker.
    - ``"self_assigned"`` — worker is itself a leader; no in-dept superior.
    - ``"out_of_chain"`` — ``OrderManager`` rejected the delegation (None).
    - ``"direct_no_chief"`` — no post / no chief / chief unwired / no manager.
    - ``"unresolved"`` — upstream AD-864 produced no worker (``agent_id`` None).
    """

    spec_id: str
    chief_agent_id: str | None
    worker_agent_id: str | None
    order_id: str | None
    delegated: bool
    reason: str


class CrewDelegator:
    """Route a resolved worker sub-task through its department chief.

    Pure decision: reads the live registry and ontology and consults
    ``OrderManager`` (which owns ``authority_over`` validation); writes no
    ``WorkItem`` state. Honest-degrades to direct assignment instead of raising,
    since the caller sits on the dispatch path.
    """

    def __init__(
        self,
        *,
        ontology: "VesselOntologyService",
        order_manager: "OrderManager | None",
        agent_registry: "AgentRegistry",
    ) -> None:
        self._ontology = ontology
        self._order_manager = order_manager
        self._agent_registry = agent_registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def delegate(self, decision: "AssignmentDecision") -> DelegationDecision:
        """Route ``decision``'s worker through its department chief.

        Never raises: any unexpected collaborator error is Tier-2
        log-and-degraded to direct assignment so a malformed decision cannot
        crash dispatch.
        """
        spec_id = decision.spec_id
        worker_agent_id = decision.agent_id
        if worker_agent_id is None:
            return DelegationDecision(
                spec_id=spec_id,
                chief_agent_id=None,
                worker_agent_id=None,
                order_id=None,
                delegated=False,
                reason=_REASON_UNRESOLVED,
            )

        try:
            worker_type = self._worker_agent_type(worker_agent_id)
            worker_post = (
                self._ontology.get_post_for_agent(worker_type) if worker_type else None
            )
            if worker_post is None:
                # No billet for the worker — nobody to route through.
                return self._direct(spec_id, worker_agent_id)

            chief_post = self._find_chief_post(worker_post)
            if chief_post is None:
                # No in-department superior holds authority over the worker.
                if worker_post.authority_over:
                    # Worker is itself a leader; it keeps the leaf task.
                    return DelegationDecision(
                        spec_id=spec_id,
                        chief_agent_id=None,
                        worker_agent_id=worker_agent_id,
                        order_id=None,
                        delegated=False,
                        reason=_REASON_SELF_ASSIGNED,
                    )
                return self._direct(spec_id, worker_agent_id)

            chief_agent_id = self._resolve_post_agent(chief_post.id)
            if chief_agent_id is None:
                # Chief post exists but is unwired (no live agent_id).
                return self._direct(spec_id, worker_agent_id)
            if self._order_manager is None:
                # No manager to govern the delegation — degrade, keep provenance.
                return self._direct(spec_id, worker_agent_id, chief_agent_id)

            directive = self._directive_for(decision)
            order = self._order_manager.issue_order(
                from_agent_id=chief_agent_id,
                to_post_id=worker_post.id,
                directive=directive,
            )
            if order is None:
                # OrderManager rejected the delegation (out_of_chain etc.).
                # Honor it: the worker still keeps the work directly.
                return DelegationDecision(
                    spec_id=spec_id,
                    chief_agent_id=chief_agent_id,
                    worker_agent_id=worker_agent_id,
                    order_id=None,
                    delegated=False,
                    reason=_REASON_OUT_OF_CHAIN,
                )
            return DelegationDecision(
                spec_id=spec_id,
                chief_agent_id=chief_agent_id,
                worker_agent_id=worker_agent_id,
                order_id=order.id,
                delegated=True,
                reason=_REASON_DELEGATED,
            )
        except Exception:  # Tier-2 log-and-degrade: dispatch path must not crash.
            logger.warning(
                "AD-865: delegation failed for spec=%s (worker=%s); "
                "degrading to direct assignment",
                spec_id,
                worker_agent_id,
                exc_info=True,
            )
            return self._direct(spec_id, worker_agent_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _direct(
        self,
        spec_id: str,
        worker_agent_id: str,
        chief_agent_id: str | None = None,
    ) -> DelegationDecision:
        """Honest-degrade: worker keeps the work, no Order issued."""
        return DelegationDecision(
            spec_id=spec_id,
            chief_agent_id=chief_agent_id,
            worker_agent_id=worker_agent_id,
            order_id=None,
            delegated=False,
            reason=_REASON_DIRECT_NO_CHIEF,
        )

    def _worker_agent_type(self, agent_id: str) -> str | None:
        agent = self._agent_registry.get(agent_id)
        if agent is None:
            return None
        return getattr(agent, "agent_type", None)

    def _find_chief_post(self, worker_post: "Post") -> "Post | None":
        """First in-department superior whose authority_over holds the worker post."""
        chain = self._ontology.get_chain_of_command(worker_post.id)
        for post in chain:
            if post.id == worker_post.id:
                continue
            if (
                post.department_id == worker_post.department_id
                and worker_post.id in (post.authority_over or [])
            ):
                return post
        return None

    def _resolve_post_agent(self, post_id: str) -> str | None:
        """Live agent_id of the first assignment wired to ``post_id``."""
        for assignment in self._ontology.get_agents_for_post(post_id):
            if assignment.agent_id is not None:
                return assignment.agent_id
        return None

    def _directive_for(self, decision: "AssignmentDecision") -> str:
        """Non-empty directive text for the Order (issue_order rejects blanks)."""
        directive = (decision.capability or decision.spec_id or "").strip()
        return directive or "delegated work item"
