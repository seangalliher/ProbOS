# AD-677: Context Provenance Metadata

**Status:** Ready for builder
**Dependencies:** None
**Estimated tests:** ~11

---

## Problem

Context injected into agent prompts has no provenance metadata. When the
TieredKnowledgeLoader (`tiered_knowledge.py`) injects knowledge snippets,
the agent cannot distinguish:
- Where the snippet came from (episodic memory vs records vs operational state)
- When it was retrieved (is it fresh or cached?)
- How confident the retrieval is (high relevance score vs marginal match?)

The Oracle Service (`oracle_service.py`) already produces `OracleResult` with
provenance, but this metadata is lost during context injection. Agents
receive the text content but not the source attribution.

## Fix

### Section 1: Create `ProvenanceTag` dataclass

**File:** `src/probos/cognitive/provenance.py` (new file)

```python
"""Context Provenance Metadata (AD-677).

Tags every piece of context injected into agent prompts with
source tier, retrieval timestamp, confidence score, and
staleness indicator.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProvenanceTag:
    """Metadata tag for a single piece of injected context."""

    source_tier: str  # "episodic" | "records" | "operational" | "archive" | "standing_orders"
    retrieval_timestamp: float  # When this content was retrieved
    confidence: float  # 0.0-1.0 relevance/confidence score
    content_hash: str  # First 8 chars of content hash for dedup detection
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
        return f"[source:{self.source_tier} confidence:{self.confidence:.2f} age:{age_str}{stale_marker}]"


def compute_content_hash(content: str) -> str:
    """Compute a short hash of content for dedup detection."""
    import hashlib
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
```

### Section 2: Add provenance-aware query function

**File:** `src/probos/cognitive/provenance.py` (same file as Section 1)

Add a standalone function that wraps OracleService.query() results with
provenance envelopes. This lives in `provenance.py` (not on TieredKnowledgeLoader)
because `TieredKnowledgeLoader` uses a `KnowledgeSourceProtocol` interface
(not OracleService directly), and `load_with_provenance` needs the Oracle's
`query()` which returns `OracleResult` with provenance fields.

```python
async def query_with_provenance(
    oracle: Any,
    *,
    query_text: str = "",
    agent_id: str = "",
    intent_type: str = "",
    k_per_tier: int = 5,
    tiers: list[str] | None = None,
) -> list[ProvenanceEnvelope]:
    """Query Oracle and wrap results with provenance metadata (AD-677).

    This is a standalone function that takes an OracleService instance.
    It does NOT modify TieredKnowledgeLoader — that system uses
    KnowledgeSourceProtocol, not OracleService.

    Args:
        oracle: OracleService instance with query() method
        query_text: Search query
        agent_id: Agent performing the query
        intent_type: Intent type for filtering
        k_per_tier: Results per tier
        tiers: Optional tier filter
    """
    try:
        results = await oracle.query(
            query_text=query_text or intent_type or "ambient",
            agent_id=agent_id,
            intent_type=intent_type,
            k_per_tier=k_per_tier,
            tiers=tiers,
        )
        return [ProvenanceEnvelope.from_oracle_result(r) for r in results]
    except Exception:
        logger.debug("AD-677: Provenance-tagged query failed", exc_info=True)
        return []
```

**Note:** `TieredKnowledgeLoader` is NOT modified. It uses `KnowledgeSourceProtocol`
(which has `load_episodes()`, `load_trust_snapshot()`, etc.) — NOT `OracleService.query()`.
The provenance query function is a separate entry point for callers that have
direct access to the Oracle.

### Section 3: Add `CONTEXT_PROVENANCE` event type

**File:** `src/probos/events.py`

Add after the `KNOWLEDGE_TIER_LOADED` event (line 169):

SEARCH:
```python
    KNOWLEDGE_TIER_LOADED = "knowledge_tier_loaded"
```

REPLACE:
```python
    KNOWLEDGE_TIER_LOADED = "knowledge_tier_loaded"
    CONTEXT_PROVENANCE_INJECTED = "context_provenance_injected"  # AD-677
```

### Section 4: Emit provenance events during context injection

**File:** `src/probos/cognitive/tiered_knowledge.py`

In the existing `load_ambient()`, `load_contextual()`, and `load_on_demand()`
methods, after the knowledge is loaded, emit a provenance event. Find the
existing `KnowledgeTierLoadedEvent` emission pattern:

