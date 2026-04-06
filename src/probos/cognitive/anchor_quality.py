"""AD-567c: Anchor Quality & Integrity — weighted confidence scoring and per-agent profiles.

Implements Johnson & Raye (1981) reality monitoring: contextual dimensions
(when/where/who) are stronger reality markers than procedural dimensions (how).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from probos.types import AnchorFrame

logger = logging.getLogger(__name__)

# Default Johnson-SMF-inspired dimension weights (must sum to 1.0)
DEFAULT_DIMENSION_WEIGHTS: dict[str, float] = {
    "temporal": 0.25,   # When — strong reality marker
    "spatial": 0.25,    # Where — strong reality marker
    "social": 0.25,     # Who — strong reality marker
    "causal": 0.15,     # Why/How — weaker per Johnson
    "evidential": 0.10, # Corroboration — supplementary
}


def _is_filled(value: Any) -> bool:
    """Check if an AnchorFrame field value is populated (non-default)."""
    if isinstance(value, str):
        return value != ""
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, (int, float)):
        return value > 0.0
    return bool(value)


def _compute_dimension_scores(anchors: AnchorFrame) -> dict[str, float]:
    """Compute per-dimension fill rates for an AnchorFrame."""
    temporal_fields = [anchors.duty_cycle_id, anchors.watch_section]
    spatial_fields = [anchors.channel, anchors.channel_id, anchors.department]
    social_fields = [anchors.participants, anchors.trigger_agent]
    evidential_fields = [anchors.thread_id, anchors.event_log_window]
    return {
        "temporal": sum(1 for f in temporal_fields if _is_filled(f)) / len(temporal_fields),
        "spatial": sum(1 for f in spatial_fields if _is_filled(f)) / len(spatial_fields),
        "social": sum(1 for f in social_fields if _is_filled(f)) / len(social_fields),
        "causal": 1.0 if _is_filled(anchors.trigger_type) else 0.0,
        "evidential": sum(1 for f in evidential_fields if _is_filled(f)) / len(evidential_fields),
    }


def compute_anchor_confidence(
    anchors: AnchorFrame | None,
    weights: dict[str, float] | None = None,
) -> float:
    """Compute weighted anchor confidence score (0.0–1.0).

    Johnson & Raye (1981): real memories have more contextual/perceptual
    detail (when/where/who); imagined memories rely on cognitive operations.
    Weight contextual dimensions higher for confabulation detection.

    Dimension weights default to DEFAULT_DIMENSION_WEIGHTS.
    """
    if anchors is None:
        return 0.0

    w = weights or DEFAULT_DIMENSION_WEIGHTS

    scores = _compute_dimension_scores(anchors)

    confidence = (
        w.get("temporal", 0.25) * scores["temporal"]
        + w.get("spatial", 0.25) * scores["spatial"]
        + w.get("social", 0.25) * scores["social"]
        + w.get("causal", 0.15) * scores["causal"]
        + w.get("evidential", 0.10) * scores["evidential"]
    )
    return confidence


# ---------------------------------------------------------------------------
# Per-Agent Anchor Profiles (CAST-inspired)
# ---------------------------------------------------------------------------

@dataclass
class AnchorProfile:
    """Aggregate anchor quality statistics for a single agent (AD-567c)."""

    agent_id: str = ""
    total_episodes: int = 0
    mean_confidence: float = 0.0
    median_confidence: float = 0.0
    low_confidence_count: int = 0
    low_confidence_pct: float = 0.0
    dimension_fill_rates: dict[str, float] = field(default_factory=dict)
    weakest_dimension: str = ""
    strongest_dimension: str = ""
    timestamp: float = 0.0


async def build_anchor_profile(
    agent_id: str,
    episodic_memory: Any,
    confidence_gate: float = 0.3,
    weights: dict[str, float] | None = None,
) -> AnchorProfile:
    """Build an AnchorProfile from an agent's episodic memory (AD-567c).

    Batch operation — intended for dream cycles or on-demand, not per-recall.
    """
    profile = AnchorProfile(agent_id=agent_id, timestamp=time.time())

    if not episodic_memory or not hasattr(episodic_memory, 'recent_for_agent'):
        return profile

    try:
        episodes = await episodic_memory.recent_for_agent(agent_id, k=100)
    except Exception:
        logger.debug("AD-567c: Failed to fetch episodes for anchor profile", exc_info=True)
        return profile

    if not episodes:
        return profile

    profile.total_episodes = len(episodes)

    # Compute per-episode confidence and per-dimension fill rates
    confidences: list[float] = []
    dim_fills: dict[str, list[float]] = {
        "temporal": [], "spatial": [], "social": [], "causal": [], "evidential": [],
    }

    for ep in episodes:
        anchors = ep.anchors
        conf = compute_anchor_confidence(anchors, weights)
        confidences.append(conf)

        if anchors is not None:
            dim_scores = _compute_dimension_scores(anchors)
            for dim in dim_fills:
                dim_fills[dim].append(dim_scores[dim])
        else:
            for dim in dim_fills:
                dim_fills[dim].append(0.0)

    # Aggregate statistics
    profile.mean_confidence = sum(confidences) / len(confidences)
    sorted_conf = sorted(confidences)
    n = len(sorted_conf)
    profile.median_confidence = (
        sorted_conf[n // 2] if n % 2 == 1
        else (sorted_conf[n // 2 - 1] + sorted_conf[n // 2]) / 2.0
    )
    profile.low_confidence_count = sum(1 for c in confidences if c < confidence_gate)
    profile.low_confidence_pct = profile.low_confidence_count / len(confidences)

    # Per-dimension fill rates
    for dim, fills in dim_fills.items():
        profile.dimension_fill_rates[dim] = sum(fills) / len(fills) if fills else 0.0

    # Weakest / strongest
    if profile.dimension_fill_rates:
        profile.weakest_dimension = min(
            profile.dimension_fill_rates, key=profile.dimension_fill_rates.get  # type: ignore[arg-type]
        )
        profile.strongest_dimension = max(
            profile.dimension_fill_rates, key=profile.dimension_fill_rates.get  # type: ignore[arg-type]
        )

    return profile
