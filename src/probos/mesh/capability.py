"""Capability registry — semantic descriptor store with fuzzy matching."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from probos.types import AgentID, CapabilityDescriptor

logger = logging.getLogger(__name__)


@dataclass
class CapabilityMatch:
    """Result of a capability query."""

    agent_id: AgentID
    capability: CapabilityDescriptor
    score: float  # 0.0–1.0 match quality


class CapabilityRegistry:
    """Stores and queries semantic capability descriptors.

    Agents register what they can do. The registry matches intents
    to capable agents using substring/keyword matching against the
    `can` and `detail` fields, with optional semantic matching via
    embeddings when enabled.
    """

    def __init__(self, semantic_matching: bool = True) -> None:
        self._capabilities: dict[AgentID, list[CapabilityDescriptor]] = {}
        self._semantic_matching = semantic_matching

    def register(self, agent_id: AgentID, capabilities: list[CapabilityDescriptor]) -> None:
        self._capabilities[agent_id] = list(capabilities)
        logger.debug(
            "Capabilities registered: agent=%s caps=%s",
            agent_id[:8],
            [c.can for c in capabilities],
        )

    def unregister(self, agent_id: AgentID) -> None:
        self._capabilities.pop(agent_id, None)

    def query(
        self,
        intent: str,
        trust_scores: dict[str, float] | None = None,
    ) -> list[CapabilityMatch]:
        """Find agents whose capabilities match the given intent string.

        Matching strategy (tiered):
        - Exact match on `can` field → score 1.0
        - Intent is a substring of `can` or vice versa → score 0.8
        - Semantic similarity via embeddings (if enabled) → score 0.6 * similarity
        - Any keyword from intent appears in `can` or `detail` → score 0.5

        When ``trust_scores`` is provided (AD-225), the capability score is
        weighted by trust: ``final = score * (0.5 + 0.5 * trust)``.  This
        ensures trust never eliminates a match (floor at 50%) but favours
        agents whose claims are backed by track record.
        """
        intent_lower = intent.lower()
        intent_keywords = set(intent_lower.replace("_", " ").split())
        matches: list[CapabilityMatch] = []

        for agent_id, caps in self._capabilities.items():
            for cap in caps:
                score = self._score_match(intent_lower, intent_keywords, cap)
                if score > 0.0:
                    # Apply trust weighting (AD-225)
                    if trust_scores is not None:
                        trust = trust_scores.get(agent_id, 0.5)
                        score = score * (0.5 + 0.5 * trust)
                    matches.append(CapabilityMatch(
                        agent_id=agent_id,
                        capability=cap,
                        score=score,
                    ))

        # Sort by score descending, then by capability confidence descending
        matches.sort(key=lambda m: (m.score, m.capability.confidence), reverse=True)
        return matches

    def get_agent_capabilities(self, agent_id: AgentID) -> list[CapabilityDescriptor]:
        return list(self._capabilities.get(agent_id, []))

    @property
    def agent_count(self) -> int:
        return len(self._capabilities)

    def _score_match(
        self,
        intent_lower: str,
        intent_keywords: set[str],
        cap: CapabilityDescriptor,
    ) -> float:
        can_lower = cap.can.lower()
        detail_lower = cap.detail.lower()

        # Exact match
        if intent_lower == can_lower:
            return 1.0

        # Substring containment
        if intent_lower in can_lower or can_lower in intent_lower:
            return 0.8

        # Semantic similarity via embeddings (when enabled)
        if self._semantic_matching:
            try:
                from probos.cognitive.embeddings import compute_similarity
                cap_text = f"{can_lower} {detail_lower}".strip()
                intent_text = intent_lower.replace("_", " ")
                sim = compute_similarity(intent_text, cap_text)
                if sim >= 0.5:
                    return 0.6 * sim + 0.3  # Scale to 0.6-0.9 range
            except Exception:
                pass

        # Keyword overlap (fallback)
        can_keywords = set(can_lower.replace("_", " ").split())
        detail_keywords = set(detail_lower.replace("_", " ").split())
        all_cap_keywords = can_keywords | detail_keywords

        overlap = intent_keywords & all_cap_keywords
        if overlap:
            return 0.5 * len(overlap) / max(len(intent_keywords), 1)

        return 0.0
