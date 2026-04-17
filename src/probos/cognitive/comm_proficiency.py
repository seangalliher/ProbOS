"""AD-625: Communication proficiency — prompt guidance and gate modulation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from probos.skill_framework import ProficiencyLevel


class CommTier(IntEnum):
    """Communication discipline tiers mapped from ProficiencyLevel."""
    NOVICE = 1
    COMPETENT = 2
    PROFICIENT = 3
    EXPERT = 4


@dataclass(frozen=True)
class CommGateOverrides:
    """Per-tier system gate adjustments."""
    reply_cooldown_seconds: int
    tier: CommTier


# --- Tier mapping ---

_TIER_MAP: dict[int, CommTier] = {
    ProficiencyLevel.FOLLOW.value: CommTier.NOVICE,
    ProficiencyLevel.ASSIST.value: CommTier.NOVICE,
    ProficiencyLevel.APPLY.value: CommTier.COMPETENT,
    ProficiencyLevel.ENABLE.value: CommTier.COMPETENT,
    ProficiencyLevel.ADVISE.value: CommTier.PROFICIENT,
    ProficiencyLevel.LEAD.value: CommTier.EXPERT,
    ProficiencyLevel.SHAPE.value: CommTier.EXPERT,
}

_GATE_OVERRIDES: dict[CommTier, CommGateOverrides] = {
    CommTier.NOVICE: CommGateOverrides(
        reply_cooldown_seconds=180,
        tier=CommTier.NOVICE,
    ),
    CommTier.COMPETENT: CommGateOverrides(
        reply_cooldown_seconds=120,
        tier=CommTier.COMPETENT,
    ),
    CommTier.PROFICIENT: CommGateOverrides(
        reply_cooldown_seconds=90,
        tier=CommTier.PROFICIENT,
    ),
    CommTier.EXPERT: CommGateOverrides(
        reply_cooldown_seconds=60,
        tier=CommTier.EXPERT,
    ),
}

_PROMPT_GUIDANCE: dict[CommTier, str] = {
    CommTier.NOVICE: (
        "You are at Novice communication level. Before replying, explicitly state "
        "what new information you would add. If you cannot articulate a specific novel "
        "contribution, use [NO_RESPONSE] or [ENDORSE]. Err on the side of silence — "
        "a disciplined [NO_RESPONSE] builds communication proficiency faster than "
        "a low-value reply."
    ),
    CommTier.COMPETENT: (
        "You are at Competent communication level. Check whether your reply adds "
        "information not already in the thread. Use [ENDORSE] for agreement. "
        "Keep replies to 2-3 sentences."
    ),
    CommTier.PROFICIENT: (
        "You are at Proficient communication level. You have demonstrated communication "
        "discipline. Focus on novel perspectives, gap-filling, and connecting ideas across "
        "departments. Your contributions should advance the discussion, not confirm it."
    ),
    CommTier.EXPERT: (
        "You are at Expert communication level. Shape discussion direction, identify "
        "what is NOT being said, fill analytical gaps, and mentor others through your "
        "example. Your silence is as valuable as your words."
    ),
}


def proficiency_to_tier(proficiency: int | ProficiencyLevel) -> CommTier:
    """Map a ProficiencyLevel value to a CommTier."""
    val = proficiency if isinstance(proficiency, int) else proficiency.value
    return _TIER_MAP.get(val, CommTier.NOVICE)


def get_gate_overrides(proficiency: int | ProficiencyLevel) -> CommGateOverrides:
    """Return system gate overrides for the given proficiency level."""
    return _GATE_OVERRIDES[proficiency_to_tier(proficiency)]


def get_prompt_guidance(proficiency: int | ProficiencyLevel) -> str:
    """Return tier-specific prompt guidance text."""
    return _PROMPT_GUIDANCE[proficiency_to_tier(proficiency)]


def format_proficiency_label(proficiency: int | ProficiencyLevel) -> str:
    """Return human-readable label for use in skill descriptions.

    E.g., "Competent" for APPLY/ENABLE levels.
    """
    return proficiency_to_tier(proficiency).name.capitalize()