```
grep -n "KnowledgeTierLoadedEvent" src/probos/cognitive/tiered_knowledge.py
```

After the existing event emission, add:

```python
            # AD-677: Emit provenance metadata
            if self._emit_event_fn:
                self._emit_event_fn(EventType.CONTEXT_PROVENANCE_INJECTED, {
                    "tier": tier_name,
                    "agent_id": agent_id,
                    "snippet_count": snippet_count,
                    "cached": was_cached,
                    "timestamp": time.time(),
                })
```

Verify `_emit_event_fn` attribute exists (it does — line 62):
```
grep -n "_emit_event_fn" src/probos/cognitive/tiered_knowledge.py
```

If the emission pattern uses a different mechanism, follow that pattern.

## Tests

**File:** `tests/test_ad677_context_provenance.py`

11 tests:

1. `test_provenance_tag_creation` — create a `ProvenanceTag`, verify fields
2. `test_provenance_tag_age` — create tag with past timestamp, verify `age_seconds > 0`
3. `test_provenance_tag_staleness` — tag with timestamp 10 minutes ago → `is_stale` is True
4. `test_provenance_tag_format_inline` — verify format string matches pattern
   `[source:episodic confidence:0.82 age:Xs]`
5. `test_provenance_tag_stale_marker` — stale tag includes "STALE" in format
6. `test_compute_content_hash` — same content → same hash, different content → different hash
7. `test_compute_content_hash_length` — hash is 8 characters
8. `test_provenance_envelope_render` — verify rendered output starts with provenance marker
9. `test_provenance_envelope_from_oracle_result` — create from mock `OracleResult`,
   verify `source_tier`, `confidence`, `content` map correctly
10. `test_context_provenance_event_type` — verify `EventType.CONTEXT_PROVENANCE_INJECTED` exists
11. `test_query_with_provenance` — mock OracleService with `query()` returning
    `OracleResult` objects, call `query_with_provenance()`, verify returns
    `ProvenanceEnvelope` objects with correct source_tier and confidence

## What This Does NOT Change

- Existing `load_ambient()`, `load_contextual()`, `load_on_demand()` return strings
  unchanged — backward compatible
- No changes to `OracleResult` or `OracleService` — provenance wrapping happens
  at the consumer side
- No changes to `compose_instructions()` — standing orders don't get provenance
  tags (they're static config, not retrieved content)
- Does NOT add provenance to NATS messages — this is about prompt injection only
- Does NOT modify the cognitive chain steps
- Does NOT add provenance persistence — tags are ephemeral (created at retrieval time)

## Tracking

- `PROGRESS.md`: Add AD-677 as COMPLETE
- `docs/development/roadmap.md`: Update AD-677 status

## Acceptance Criteria

- `ProvenanceTag` dataclass with source_tier, retrieval_timestamp, confidence, content_hash
- `ProvenanceEnvelope` wraps content + tag with `render()` method
- `query_with_provenance()` wraps OracleService results in envelopes
- `EventType.CONTEXT_PROVENANCE_INJECTED` exists
- Inline provenance format: `[source:X confidence:Y age:Z]`
- Staleness detection (>5min = stale)
- All 11 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# TieredKnowledgeLoader methods
grep -n "def load_ambient\|def load_contextual\|def load_on_demand" \
  src/probos/cognitive/tiered_knowledge.py
  66: load_ambient()
  103: load_contextual()
  147: load_on_demand()

# OracleResult definition
grep -n "class OracleResult" src/probos/cognitive/oracle_service.py
  22: @dataclass(frozen=True) — source_tier, content, score, metadata, provenance

# Existing provenance module
grep -n "anchor_provenance" src/probos/cognitive/anchor_provenance.py
  → different scope: anchor metadata for procedures, not context injection

# Knowledge loading config
grep -n "class KnowledgeLoadingConfig" src/probos/config.py
  658: ambient_token_budget=200, contextual=400, on_demand=600

# KnowledgeTierLoadedEvent
grep -n "KNOWLEDGE_TIER_LOADED" src/probos/events.py
  169: KNOWLEDGE_TIER_LOADED = "knowledge_tier_loaded"

# No existing context provenance
grep -rn "ProvenanceTag\|ProvenanceEnvelope\|CONTEXT_PROVENANCE" src/probos/ → no matches

# Existing provenance events
grep -n "CORROBORATION_PROVENANCE" src/probos/events.py
  158: CORROBORATION_PROVENANCE_VALIDATED — different scope (corroboration, not context)
```
