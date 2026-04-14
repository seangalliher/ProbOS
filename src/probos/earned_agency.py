"""Earned Agency — trust-tiered behavioral gating (AD-357)."""

from __future__ import annotations
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any
from probos.crew_profile import Rank


class AgencyLevel(str, Enum):
    """What an agent is permitted to do at its current trust tier."""
    REACTIVE = "reactive"           # Ensign: responds only when @mentioned
    SUGGESTIVE = "suggestive"       # Lieutenant: participates in own department
    AUTONOMOUS = "autonomous"       # Commander: full Ward Room participation
    UNRESTRICTED = "unrestricted"   # Senior: cross-department, mentoring (future)


class RecallTier(str, Enum):
    """Memory recall capability tier — mapped from Earned Agency rank (AD-462c)."""
    BASIC = "basic"            # Vector similarity only, small budget
    ENHANCED = "enhanced"      # Vector + keyword + salience weights, standard budget
    FULL = "full"              # Full recall_weighted + recall_by_anchor, large budget
    ORACLE = "oracle"          # All recall paths + Oracle Service (AD-462e)


def recall_tier_from_rank(rank: Rank) -> RecallTier:
    """Map rank to recall capability tier."""
    return {
        Rank.ENSIGN: RecallTier.BASIC,
        Rank.LIEUTENANT: RecallTier.ENHANCED,
        Rank.COMMANDER: RecallTier.FULL,
        Rank.SENIOR: RecallTier.ORACLE,
    }[rank]


@dataclass(frozen=True)
class ClearanceGrant:
    """AD-622: Temporary elevated access record.

    Captain-issued, time-limited, scoped, revocable.
    SAP analog for project/duty-based elevated recall access.
    """
    id: str                         # UUID
    target_agent_id: str            # Who receives the grant (sovereign ID)
    recall_tier: RecallTier         # Granted tier level
    scope: str = "general"          # "general" | "project:{name}" | "investigation:{id}"
    reason: str = ""                # Justification (audit trail)
    issued_by: str = "captain"      # Issuer identity
    issued_at: float = 0.0          # Timestamp
    expires_at: float | None = None # None = until revoked
    revoked: bool = False           # Soft-delete
    revoked_at: float | None = None # When revoked (audit trail)


# AD-620: Ordering map — RecallTier is a str enum so we need explicit
# numeric ordering for comparison.
_TIER_ORDER: dict[RecallTier, int] = {
    RecallTier.BASIC: 0,
    RecallTier.ENHANCED: 1,
    RecallTier.FULL: 2,
    RecallTier.ORACLE: 3,
}


def effective_recall_tier(
    rank: Rank | None,
    billet_clearance: str = "",
    grants: Sequence[ClearanceGrant] = (),
) -> RecallTier:
    """AD-620/622: Resolve effective recall tier — max(rank-based, billet-based, grant-based).

    Billet clearance comes from the Post.clearance field in organization.yaml.
    Grants come from active ClearanceGrants issued by the Captain.
    Takes the highest of all three sources.
    """
    rank_tier = recall_tier_from_rank(rank) if rank else RecallTier.ENHANCED

    if not billet_clearance:
        best = rank_tier
    else:
        try:
            billet_tier = RecallTier(billet_clearance.lower())
        except ValueError:
            billet_tier = rank_tier
        best = billet_tier if _TIER_ORDER.get(billet_tier, 0) > _TIER_ORDER.get(rank_tier, 0) else rank_tier

    # AD-622: Apply active grants
    for grant in grants:
        grant_order = _TIER_ORDER.get(grant.recall_tier, 0)
        if grant_order > _TIER_ORDER.get(best, 0):
            best = grant.recall_tier

    return best


def resolve_billet_clearance(
    agent_type: str,
    ontology: Any | None,
) -> str:
    """AD-620: Look up billet clearance for an agent type from the ontology.

    Returns the Post.clearance string, or "" if ontology unavailable or
    agent has no post assignment.
    """
    if not ontology:
        return ""
    try:
        post = ontology.get_post_for_agent(agent_type)
        return post.clearance if post else ""
    except Exception:
        return ""


def resolve_active_grants(
    agent_id: str,
    grant_store: Any | None,
) -> list[ClearanceGrant]:
    """AD-622: Look up active grants for an agent.

    Returns empty list if grant store unavailable. Law of Demeter —
    callers don't reach through runtime to query grants directly.

    NOTE: Synchronous — grant_store.get_active_grants_sync() reads
    from an in-memory cache. See ClearanceGrantStore for cache details.
    """
    if not grant_store:
        return []
    try:
        return grant_store.get_active_grants_sync(agent_id)
    except Exception:
        return []


def agency_from_rank(rank: Rank) -> AgencyLevel:
    """Map rank to agency level."""
    return {
        Rank.ENSIGN: AgencyLevel.REACTIVE,
        Rank.LIEUTENANT: AgencyLevel.SUGGESTIVE,
        Rank.COMMANDER: AgencyLevel.AUTONOMOUS,
        Rank.SENIOR: AgencyLevel.UNRESTRICTED,
    }[rank]


def can_respond_ambient(
    rank: Rank,
    *,
    is_captain_post: bool,
    same_department: bool,
) -> bool:
    """Can this agent respond WITHOUT being @mentioned?

    Core enforcement function. Returns True if the agent is permitted
    to respond to a post it was not explicitly mentioned in.
    """
    if rank == Rank.ENSIGN:
        return False  # Ensigns only respond when @mentioned

    if rank == Rank.LIEUTENANT:
        # Lieutenants respond to Captain posts in own department only
        return is_captain_post and same_department

    if rank == Rank.COMMANDER:
        # Commanders respond to any Captain post; agent posts in own dept
        return is_captain_post or same_department

    # Senior: unrestricted ambient response
    return True


def can_think_proactively(rank: Rank) -> bool:
    """Can this agent initiate proactive thought?

    Ensigns are reactive-only — they haven't earned the trust to
    self-initiate. Everyone else can think proactively.
    """
    return rank != Rank.ENSIGN


def can_perform_action(rank: Rank, action: str) -> bool:
    """Can this agent perform a specific Ward Room action?

    AD-437/AD-485: Action space gating by rank.
    - Ensign: dm only (configurable via communications.dm_min_rank)
    - Lieutenant: endorse + reply + dm
    - Commander: endorse + reply + dm
    - Senior: endorse + reply + dm + thread management (lock, pin)
    """
    _ACTION_TIERS: dict[str, Rank] = {
        "endorse": Rank.LIEUTENANT,
        "reply": Rank.LIEUTENANT,
        "dm": Rank.ENSIGN,  # AD-485: configurable via communications.dm_min_rank
        "lock": Rank.SENIOR,
        "pin": Rank.SENIOR,
    }

    min_rank = _ACTION_TIERS.get(action)
    if min_rank is None:
        return False  # Unknown action

    # Compare ordinals
    _RANK_ORDER = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]
    return _RANK_ORDER.index(rank) >= _RANK_ORDER.index(min_rank)
