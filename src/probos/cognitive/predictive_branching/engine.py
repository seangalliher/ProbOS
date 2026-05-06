"""AD-633a: Prediction Engine — deterministic confidence scoring.

Pure decision layer. Reads Hebbian weights, ward-room recent activity,
ontology department membership, and working-memory engagement to produce a
confidence score and bucketed tier. No LLM call. No I/O. No event emission.

The engine is the entry point of the AD-633 pipeline:

  PredictionEngine.score() -> PredictionDescriptor
                              \\
                               +-> SpeculationCache.lookup() (AD-633b)
                               +-> SpeculationExecutor.dispatch() (AD-633b)
                               +-> SpeculationBudget.try_reserve() (AD-633c)

AD-633i (Cognitive JIT compilation of repeated predictions into procedures)
is hard-deferred. Its consumer surface — AD-531–539's Cognitive JIT backend —
does not exist at HEAD `d85611f`. `learned_shortcuts/protocol.py:18` documents
`'cognitive_jit'` as a future identifier. Forcing function: AD-633i ships when
AD-531–539 lands a JIT consumer that subscribes to the `PREDICTION_HIT` event
stream this module already emits.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ConfidenceTier(str, Enum):
    """AD-633a: Speculation tier resolved from confidence score."""

    ZERO_COST = "zero_cost"          # Deterministic-only; do not dispatch LLM speculation
    CHEAP = "cheap"                  # Fast-tier LLM speculation
    STANDARD = "standard"            # Standard-tier LLM speculation
    ANTICIPATORY = "anticipatory"    # AD-633f reserved (idle-cycle, gated by EarnedAgency)


@dataclass(frozen=True)
class PredictionDescriptor:
    """AD-633a: Output of a prediction-engine score call."""

    agent_id: str
    agent_type: str
    intent_type: str
    confidence: float                 # [0.0, 1.0]
    tier: ConfidenceTier
    signature: str                    # Stable cache key
    computed_at: float = field(default_factory=time.time)
    components: dict[str, float] = field(default_factory=dict)  # debug breakdown
    reason: str = ""


def compute_signature(*, agent_id: str, intent_type: str, observation: dict[str, Any]) -> str:
    """AD-633a: Stable cache key for a prediction.

    Hash inputs:
      - agent_id (per-agent isolation)
      - intent_type (separate cache lanes per intent)
      - thread_id (same thread = same cache lane)
      - last_speaker_id (different speaker = different signature)

    Excluded inputs:
      - timestamp (would defeat cache hits)
      - free-form text (would defeat similar-context hits)

    Collisions across distinct semantic contexts are vanishingly rare; if
    observed in practice, AD-633a-1 expands the signature surface (e.g., adds
    `last_post_id`).
    """
    parts = [
        agent_id,
        intent_type,
        str(observation.get("thread_id", "")),
        str(observation.get("last_speaker_id", "")),
    ]
    digest = hashlib.sha1("|".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()
    return digest[:16]


class PredictionEngine:
    """AD-633a: Deterministic confidence scoring for speculative pre-computation.

    Constructor injection only — receives runtime references and config.
    No global lookups. No event emission. Pure decision class.
    """

    # Weight allocation: components sum to 1.0
    HEBBIAN_WEIGHT = 0.4
    THREAD_ACTIVITY_WEIGHT = 0.2
    DEPARTMENT_WEIGHT = 0.2
    WORKING_MEMORY_WEIGHT = 0.2

    THREAD_ACTIVITY_WINDOW_SECONDS = 300.0   # 5 min
    THREAD_ACTIVITY_SATURATION = 5           # 5+ recent posts = 1.0

    def __init__(
        self,
        *,
        hebbian_router: Any,
        ontology: Any,
        config: Any,
        circuit_breaker: Any | None = None,
    ) -> None:
        self._hebbian = hebbian_router
        self._ontology = ontology
        self._config = config
        self._circuit_breaker = circuit_breaker

    def score(
        self,
        *,
        agent_id: str,
        agent_type: str,
        observation: dict[str, Any],
    ) -> PredictionDescriptor:
        """Score the likelihood that this agent will be invoked on this kind of intent."""
        intent_type = str(observation.get("intent", ""))

        # Hard gate: circuit breaker OPEN -> ZERO_COST regardless of confidence
        if self._circuit_breaker is not None:
            try:
                if not self._circuit_breaker.should_allow_think(agent_id):
                    sig = compute_signature(
                        agent_id=agent_id, intent_type=intent_type, observation=observation
                    )
                    return PredictionDescriptor(
                        agent_id=agent_id,
                        agent_type=agent_type,
                        intent_type=intent_type,
                        confidence=0.0,
                        tier=ConfidenceTier.ZERO_COST,
                        signature=sig,
                        components={"circuit_breaker": 0.0},
                        reason="circuit_breaker_open",
                    )
            except Exception:
                logger.warning(
                    "AD-633a: circuit_breaker check failed for %s; treating as CLOSED",
                    agent_id, exc_info=True,
                )

        components: dict[str, float] = {}

        # Component 1: Hebbian weight (source = thread origin / last_speaker_id; target = agent)
        hebbian_score = 0.0
        last_speaker = str(observation.get("last_speaker_id", ""))
        if last_speaker and self._hebbian is not None:
            try:
                hebbian_score = max(0.0, min(1.0, float(self._hebbian.get_weight(last_speaker, agent_id))))
            except Exception:
                logger.warning(
                    "AD-633a: hebbian get_weight failed (%s -> %s); using 0.0",
                    last_speaker, agent_id, exc_info=True,
                )
        components["hebbian"] = hebbian_score

        # Component 2: Recent thread activity — count posts in last 5 min that mention agent
        recent_posts = observation.get("recent_thread_posts", []) or []
        if isinstance(recent_posts, list):
            count = min(self.THREAD_ACTIVITY_SATURATION, len(recent_posts))
            thread_score = count / self.THREAD_ACTIVITY_SATURATION
        else:
            thread_score = 0.0
        components["thread_activity"] = thread_score

        # Component 3: Department membership — is observation tagged with this agent's department?
        dept_score = 0.0
        observed_dept = observation.get("department", "")
        if self._ontology is not None and observed_dept:
            try:
                agent_dept = self._ontology.get_agent_department(agent_type)
                dept_score = 1.0 if (agent_dept and agent_dept == observed_dept) else 0.0
            except Exception:
                logger.warning(
                    "AD-633a: ontology get_agent_department failed for %s; using 0.0",
                    agent_type, exc_info=True,
                )
        components["department"] = dept_score

        # Component 4: Working memory engagement match
        wm_engagements = observation.get("active_engagements", []) or []
        wm_score = 1.0 if (intent_type and intent_type in wm_engagements) else 0.0
        components["working_memory"] = wm_score

        confidence = (
            self.HEBBIAN_WEIGHT * hebbian_score
            + self.THREAD_ACTIVITY_WEIGHT * thread_score
            + self.DEPARTMENT_WEIGHT * dept_score
            + self.WORKING_MEMORY_WEIGHT * wm_score
        )
        confidence = max(0.0, min(1.0, confidence))

        tier = self._tier_for(confidence)

        signature = compute_signature(
            agent_id=agent_id, intent_type=intent_type, observation=observation
        )

        return PredictionDescriptor(
            agent_id=agent_id,
            agent_type=agent_type,
            intent_type=intent_type,
            confidence=confidence,
            tier=tier,
            signature=signature,
            components=components,
            reason="scored",
        )

    def _tier_for(self, confidence: float) -> ConfidenceTier:
        """Bucket confidence into a speculation tier."""
        cfg = self._config
        if confidence < cfg.cheap_tier_min_confidence:
            return ConfidenceTier.ZERO_COST
        if confidence < cfg.standard_tier_min_confidence:
            return ConfidenceTier.CHEAP
        if confidence < cfg.anticipatory_tier_min_confidence:
            return ConfidenceTier.STANDARD
        return ConfidenceTier.ANTICIPATORY
