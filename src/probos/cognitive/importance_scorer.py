"""AD-598: Rule-based importance scoring at encoding time.

Assigns a 1-10 importance score to episodes based on trigger type,
content signals, and outcome patterns. No LLM call — pure heuristics.

Inspired by Park et al. (2023) Generative Agents importance scoring,
adapted for ProbOS's AnchorFrame + outcome-based architecture.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.types import Episode

logger = logging.getLogger(__name__)

# Rule-based importance mapping: trigger_type → base importance
# Configurable via ImportanceScoringConfig override
DEFAULT_TRIGGER_IMPORTANCE: dict[str, int] = {
    # High importance — rare, high-signal events
    "circuit_breaker_trip": 9,
    "trust_violation": 9,
    "security_alert": 9,
    "captain_directive": 8,
    "captain_dm": 8,
    "naming_ceremony": 8,
    "promotion": 8,
    # Medium-high — noteworthy events
    "trust_update": 7,
    "dream_complete": 6,
    "counselor_intervention": 7,
    "standing_order": 7,
    "qualification_result": 6,
    # Medium — standard interactions
    "ward_room_post": 5,
    "dm_reply": 5,
    "game_move": 4,
    "game_completed": 4,
    # Low — routine/automated
    "proactive_thought": 3,
    "routine_observation": 3,
    "status_check": 2,
}


def compute_importance(episode: "Episode") -> int:
    """Compute importance score (1-10) for an episode at encoding time.

    Scoring priority:
    1. Trigger type mapping (from AnchorFrame)
    2. Content signal boosts (Captain mentions, failures, firsts)
    3. Outcome-based adjustments (failures boost, empty degrades)

    Returns 5 (neutral) if no signals are detected or on error.
    """
    try:
        score = 5  # Neutral default

        # --- Signal 1: Trigger type from AnchorFrame ---
        if episode.anchors and episode.anchors.trigger_type:
            trigger = episode.anchors.trigger_type.lower().strip()
            if trigger in DEFAULT_TRIGGER_IMPORTANCE:
                score = DEFAULT_TRIGGER_IMPORTANCE[trigger]

        # --- Signal 2: Content-based boosts ---
        text = (episode.user_input or "").lower()

        # Captain interaction is always important
        if "[1:1 with" in text or "captain" in text.split("]:")[0] if "]:" in text else False:
            score = max(score, 8)

        # Ward Room posts (intentional social communication)
        if "[ward room]" in text and score < 5:
            score = 5

        # --- Signal 3: Outcome-based adjustments ---
        outcomes = episode.outcomes or []
        has_failure = False
        has_real_response = False
        for o in outcomes:
            if isinstance(o, dict):
                if not o.get("success", True):
                    has_failure = True
                response = o.get("response", "")
                if isinstance(response, str) and response.strip() not in ("", "[NO_RESPONSE]"):
                    has_real_response = True

        # Failures are learning opportunities — boost importance
        if has_failure:
            score = max(score, 7)

        # No real response = low value
        if not has_real_response and outcomes:
            score = min(score, 3)

        # --- Clamp to valid range ---
        return max(1, min(10, score))

    except Exception:
        logger.debug("AD-598: Importance scoring failed, defaulting to 5", exc_info=True)
        return 5
