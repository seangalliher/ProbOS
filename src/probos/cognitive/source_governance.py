"""Adaptive Source Governance — AD-568a/b/c.

Dynamic episodic vs parametric memory weighting based on task type,
retrieval quality signals, and anchor confidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RetrievalStrategy(str, Enum):
    """Retrieval strategy for episodic memory (AD-568a)."""
    NONE = "none"        # Skip episodic recall — parametric + procedural only
    SHALLOW = "shallow"  # Standard tier-based recall
    DEEP = "deep"        # Enhanced retrieval with expanded budget


# Intent-type → strategy mapping.
# Intent names come from IntentMessage.intent (plain strings).
# Unknown intents default to SHALLOW.
_INTENT_STRATEGY_MAP: dict[str, RetrievalStrategy] = {
    # NONE — creative/exploratory, no episodic benefit
    "game_challenge": RetrievalStrategy.NONE,
    "game_move": RetrievalStrategy.NONE,
    "game_spectate": RetrievalStrategy.NONE,

    # SHALLOW — routine, standard recall
    "proactive_think": RetrievalStrategy.SHALLOW,
    "ward_room_notification": RetrievalStrategy.SHALLOW,
    "direct_message": RetrievalStrategy.SHALLOW,
    "duty_assignment": RetrievalStrategy.SHALLOW,

    # DEEP — operational/diagnostic, experience is critical
    "incident_response": RetrievalStrategy.DEEP,
    "diagnostic_request": RetrievalStrategy.DEEP,
    "system_analysis": RetrievalStrategy.DEEP,
    "security_assessment": RetrievalStrategy.DEEP,
    "medical_assessment": RetrievalStrategy.DEEP,
    "build_task": RetrievalStrategy.DEEP,
    "code_review": RetrievalStrategy.DEEP,
}


def classify_retrieval_strategy(
    intent_type: str,
    *,
    episodic_count: int = 0,
    recent_confabulation_rate: float = 0.0,
) -> RetrievalStrategy:
    """Classify intent into retrieval strategy (AD-568a).

    Args:
        intent_type: The intent name string (e.g. "direct_message", "proactive_think").
        episodic_count: Number of episodes the agent has. If zero, NONE is
            always returned (no memories to retrieve).
        recent_confabulation_rate: Agent's recent confabulation rate from
            Counselor profile. High rates (>0.3) downgrade DEEP → SHALLOW.

    Returns:
        RetrievalStrategy enum value.
    """
    # No episodes at all → skip retrieval regardless of intent
    if episodic_count == 0:
        return RetrievalStrategy.NONE

    strategy = _INTENT_STRATEGY_MAP.get(intent_type, RetrievalStrategy.SHALLOW)

    # Safety: high confabulation rate → don't expand retrieval
    if strategy == RetrievalStrategy.DEEP and recent_confabulation_rate > 0.3:
        logger.info(
            "AD-568a: Downgrading DEEP→SHALLOW for intent '%s' due to "
            "confabulation rate %.2f",
            intent_type, recent_confabulation_rate,
        )
        strategy = RetrievalStrategy.SHALLOW

    return strategy


# ---------------------------------------------------------------------------
# Phase 2: Adaptive Budget Scaling (AD-568b)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetAdjustment:
    """Result of adaptive budget scaling (AD-568b)."""
    original_budget: int
    adjusted_budget: int
    reason: str
    scale_factor: float


def compute_adaptive_budget(
    base_budget: int,
    *,
    recall_scores: list[Any] | None = None,
    mean_anchor_confidence: float = 0.0,
    episode_count: int = 0,
    strategy: RetrievalStrategy = RetrievalStrategy.SHALLOW,
) -> BudgetAdjustment:
    """Compute adaptive context budget based on retrieval quality (AD-568b).

    Scaling rules:
    - High-quality recalls (mean anchor confidence > 0.6): expand to 1.3x
    - Low-quality recalls (mean anchor confidence < 0.2): contract to 0.6x
    - Very few episodes (< 3): contract to 0.5x (little to retrieve)
    - NONE strategy: budget = 0
    - DEEP strategy already applied 1.5x in Phase 1; no additional scaling here

    Floor: 500 chars (always allow at least one short episode).
    Ceiling: 12000 chars (prevent context window bloat).

    Args:
        base_budget: The tier-resolved budget from resolve_recall_tier_params().
        recall_scores: List of RecallScore objects from recall_weighted().
        mean_anchor_confidence: Pre-computed mean anchor confidence.
        episode_count: Total episodes the agent has.
        strategy: The retrieval strategy from Phase 1.

    Returns:
        BudgetAdjustment with the scaled budget and reason.
    """
    if strategy == RetrievalStrategy.NONE:
        return BudgetAdjustment(
            original_budget=base_budget,
            adjusted_budget=0,
            reason="strategy=NONE, no retrieval",
            scale_factor=0.0,
        )

    # Compute mean anchor confidence from recall_scores if available
    _anchor_conf = mean_anchor_confidence
    if recall_scores:
        confs = [
            getattr(rs, 'anchor_confidence', 0.0)
            for rs in recall_scores
            if hasattr(rs, 'anchor_confidence')
        ]
        if confs:
            _anchor_conf = sum(confs) / len(confs)

    scale = 1.0
    reason_parts: list[str] = []

    # Signal 1: Anchor confidence quality
    if _anchor_conf > 0.6:
        scale *= 1.3
        reason_parts.append(f"high anchor confidence ({_anchor_conf:.2f})")
    elif _anchor_conf < 0.2 and episode_count > 0:
        scale *= 0.6
        reason_parts.append(f"low anchor confidence ({_anchor_conf:.2f})")

    # Signal 2: Episode sparsity
    if 0 < episode_count < 3:
        scale *= 0.5
        reason_parts.append(f"sparse episodes ({episode_count})")

    # Signal 3: Recall score distribution (if available)
    if recall_scores and len(recall_scores) > 0:
        scores = [
            getattr(rs, 'composite_score', 0.0)
            for rs in recall_scores
            if hasattr(rs, 'composite_score')
        ]
        if scores:
            mean_score = sum(scores) / len(scores)
            if mean_score > 0.7:
                scale *= 1.15
                reason_parts.append(f"high recall quality ({mean_score:.2f})")
            elif mean_score < 0.3:
                scale *= 0.8
                reason_parts.append(f"low recall quality ({mean_score:.2f})")

    adjusted = int(base_budget * scale)
    # Enforce floor/ceiling
    adjusted = max(500, min(12000, adjusted))

    reason = "; ".join(reason_parts) if reason_parts else "no adjustment"

    return BudgetAdjustment(
        original_budget=base_budget,
        adjusted_budget=adjusted,
        reason=reason,
        scale_factor=scale,
    )


# ---------------------------------------------------------------------------
# Phase 3: Source Priority Framing (AD-568c)
# ---------------------------------------------------------------------------


class SourceAuthority(str, Enum):
    """How authoritatively to frame episodic content (AD-568c)."""
    AUTHORITATIVE = "authoritative"  # Well-anchored, domain-relevant
    SUPPLEMENTARY = "supplementary"  # Moderate quality — consider but verify
    PERIPHERAL = "peripheral"        # Low quality — background only


@dataclass(frozen=True)
class SourceFraming:
    """Source priority framing result (AD-568c)."""
    authority: SourceAuthority
    header: str
    instruction: str


def compute_source_framing(
    *,
    mean_anchor_confidence: float = 0.0,
    recall_count: int = 0,
    mean_recall_score: float = 0.0,
    strategy: RetrievalStrategy = RetrievalStrategy.SHALLOW,
) -> SourceFraming:
    """Compute source authority framing for episodic content (AD-568c).

    Args:
        mean_anchor_confidence: Mean anchor confidence of recalled episodes.
        recall_count: Number of episodes recalled.
        mean_recall_score: Mean composite score of recalled episodes.
        strategy: Retrieval strategy from Phase 1.

    Returns:
        SourceFraming with authority level, header text, and instruction text.
    """
    if strategy == RetrievalStrategy.NONE or recall_count == 0:
        return SourceFraming(
            authority=SourceAuthority.PERIPHERAL,
            header="=== SHIP MEMORY (no relevant experiences recalled) ===",
            instruction=(
                "You have no relevant episodic memories for this task. "
                "Rely on your training knowledge and standing orders. "
                "Be explicit if you are reasoning from general knowledge rather "
                "than personal experience."
            ),
        )

    # Compute authority level from quality signals
    quality_score = (mean_anchor_confidence * 0.6) + (mean_recall_score * 0.4)

    if quality_score > 0.55 and recall_count >= 3:
        return SourceFraming(
            authority=SourceAuthority.AUTHORITATIVE,
            header="=== SHIP MEMORY (verified operational experience) ===",
            instruction=(
                "These memories are well-anchored with strong contextual grounding. "
                "Prefer your operational experience over general knowledge when they "
                "conflict. Your experience aboard this vessel is authoritative for "
                "ship-specific matters."
            ),
        )
    elif quality_score > 0.3:
        return SourceFraming(
            authority=SourceAuthority.SUPPLEMENTARY,
            header="=== SHIP MEMORY (your experiences aboard this vessel) ===",
            instruction=(
                "These are your experiences. Consider them alongside your training "
                "knowledge. Where memories have strong anchors (time, place, participants), "
                "weight them more heavily. Where anchors are weak, treat as supplementary."
            ),
        )
    else:
        return SourceFraming(
            authority=SourceAuthority.PERIPHERAL,
            header="=== SHIP MEMORY (limited recollections) ===",
            instruction=(
                "These recollections have weak contextual grounding. Do not rely "
                "heavily on them. Use your training knowledge as the primary source "
                "and treat these as background context only. If uncertain, say so."
            ),
        )
