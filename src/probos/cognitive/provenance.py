"""Context Provenance Metadata (AD-677).

Tags every piece of context injected into agent prompts with
source tier, retrieval timestamp, confidence score, and
staleness indicator.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProvenanceTag:
    """Metadata tag for a single piece of injected context."""

    source_tier: str
    retrieval_timestamp: float
    confidence: float
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        """How old this retrieval is."""
        return time.time() - self.retrieval_timestamp

    @property
    def is_stale(self) -> bool:
        """Whether this context is older than 5 minutes."""
        return self.age_seconds > 300

    def format_inline(self) -> str:
        """Format as an inline provenance marker for prompt injection.

        Example: [source:episodic confidence:0.82 age:3m]
        """
        age = self.age_seconds
        if age < 60:
            age_str = f"{int(age)}s"
        elif age < 3600:
            age_str = f"{int(age / 60)}m"
        else:
            age_str = f"{int(age / 3600)}h"

        stale_marker = " STALE" if self.is_stale else ""
        return (
            f"[source:{self.source_tier} confidence:{self.confidence:.2f} "
            f"age:{age_str}{stale_marker}]"
        )


def compute_content_hash(content: str) -> str:
    """Compute a short hash of content for dedup detection."""
    return hashlib.sha256(content.encode()).hexdigest()[:8]


@dataclass
class ProvenanceEnvelope:
    """Wraps content with its provenance tag (AD-677).

    Used by TieredKnowledgeLoader to pass provenance through
    the context injection pipeline.
    """

    content: str
    tag: ProvenanceTag

    def render(self) -> str:
        """Render content with inline provenance marker."""
        return f"{self.tag.format_inline()}\n{self.content}"

    @classmethod
    def from_oracle_result(cls, result: Any) -> "ProvenanceEnvelope":
        """Create from an OracleResult (oracle_service.py:22-30)."""
        return cls(
            content=result.content,
            tag=ProvenanceTag(
                source_tier=result.source_tier,
                retrieval_timestamp=time.time(),
                confidence=result.score,
                content_hash=compute_content_hash(result.content),
                metadata=result.metadata,
            ),
        )


async def query_with_provenance(
    oracle: Any,
    *,
    query_text: str = "",
    agent_id: str = "",
    intent_type: str = "",
    k_per_tier: int = 5,
    tiers: list[str] | None = None,
) -> list[ProvenanceEnvelope]:
    """Query Oracle and wrap results with provenance metadata (AD-677)."""
    try:
        results = await oracle.query(
            query_text=query_text or intent_type or "ambient",
            agent_id=agent_id,
            intent_type=intent_type,
            k_per_tier=k_per_tier,
            tiers=tiers,
        )
        return [ProvenanceEnvelope.from_oracle_result(result) for result in results]
    except Exception:
        logger.debug(
            "AD-677: Provenance-tagged query failed; returning empty envelope list "
            "so context injection can continue without provenance metadata.",
            exc_info=True,
        )
        return []
