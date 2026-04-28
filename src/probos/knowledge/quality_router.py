"""AD-565: Quality-informed routing weights."""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.config import QualityRouterConfig

logger = logging.getLogger(__name__)


class QualityRouter:
    """Maps notebook quality scores to optional routing weight multipliers."""

    def __init__(self, config: QualityRouterConfig, emit_event_fn: Any = None) -> None:
        self._config = config
        self._emit_event_fn = emit_event_fn
        self._quality_scores: dict[str, float] = {}
        self._last_updated: dict[str, float] = {}

    def get_quality_weight(self, agent_id: str) -> float:
        """Return the quality routing weight for an agent."""
        if not self._config.enabled:
            return 1.0
        quality_score = self._quality_scores.get(agent_id)
        if quality_score is None:
            return 1.0
        weight = self._config.min_weight + quality_score * (
            self._config.max_weight - self._config.min_weight
        )
        return max(self._config.min_weight, min(self._config.max_weight, weight))

    def update_quality(self, agent_id: str, quality_score: float) -> None:
        """Store an agent quality score and emit concerns below threshold."""
        if not self._config.enabled:
            return
        self._quality_scores[agent_id] = quality_score
        self._last_updated[agent_id] = time.time()
        weight = self.get_quality_weight(agent_id)
        if quality_score < self._config.concern_threshold and self._emit_event_fn:
            self._emit_event_fn("quality_concern", {
                "agent_id": agent_id,
                "quality_score": quality_score,
                "weight": weight,
            })
        logger.info(
            "AD-565: Quality updated for %s - score=%.3f, weight=%.3f",
            agent_id,
            quality_score,
            weight,
        )

    def get_diagnostic(self, agent_id: str) -> dict:
        """Return a Counselor-ready diagnostic for an agent."""
        quality_score = self._quality_scores.get(agent_id)
        return {
            "agent_id": agent_id,
            "quality_score": quality_score,
            "weight": self.get_quality_weight(agent_id),
            "last_updated": self._last_updated.get(agent_id),
            "concern": quality_score is not None and quality_score < self._config.concern_threshold,
        }

    def get_all_weights(self) -> dict[str, float]:
        """Return all known quality routing weights."""
        return {
            agent_id: self.get_quality_weight(agent_id)
            for agent_id in self._quality_scores
        }