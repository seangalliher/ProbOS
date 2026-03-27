"""Earned Agency — trust-tiered behavioral gating (AD-357)."""

from __future__ import annotations
from enum import Enum
from probos.crew_profile import Rank


class AgencyLevel(str, Enum):
    """What an agent is permitted to do at its current trust tier."""
    REACTIVE = "reactive"           # Ensign: responds only when @mentioned
    SUGGESTIVE = "suggestive"       # Lieutenant: participates in own department
    AUTONOMOUS = "autonomous"       # Commander: full Ward Room participation
    UNRESTRICTED = "unrestricted"   # Senior: cross-department, mentoring (future)


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

    AD-437: Action space gating by rank.
    - Ensign: no actions (reactive only)
    - Lieutenant: endorse + reply
    - Commander: endorse + reply
    - Senior: endorse + reply + thread management (lock, pin)
    """
    if rank == Rank.ENSIGN:
        return False

    _ACTION_TIERS: dict[str, Rank] = {
        "endorse": Rank.LIEUTENANT,
        "reply": Rank.LIEUTENANT,
        "dm": Rank.COMMANDER,  # AD-453
        "lock": Rank.SENIOR,
        "pin": Rank.SENIOR,
    }

    min_rank = _ACTION_TIERS.get(action)
    if min_rank is None:
        return False  # Unknown action

    # Compare ordinals
    _RANK_ORDER = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]
    return _RANK_ORDER.index(rank) >= _RANK_ORDER.index(min_rank)
