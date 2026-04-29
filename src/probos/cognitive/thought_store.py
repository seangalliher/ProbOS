"""AD-606: Think-in-Memory - Evolved Thought Storage.

Persists important conclusions from working memory as thought episodes in
EpisodicMemory. Thought episodes use source=MemorySource.REFLECTION and
channel="thought" in their AnchorFrame, making them distinguishable from direct
experience while naturally participating in standard recall.
"""

from __future__ import annotations

import logging
import time
import uuid
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class ThoughtType(StrEnum):
    """Valid thought types for stored thoughts."""

    HYPOTHESIS = "hypothesis"
    CONCLUSION = "conclusion"
    OBSERVATION = "observation_synthesis"
    INFERENCE = "pattern_recognition"
    PLAN = "plan"


class ThoughtStore:
    """Stores evolved thoughts as episodic memory entries."""

    def __init__(
        self,
        episodic_memory: Any = None,
        *,
        config: Any,
        identity_registry: Any = None,
    ) -> None:
        self._episodic_memory = episodic_memory
        self._identity_registry = identity_registry
        self._min_importance: int = config.min_importance
        self._max_per_cycle: int = config.max_thoughts_per_cycle
        self._cycle_count: int = 0
        self._cycle_correlation_id: str = ""

    def reset_cycle(self, correlation_id: str = "") -> None:
        """Reset the per-cycle thought counter."""
        self._cycle_count = 0
        self._cycle_correlation_id = correlation_id

    async def store_thought(
        self,
        agent_id: str,
        thought: str,
        thought_type: str,
        *,
        evidence_episode_ids: list[str] | None = None,
        importance: int = 6,
        correlation_id: str = "",
    ) -> Any | None:
        """Create and store a thought episode in episodic memory."""
        if not self._episodic_memory:
            logger.debug("AD-606: No episodic memory available; skipping thought storage")
            return None

        if not thought or not thought.strip():
            return None

        thought_value = thought_type.value if hasattr(thought_type, "value") else str(thought_type)
        try:
            thought_value = ThoughtType(thought_value).value
        except ValueError:
            logger.warning(
                "AD-606: Unknown thought type '%s' from %s; defaulting to conclusion so recall remains typed",
                thought_value,
                agent_id,
            )
            thought_value = ThoughtType.CONCLUSION.value

        if importance < self._min_importance:
            logger.debug(
                "AD-606: Thought importance %d below threshold %d; skipping noisy thought storage",
                importance,
                self._min_importance,
            )
            return None

        if self._cycle_count >= self._max_per_cycle:
            logger.debug(
                "AD-606: Thought cap %d reached for this cycle; skipping additional thought storage",
                self._max_per_cycle,
            )
            return None

        from probos.cognitive.episodic import resolve_sovereign_id_from_slot
        from probos.types import AnchorFrame, Episode, MemorySource

        evidence = list(evidence_episode_ids or [])
        resolved_agent_id = resolve_sovereign_id_from_slot(agent_id, self._identity_registry)
        episode = Episode(
            id=uuid.uuid4().hex,
            timestamp=time.time(),
            user_input=thought.strip(),
            agent_ids=[resolved_agent_id],
            source=MemorySource.REFLECTION.value,
            anchors=AnchorFrame(channel="thought", trigger_type=thought_value),
            importance=importance,
            correlation_id=correlation_id or self._cycle_correlation_id,
            outcomes=[
                {
                    "thought_type": thought_value,
                    "evidence_episode_ids": evidence,
                }
            ],
        )

        try:
            await self._episodic_memory.store(episode)
        except Exception:
            logger.warning(
                "AD-606: Failed to store thought episode for %s; continuing without thought memory",
                agent_id,
                exc_info=True,
            )
            return None

        self._cycle_count += 1
        logger.debug(
            "AD-606: Stored thought episode %s type=%s importance=%d agent=%s",
            episode.id,
            thought_value,
            importance,
            agent_id,
        )
        return episode

    async def recall_thoughts(
        self,
        agent_id: str,
        query: str,
        *,
        k: int = 5,
        trust_network: Any = None,
        hebbian_router: Any = None,
    ) -> list[Any]:
        """Recall thought episodes specifically."""
        if not self._episodic_memory or not query:
            return []

        try:
            return await self._episodic_memory.recall_by_anchor_scored(
                agent_id=agent_id,
                channel="thought",
                semantic_query=query,
                limit=k,
                trust_network=trust_network,
                hebbian_router=hebbian_router,
            )
        except Exception:
            logger.debug("AD-606: Thought recall failed; returning no thought results", exc_info=True)
            return []

    @property
    def cycle_thought_count(self) -> int:
        """Number of thoughts stored in the current cognitive cycle."""
        return self._cycle_count