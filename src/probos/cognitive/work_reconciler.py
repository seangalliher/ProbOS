"""AD-874: Deterministic stranded-work-item classifier + live-agent resolver.

Pure, side-effect-free service. Resolves a work item's ``assigned_to`` to a
*live* agent and classifies a board item into a reconcile action. No LLM, no
board mutation, honest-degrade (never raises). The Quartermaster agent
(AD-875) consumes these decisions and performs the actual board mutations.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_TERMINAL = {"done", "failed", "cancelled"}


@dataclass(frozen=True)
class ReconcileDecision:
    """A pure classification of what should happen to one board item."""

    work_item_id: str
    action: str  # "live_redispatch" | "clear_and_reroute" | "strand_terminal" | "skip"
    assignee: str | None
    resolved_agent_id: str | None
    reason: str


class WorkItemReconciler:
    """Resolves assignees to live agents and classifies stranded items.

    Pure decision service — reads the live ``AgentRegistry`` and (optionally)
    the ``AgentIdentityRegistry`` to determine whether an item's owner is still
    alive, but never mutates the board.
    """

    def __init__(self, *, registry: Any, identity_registry: Any | None = None) -> None:
        self._registry = registry
        self._identity_registry = identity_registry

    def resolve_live_agent(self, assigned_to: str | None) -> str | None:
        """Resolve ``assigned_to`` to the id of a currently-live agent, or None.

        1. falsy assignee -> None.
        2. the assignee id is itself a live agent -> return it (common case:
           AD-177 slot IDs are restart-stable, so a re-spawned same-role agent
           keeps the same id).
        3. else, if an identity registry is wired, treat the assignee as a
           deployment slot, look up its sovereign DID, and scan live agents for
           one whose slot maps to the same ``agent_uuid`` (the **AD-441
           migration seam** — only load-bearing once a sovereign_id can move to
           a new slot; O(N) only on the dead-assignee branch).
        4. else -> None.

        Honest-degrade: any collaborator error returns None, never raises.
        """
        try:
            if not assigned_to:
                return None
            if self._registry.get(assigned_to) is not None:
                return assigned_to
            if self._identity_registry is not None:
                cert = self._identity_registry.get_by_slot(assigned_to)
                if not cert:
                    return None
                for agent in self._registry.all():
                    peer = self._identity_registry.get_by_slot(agent.id)
                    if peer and peer.agent_uuid == cert.agent_uuid:
                        return agent.id
                return None
            return None
        except Exception:
            logger.warning(
                "AD-874: resolve_live_agent failed for assignee %s; "
                "treating as unresolved",
                assigned_to,
                exc_info=True,
            )
            return None

    def classify(
        self,
        wi: dict[str, Any],
        *,
        is_dispatchable: bool,
        is_stalled: bool = False,
    ) -> ReconcileDecision:
        """Classify a board item into a reconcile action (pure).

        ``is_stalled`` (AD-881) is supplied by the sweep, which owns the clock
        and the configured stall threshold. When True, a live-owned
        ``in_progress`` item is rerouted (``reason="stalled"``) instead of
        skipped — liveness alone no longer implies progress.

        BF-730: a stalled ``in_progress`` item that is NOT dispatchable returns
        ``strand_terminal`` instead. It cannot be rerouted without replaying an
        AD-1165 promoted turn, and it cannot be left ``in_progress`` without
        showing the Captain a board of work that is not running.
        """
        wid = wi.get("id", "")
        status = wi.get("status", "")
        assignee = wi.get("assigned_to") or None

        if status in _TERMINAL:
            return ReconcileDecision(wid, "skip", assignee, None, "terminal")
        if not is_dispatchable:
            # BF-730: dispatchability and reconcilability are different
            # questions, and conflating them made the sweep structurally unable
            # to touch the only items that strand. An AD-1165 promoted turn is
            # deliberately NOT dispatchable -- rerouting one would replay side
            # effects the turn already performed -- so every stalled promoted
            # turn returned "skip" here and sat on the board forever. Measured
            # 2026-08-08: 42 non-terminal items, all classified skip, six of
            # them in_progress and idle between 23.5h and 182h.
            #
            # A stalled one still needs an ending. It cannot resume (the turn
            # that owned it is gone) and it must never be dispatched, so it
            # gets a terminal action and no reroute. Owner liveness is
            # deliberately NOT part of this condition: neither a live nor a
            # dead owner permits dispatch here, so both strand identically and
            # excluding one would leave the same defect for a subset.
            if is_stalled and status == "in_progress":
                return ReconcileDecision(
                    wid, "strand_terminal", assignee, None, "stalled_not_dispatchable"
                )
            return ReconcileDecision(wid, "skip", assignee, None, "not_dispatchable")
        if assignee is None and status == "open":
            return ReconcileDecision(
                wid, "live_redispatch", None, None, "unassigned_dispatchable"
            )
        if assignee is not None:
            resolved = self.resolve_live_agent(assignee)
            if resolved is not None and status == "in_progress":
                if is_stalled:
                    # AD-881: live assignee but no board progress past the
                    # stall threshold — reroute instead of skip.
                    return ReconcileDecision(
                        wid, "clear_and_reroute", assignee, resolved, "stalled"
                    )
                return ReconcileDecision(
                    wid, "skip", assignee, resolved, "in_progress_live_owner"
                )
            if resolved is not None and status == "open":
                return ReconcileDecision(
                    wid, "live_redispatch", assignee, resolved, "assignee_live"
                )
            if resolved is None:
                return ReconcileDecision(
                    wid, "clear_and_reroute", assignee, None, "assignee_not_live"
                )
        return ReconcileDecision(wid, "skip", assignee, None, "no_action")
