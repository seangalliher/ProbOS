"""Memory Transparency Mechanism (AD-678).

Wraps episodic memory recall results with provenance metadata,
enabling agents to reason about memory age, confidence, and source.
Uses ProvenanceTag/ProvenanceEnvelope from AD-677.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.types import Episode

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryProvenance:
    """Provenance metadata for a recalled memory (AD-678)."""

    episode_id: str
    agent_id: str
    age_seconds: float
    similarity_score: float
    source_channel: str
    is_own_memory: bool

    @property
    def is_stale(self) -> bool:
        """Whether this memory is older than 1 hour."""
        return self.age_seconds > 3600

    @property
    def confidence_label(self) -> str:
        """Human-readable confidence level."""
        if self.similarity_score >= 0.8:
            return "high"
        if self.similarity_score >= 0.5:
            return "moderate"
        return "low"

    def format_inline(self) -> str:
        """Format as inline tag for prompt injection.

        Example: [memory agent:worf-12ab age:5m confidence:high own:yes]
        """
        age = self.age_seconds
        if age < 60:
            age_str = f"{int(age)}s"
        elif age < 3600:
            age_str = f"{int(age / 60)}m"
        else:
            age_str = f"{int(age / 3600)}h"

        stale = " STALE" if self.is_stale else ""
        own = "yes" if self.is_own_memory else "no"
        agent_label = self.agent_id[:12] if self.agent_id else "unknown"
        return (
            f"[memory agent:{agent_label} age:{age_str} "
            f"confidence:{self.confidence_label} own:{own}{stale}]"
        )


@dataclass
class TransparentMemory:
    """A recalled memory with provenance attached (AD-678)."""

    content: str
    provenance: MemoryProvenance
    episode: Any = None

    def render(self) -> str:
        """Render content with inline provenance tag."""
        return f"{self.provenance.format_inline()} {self.content}"


class MemoryTransparencyService:
    """Wraps episodic recall results with provenance (AD-678)."""

    def wrap_recall_results(
        self,
        *,
        episodes: list[Any],
        distances: list[float] | None = None,
        recalling_agent_id: str = "",
    ) -> list[TransparentMemory]:
        """Wrap a list of recalled episodes with provenance.

        Args:
            episodes: List of Episode objects from recall().
            distances: Optional ChromaDB distances (1 - similarity).
            recalling_agent_id: Agent performing the recall.
        """
        results: list[TransparentMemory] = []
        for index, episode in enumerate(episodes):
            episode_id = getattr(episode, "id", "")
            agent_ids = getattr(episode, "agent_ids", [])
            agent_id = agent_ids[0] if agent_ids else ""
            timestamp = getattr(episode, "timestamp", 0.0)
            content = getattr(episode, "user_input", "")
            anchors = getattr(episode, "anchors", None)
            channel = anchors.channel if anchors and hasattr(anchors, "channel") else "unknown"

            distance = distances[index] if distances and index < len(distances) else 0.0
            similarity = max(0.0, 1.0 - distance)
            age = time.time() - timestamp if timestamp else 0.0

            provenance = MemoryProvenance(
                episode_id=episode_id,
                agent_id=agent_id,
                age_seconds=age,
                similarity_score=similarity,
                source_channel=channel or "unknown",
                is_own_memory=(agent_id == recalling_agent_id),
            )

            results.append(
                TransparentMemory(
                    content=content,
                    provenance=provenance,
                    episode=episode,
                )
            )

        return results

    def filter_by_confidence(
        self,
        memories: list[TransparentMemory],
        min_confidence: float = 0.5,
    ) -> list[TransparentMemory]:
        """Filter memories by minimum similarity score."""
        return [
            memory
            for memory in memories
            if memory.provenance.similarity_score >= min_confidence
        ]

    def format_for_prompt(
        self,
        memories: list[TransparentMemory],
        *,
        max_items: int = 5,
    ) -> str:
        """Format transparent memories for injection into agent prompt."""
        lines = []
        for memory in memories[:max_items]:
            lines.append(memory.render())
        return "\n".join(lines)
