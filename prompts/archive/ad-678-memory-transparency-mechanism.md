# AD-678: Memory Transparency Mechanism

**Status:** Ready for builder
**Dependencies:** AD-677 (Context Provenance Metadata)
**Estimated tests:** ~7

---

## Problem

When an agent recalls episodic memories, the memories arrive as raw text
with no indication of source, age, or reliability. The agent cannot
distinguish between a memory from 5 minutes ago and one from 3 days ago,
or between a high-confidence semantic match and a marginal one.

AD-677 introduces `ProvenanceTag` and `ProvenanceEnvelope` for context
provenance. AD-678 extends this to episodic memory retrieval — wrapping
recall results with provenance tags so agents can reason about memory
quality when making decisions.

## Fix

### Section 1: Create `MemoryTransparencyService`

**File:** `src/probos/cognitive/memory_transparency.py` (new file)

```python
"""Memory Transparency Mechanism (AD-678).

Wraps episodic memory recall results with provenance metadata,
enabling agents to reason about memory age, confidence, and source.
Uses ProvenanceTag/ProvenanceEnvelope from AD-677.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.types import Episode

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryProvenance:
    """Provenance metadata for a recalled memory (AD-678)."""

    episode_id: str
    agent_id: str  # Whose memory shard this came from
    age_seconds: float  # Time since episode was stored
    similarity_score: float  # Semantic similarity (0.0-1.0)
    source_channel: str  # "ward_room" | "direct_message" | "duty" | "unknown"
    is_own_memory: bool  # Whether recalling agent authored this episode

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
        return (
            f"[memory agent:{self.agent_id[:12]} age:{age_str} "
            f"confidence:{self.confidence_label} own:{own}{stale}]"
        )


@dataclass
class TransparentMemory:
    """A recalled memory with provenance attached (AD-678)."""

    content: str
    provenance: MemoryProvenance
    episode: Any = None  # Optional full Episode reference

    def render(self) -> str:
        """Render content with inline provenance tag."""
        return f"{self.provenance.format_inline()} {self.content}"


class MemoryTransparencyService:
    """Wraps episodic recall results with provenance (AD-678).

    Usage:
        service = MemoryTransparencyService()
        transparent = service.wrap_recall_results(
            episodes=episodes,
            distances=distances,
            recalling_agent_id="agent-1",
        )
        for tm in transparent:
            print(tm.render())
    """

    def wrap_recall_results(
        self,
        *,
        episodes: list[Any],
        distances: list[float] | None = None,
        recalling_agent_id: str = "",
    ) -> list[TransparentMemory]:
        """Wrap a list of recalled episodes with provenance.

        Args:
            episodes: List of Episode objects from recall()
            distances: Optional ChromaDB distances (1 - similarity)
            recalling_agent_id: Agent performing the recall
        """
        import time

        results: list[TransparentMemory] = []
        for i, episode in enumerate(episodes):
            episode_id = getattr(episode, "id", "")
            # Episode uses agent_ids (list), not agent_id (str)
            agent_ids = getattr(episode, "agent_ids", [])
            agent_id = agent_ids[0] if agent_ids else ""
            timestamp = getattr(episode, "timestamp", 0.0)
            # Episode uses user_input, not content
            content = getattr(episode, "user_input", "")
            # channel lives on episode.anchors (AnchorFrame), not directly on Episode
            anchors = getattr(episode, "anchors", None)
            channel = anchors.channel if anchors and hasattr(anchors, "channel") else "unknown"

            # Calculate similarity from distance
            distance = distances[i] if distances and i < len(distances) else 0.0
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

            results.append(TransparentMemory(
                content=content,
                provenance=provenance,
                episode=episode,
            ))

        return results

    def filter_by_confidence(
        self,
        memories: list[TransparentMemory],
        min_confidence: float = 0.5,
    ) -> list[TransparentMemory]:
        """Filter memories by minimum similarity score."""
        return [m for m in memories if m.provenance.similarity_score >= min_confidence]

    def format_for_prompt(
        self,
        memories: list[TransparentMemory],
        *,
        max_items: int = 5,
    ) -> str:
        """Format transparent memories for injection into agent prompt."""
        lines = []
        for m in memories[:max_items]:
            lines.append(m.render())
        return "\n".join(lines)
```

## Tests

**File:** `tests/test_ad678_memory_transparency.py`

7 tests:

1. `test_memory_provenance_creation` — create `MemoryProvenance`, verify fields
2. `test_memory_provenance_staleness` — create with `age_seconds=7200` →
   `is_stale == True`; create with `age_seconds=300` → `is_stale == False`
3. `test_confidence_labels` — verify `confidence_label` returns "high" for
   0.85, "moderate" for 0.6, "low" for 0.3
4. `test_transparent_memory_render` — create `TransparentMemory`, verify
   `render()` includes provenance tag prefix
5. `test_wrap_recall_results` — create mock episodes with timestamps,
   wrap with `MemoryTransparencyService`, verify provenance fields populated
6. `test_filter_by_confidence` — wrap 3 episodes with varying distances,
   filter with `min_confidence=0.5`, verify only high-confidence ones remain
7. `test_format_for_prompt` — verify `format_for_prompt()` returns multi-line
   string with provenance tags, respects `max_items` limit

## What This Does NOT Change

- `EpisodicMemory.recall()` unchanged — still returns list[Episode]
- `EpisodicMemory.store()` unchanged
- ChromaDB storage format unchanged
- ProvenanceTag/ProvenanceEnvelope from AD-677 unchanged (AD-678 is complementary,
  not a replacement — MemoryProvenance is memory-specific)
- Does NOT modify agent cognitive chain — callers opt-in to transparency
- Does NOT persist provenance metadata (ephemeral, created at recall time)
- Does NOT modify Episode dataclass

## Tracking

- `PROGRESS.md`: Add AD-678 as COMPLETE
- `docs/development/roadmap.md`: Update AD-678 status

## Acceptance Criteria

- `MemoryProvenance` captures episode source, age, confidence, ownership
- `TransparentMemory` wraps content + provenance with `render()` method
- `MemoryTransparencyService.wrap_recall_results()` converts episodes to transparent memories
- `filter_by_confidence()` filters by similarity threshold
- `format_for_prompt()` produces multi-line tagged output
- All 7 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# EpisodicMemory recall
grep -n "async def recall" src/probos/cognitive/episodic.py
  1440: recall(query, k=5) → list[Episode]
  1626: recall_for_agent(agent_id, query, k=5) → list[Episode]
  2067: recall_for_agent_scored(...)

# ChromaDB distances returned
grep -n "distances" src/probos/cognitive/episodic.py | head -5
  1456: include=["metadatas", "documents", "distances"]
  1465: distance = result["distances"][0][i]
  1466: similarity = 1.0 - distance

# Episode fields (types.py line 411)
# Episode.agent_ids: list[str] (NOT agent_id)
# Episode.user_input: str (NOT content)
# Episode.anchors: AnchorFrame | None (channel is on anchors, not Episode)

# No existing memory transparency
grep -rn "MemoryTransparency\|memory_transparency" src/probos/ → no matches
```
