"""AD-604: Spreading Activation / Multi-Hop Retrieval.

Multi-hop recall engine: first-hop results seed second-hop queries using
anchor metadata as filters. Enables associative chains for richer causal
and narrative recall without adding a graph database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _AnchorExtraction:
    """Extracted anchor fields from a first-hop result for second-hop query."""

    department: str = ""
    channel: str = ""
    trigger_type: str = ""
    trigger_agent: str = ""
    field_count: int = 0


class SpreadingActivationEngine:
    """Multi-hop retrieval engine using anchor-based spreading activation."""

    def __init__(self, config: Any, episodic_memory: Any = None) -> None:
        self._enabled: bool = config.enabled
        self._max_hops: int = config.max_hops
        self._k_per_hop: int = config.k_per_hop
        self._hop_decay: float = config.hop_decay_factor
        self._min_anchor_fields: int = config.min_anchor_fields
        self._episodic_memory = episodic_memory

    async def multi_hop_recall(
        self,
        query: str,
        agent_id: str,
        *,
        hops: int | None = None,
        k_per_hop: int | None = None,
        trust_network: Any = None,
        hebbian_router: Any = None,
    ) -> list[Any]:
        """Perform multi-hop recall starting from a semantic query."""
        if not self._episodic_memory or not query:
            return []

        max_hops = hops if hops is not None else self._max_hops
        k = k_per_hop if k_per_hop is not None else self._k_per_hop
        seen: dict[str, Any] = {}

        try:
            first_hop = await self._episodic_memory.recall_weighted(
                agent_id,
                query,
                k=k,
                trust_network=trust_network,
                hebbian_router=hebbian_router,
            )
        except Exception:
            logger.debug("AD-604: First hop recall failed; returning no spreading results", exc_info=True)
            return []

        if not first_hop:
            return []

        for recall_score in first_hop:
            episode_id = getattr(getattr(recall_score, "episode", None), "id", "")
            if episode_id:
                seen[episode_id] = recall_score

        if not self._enabled or max_hops < 2:
            return sorted(seen.values(), key=lambda score: score.composite_score, reverse=True)

        for recall_score in first_hop:
            extraction = self._extract_anchor_fields(recall_score)
            if extraction.field_count < self._min_anchor_fields:
                continue

            episode_id = getattr(getattr(recall_score, "episode", None), "id", "")
            try:
                second_hop = await self._episodic_memory.recall_by_anchor_scored(
                    agent_id=agent_id,
                    department=extraction.department,
                    channel=extraction.channel,
                    trigger_type=extraction.trigger_type,
                    trigger_agent=extraction.trigger_agent,
                    semantic_query=query,
                    limit=k,
                    trust_network=trust_network,
                    hebbian_router=hebbian_router,
                )
            except Exception:
                logger.debug(
                    "AD-604: Second hop recall failed for episode %s; continuing with remaining seeds",
                    episode_id[:8],
                    exc_info=True,
                )
                continue

            for second_score in second_hop:
                second_episode_id = getattr(getattr(second_score, "episode", None), "id", "")
                if not second_episode_id:
                    continue
                decayed = self._apply_hop_decay(second_score)
                existing = seen.get(second_episode_id)
                if existing is None or decayed.composite_score > existing.composite_score:
                    seen[second_episode_id] = decayed

        results = sorted(seen.values(), key=lambda score: score.composite_score, reverse=True)
        logger.debug(
            "AD-604: Multi-hop recall returned %d results from %d first-hop seeds",
            len(results),
            len(first_hop),
        )
        return results

    def _extract_anchor_fields(self, recall_score: Any) -> _AnchorExtraction:
        """Extract anchor metadata from a RecallScore for second-hop query."""
        episode = getattr(recall_score, "episode", None)
        if episode is None:
            return _AnchorExtraction()

        anchors = getattr(episode, "anchors", None)
        if anchors is None:
            return _AnchorExtraction()

        department = (
            getattr(anchors, "department", "")
            or getattr(anchors, "duty_department", "")
            or ""
        )
        channel = getattr(anchors, "channel", "") or ""
        trigger_type = getattr(anchors, "trigger_type", "") or ""
        trigger_agent = getattr(anchors, "trigger_agent", "") or ""
        if not trigger_agent:
            agent_ids = getattr(episode, "agent_ids", []) or []
            trigger_agent = agent_ids[0] if agent_ids else ""

        field_count = sum(
            1 for field_value in [department, channel, trigger_type, trigger_agent] if field_value
        )
        return _AnchorExtraction(
            department=department,
            channel=channel,
            trigger_type=trigger_type,
            trigger_agent=trigger_agent,
            field_count=field_count,
        )

    def _apply_hop_decay(self, recall_score: Any) -> Any:
        """Create a new RecallScore with hop decay applied."""
        return replace(
            recall_score,
            composite_score=recall_score.composite_score * self._hop_decay,
        )