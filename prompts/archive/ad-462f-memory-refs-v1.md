# AD-462f v1 — Memory Architecture: Optimized Memory Representation (Retrieval-as-Pointers)

**Status:** Ready for Builder
**Closes:** GH issue #58 (single-wave full closure — pillars 1+2 already shipped via cited prior ADs; pillar 3 ships here)
**Wave:** 73
**Depends on:** AD-462e (OracleService, complete), AD-688 (KnowledgeGraph, complete), AD-686 (`runtime.oracle` public alias, complete), AD-696 (`oracle_lookup` QUERY op precedent, complete)
**Estimated tests:** +14 (window [+11, +15] → 11458–11462; baseline 11447 at HEAD `a63aa3e`)

---

## Problem

GH #58 names AD-462f as "Memory Architecture — Optimized Memory Representation" with three pillars:

> **Structured metadata, concept graphs, retrieval-as-pointers for memory optimization.**

When AD-462a–e shipped (2026-04 era 4 cluster), AD-462f was deferred at the time with the rationale *"AnchorFrame (AD-567a) covers near-term structured metadata needs."* (`decisions-era-4-evolution.md:2699`). The deferral reasoning is half-correct, half-stale:

- **Pillar 1 — Structured metadata:** ✅ Already shipped. `AnchorFrame` (AD-567a, `types.py:352`) provides typed temporal/spatial/social/causal/evidential/provenance anchors. `MemorySource` (AD-541) classifies acquisition. `Episode.importance` (AD-598) selective retention. `Episode.valid_from`/`valid_until` (AD-579b) temporal validity. **No new work needed for pillar 1.**
- **Pillar 2 — Concept graphs:** ✅ Already shipped. `KnowledgeEdgeStorage` (AD-688) + typed-triple traversal (AD-692) + post-merge graph expansion in `oracle_service.py:392` cover this pillar. Tier 6 in `OracleService.query()`. **No new work needed for pillar 2.**
- **Pillar 3 — Retrieval-as-pointers:** ❌ NOT yet shipped. At HEAD, every Oracle/recall path materializes full content into the prompt before the agent has decided which results matter. `OracleService.query_formatted()` (line 334) concatenates up to `max_chars=4000` characters across all 7 tiers and stuffs the whole blob into the LLM prompt. There is no API surface for an agent to receive lightweight pointers (id + score + tier + snippet) and selectively resolve only the ones it cares about.

**Net cost at HEAD:** Each Oracle dispatch (the AD-696 chain seam fires once per chain at ORACLE tier) burns ~2KB of prompt tokens whether the agent uses 1 result or 10. With 7 tiers × 3 results/tier × ~250 char/result, the upper bound is ~5KB, mostly dropped on the floor. Token efficiency is the immediate win; lazy hydration (deferred materialization) and stable cross-turn references (refs survive across chain steps) are the architectural wins.

**Closing GH #58 in one wave:** v1 ships pillar 3. PROGRESS.md / roadmap entries explicitly acknowledge pillars 1+2 as covered by AD-567a/541/598/579b/688/692/686. GH #58 closes on this commit.

---

## Solution Overview

Add a **lightweight projection layer** on top of `OracleService`:

1. New `MemoryRef` dataclass in `types.py` — frozen 7-field projection of an `OracleResult`.
2. `OracleService.query_refs(...)` — calls existing `query()`, projects to refs, populates an instance-scoped LRU cache keyed by `ref_id`. Returns `list[MemoryRef]`.
3. `OracleService.resolve_ref(ref_id)` — cache lookup, returns `OracleResult | None`. Tier-2 log-and-degrade on miss.
4. `OracleService.format_refs(refs, max_lines=10)` — short formatted projection (id + tier + score + snippet line) for prompt injection. Capped, no full content.
5. New `EventType.MEMORY_REFS_DISPATCHED`.
6. New QUERY operation `oracle_refs` in `sub_tasks/query.py` (parallel to `oracle_lookup`). Gated at `RecallTier.ENHANCED` (Lieutenant+) — refs are cheaper than full lookups, so access opens one tier earlier.
7. 14 boundary tests in `tests/test_ad462f_memory_refs.py`.

**Discipline (DLog #1):** v1 is **stateless from the chain's perspective** — refs never cross chain boundaries. Cache is bounded (256 entries), per-OracleService-instance, in-memory. Cross-conversation ref persistence is AD-462f-b. The cache exists solely so an agent's same-chain `format_refs()` rendering can show snippets cheaply while keeping a hydration door open for AD-462f-c.

---

## Architect calls (Decision Log)

15-item DLog — all decisions made up front so the Builder doesn't re-derive them.

**DLog #1 — Refs are an OPT-IN projection, not a replacement.** `query()` and `query_formatted()` keep their AD-462e contracts byte-for-byte. `query_refs()` is additive. No existing caller is migrated; AD-696's `oracle_lookup` op continues using `query_formatted()` as today. Migration is AD-462f-b's job after v1 adoption signals justify it.

**DLog #2 — `MemoryRef` lives in `types.py`, NOT `oracle_service.py`.** Refs may eventually be passed across module boundaries (mesh transport, working memory, episodic anchors). `types.py` is the canonical shared-types home — same precedent as `Episode`, `AnchorFrame`, `OracleResult`'s sibling types. Frozen dataclass, hashable via `ref_id`.

**DLog #3 — `ref_id` shape: `f"{tier}:{stable_key}"`.** Per-tier stable keys derived from existing `OracleResult.metadata`:
- `episodic` → `metadata["episode_id"]`
- `records` → `metadata["path"]` (file path is stable for ship's records)
- `operational` → `metadata["path"]`
- `archive` → `metadata.get("archive_id")` if present, else `metadata.get("path", "")`
- `semantic` → `metadata.get("collection", "?") + ":" + metadata.get("id", "")` (semantic layer keys vary by collection; v1 uses whatever's in metadata)
- `graph` → `metadata.get("edge_id", "")`
- `health` → `metadata.get("snapshot_key", "")` (synthetic; v1 falls back to `f"health:{result_index}"`)

Empty stable keys fall back to `f"{tier}:idx{i}"` so collisions are avoided within a single query. **This is a v1 simplification** — AD-462f-d will tighten metadata contracts per tier.

**DLog #4 — Cache is `OrderedDict`-backed LRU, 256 entries, instance-scoped.** Standard eviction: `move_to_end` on hit, `popitem(last=False)` on overflow. Not async-locked — `query_refs()` and `resolve_ref()` are mutex-safe by virtue of asyncio single-thread semantics; we never `await` between cache mutation and return. No TTL in v1 (LRU eviction is sufficient bound).

**DLog #5 — `resolve_ref` returns `OracleResult | None`, NOT raises on miss.** Cache miss is a normal degradation (refs from an old chain, agent re-using a ref after eviction). Tier-2 log-and-degrade per copilot-instructions exception tiers.

**DLog #6 — `format_refs` cap is `max_lines=10` default.** Each line ≤120 chars (id 60 + score 5 + snippet 50ish). Worst-case ~1.2KB — half the cost of `query_formatted`'s 2KB cap, exactly the token-efficiency win.

**DLog #7 — `oracle_refs` QUERY op gates at `RecallTier.ENHANCED`, NOT ORACLE.** Refs are intentionally cheaper than `oracle_lookup`. Lieutenant+ agents can query refs (snippet preview) but can't see full content unless they escalate the chain to ORACLE tier and run `oracle_lookup` separately. The tier gradient is the v1 governance lever.

**DLog #8 — Use existing `runtime.oracle` public alias (AD-686), NOT `runtime._oracle_service`.** Mirror AD-696's pattern at `query.py:269`. Wave-5 convention #1 enforced.

**DLog #9 — One new EventType: `MEMORY_REFS_DISPATCHED`.** Insert immediately after `ORACLE_LOOKUP_DISPATCHED` at `events.py:235`. Payload mirrors `ORACLE_LOOKUP_DISPATCHED` — `agent_id`, `agent_type`, `query_text`, `tiers`, `ref_count` (replaces `result_chars` since refs are counted, not measured in chars).

**DLog #10 — No new Pydantic config.** Cache size (256) and `format_refs` cap (`max_lines=10`) are inline module constants — `_MEMORY_REF_CACHE_SIZE` and `_FORMAT_REFS_DEFAULT_LINES` in `oracle_service.py`. Mirrors AD-696's "no new config" discipline (AD-696 DLog #10). v2 may escalate to config if adoption signals justify.

**DLog #11 — Empty-input + missing-runtime short-circuits return empty list / `None` (NOT raise).** `query_refs("")` → `[]`. `query_refs` when `runtime.oracle` is absent → caller-side responsibility (the QUERY op handles this; the OracleService method never sees None runtime). `resolve_ref(unknown_id)` → `None`.

**DLog #12 — `MemoryRef` is `frozen=True` with `eq=True`.** Hashable. Refs can be deduplicated, set-membered, and used as dict keys for downstream caches (AD-462f-b will use this for cross-step ref reuse).

**DLog #13 — No ANALYZE intent signal in v1.** Adding a third intent token (`memory_refs` alongside `oracle_query` from AD-696) inflates the ANALYZE prompt without a clear forcing function — at HEAD there is no chain dispatch site that could benefit yet. The chain wiring is AD-462f-b's job; v1 ships the tool surface only. Skill agents and slash commands can call `query_refs` directly via `runtime.oracle.query_refs(...)`.

**DLog #14 — No ToolRegistry registration in v1.** Same root cause as AD-696's deferred Section 4: `init_communication()` lacks a `runtime` parameter at HEAD (`startup/communication.py`), so registering the bound method requires upstream plumbing that's out of scope for this AD. Forcing function: AD-462f-1 (mirrors AD-696-1) lands this once `init_communication` signature is updated. The QUERY op (Section 4 of this prompt) gives chain-internal access; the ToolRegistry path is for utility agents and MCP bridge.

**DLog #15 — Commercial-leak audit: clean.** AD-462f is OSS plumbing — one dataclass, one EventType, three OracleService methods, one QUERY op, one cache. No pricing, no enterprise gating, no SaaS overlay. The deferred children (AD-462f-1 ToolRegistry, AD-462f-b ANALYZE/chain wiring, AD-462f-c cross-conversation persistence, AD-462f-d per-tier metadata contracts) all remain OSS.

---

## Implementation

### Section 0 — `events.py` (new EventType)

**File:** `src/probos/events.py`
**Operation:** SEARCH/REPLACE (single insert).

```python
===SEARCH===
    ORACLE_LOOKUP_DISPATCHED = "oracle_lookup_dispatched"  # AD-696
===REPLACE===
    ORACLE_LOOKUP_DISPATCHED = "oracle_lookup_dispatched"  # AD-696
    MEMORY_REFS_DISPATCHED = "memory_refs_dispatched"  # AD-462f
===END REPLACE===
```

### Section 1 — `types.py` (`MemoryRef` dataclass)

**File:** `src/probos/types.py`
**Operation:** SEARCH/REPLACE (single insert immediately after `RecallScore` and before `Episode`).

Anchor: `class RecallScore` (line 397) and `class Episode` (line 411). Insert between them.

```python
===SEARCH===
@dataclass(frozen=True)
class Episode:
    """A recorded episode from the cognitive pipeline."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
===REPLACE===
@dataclass(frozen=True)
class MemoryRef:
    """AD-462f: Lightweight projection of an OracleResult — retrieval-as-pointers.

    A ``MemoryRef`` is the surface representation of a memory-tier hit:
    enough information to render a one-line preview in a prompt and to
    resolve the full ``OracleResult`` later via
    ``OracleService.resolve_ref(ref_id)``. Refs are token-efficient (≤200
    char snippet vs. full content), stable within an OracleService
    instance's LRU cache lifetime, and hashable so consumers can dedupe.

    See ``decisions-era-4-evolution.md`` AD-462f for design rationale and
    the deferral chain (462f-b/c/d).
    """

    ref_id: str               # f"{tier}:{stable_key}" — see AD-462f DLog #3
    tier: str                 # "episodic" | "records" | "operational" | "archive" | "semantic" | "graph" | "health"
    score: float              # 0.0–1.0 (mirrors OracleResult.score)
    snippet: str              # ≤200 chars (truncated content preview)
    provenance: str           # human-readable tag (e.g. "[episodic memory]")
    timestamp: float = 0.0    # original event timestamp (0.0 if tier-irrelevant)
    # AD-462f DLog #12: metadata is excluded from hash/eq so the dataclass
    # remains hashable despite carrying a dict. Identity is driven by
    # (ref_id, tier, score, snippet, provenance, timestamp) — same-ref_id
    # refs from the same query compare equal regardless of metadata churn.
    metadata: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)


@dataclass(frozen=True)
class Episode:
    """A recorded episode from the cognitive pipeline."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
===END REPLACE===
```

### Section 2 — `oracle_service.py` (cache constants + 3 new methods)

**File:** `src/probos/cognitive/oracle_service.py`

#### Section 2.1 — Module-level constants (DLog #10)

Insert immediately after the existing `_GRAPH_*` constants block (around line 50, before `_GRAPH_STOPWORDS`).

Anchor: `_GRAPH_MIN_TOKEN_LEN = 3`.

```python
===SEARCH===
_GRAPH_EXPANSION_DISCOUNT = 0.7  # parent_score × this × edge.weight × edge.confidence
_GRAPH_MIN_TOKEN_LEN = 3
===REPLACE===
_GRAPH_EXPANSION_DISCOUNT = 0.7  # parent_score × this × edge.weight × edge.confidence
_GRAPH_MIN_TOKEN_LEN = 3

# AD-462f: Memory-ref projection tunables — inline caps, NOT config (AD-462f DLog #10).
_MEMORY_REF_CACHE_SIZE = 256          # OracleService instance-scoped LRU bound
_MEMORY_REF_SNIPPET_CHARS = 200       # MemoryRef.snippet cap
_FORMAT_REFS_DEFAULT_LINES = 10       # default cap for format_refs() output
_FORMAT_REFS_LINE_CHAR_CAP = 120      # per-line cap inside format_refs()
===END REPLACE===
```

#### Section 2.2 — `OrderedDict` import + cache field on `__init__`

Anchor: top of file imports + `__init__`.

```python
===SEARCH===
import logging
import time
from dataclasses import dataclass
from typing import Any
===REPLACE===
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from probos.types import MemoryRef  # AD-462f (types.py has no reverse dep on oracle_service)
===END REPLACE===
```

```python
===SEARCH===
        self._semantic_layer = semantic_layer  # AD-686 (Tier 5)
        self._knowledge_graph = knowledge_graph  # AD-688 (Tier 6)
        self._health_provider = health_provider  # AD-695 (Tier 7)

    def attach_semantic_layer(self, semantic_layer: Any) -> None:
===REPLACE===
        self._semantic_layer = semantic_layer  # AD-686 (Tier 5)
        self._knowledge_graph = knowledge_graph  # AD-688 (Tier 6)
        self._health_provider = health_provider  # AD-695 (Tier 7)
        # AD-462f: Instance-scoped LRU for resolve_ref(). Bounded by
        # _MEMORY_REF_CACHE_SIZE; OrderedDict eviction (oldest first).
        self._ref_cache: OrderedDict[str, OracleResult] = OrderedDict()

    def attach_semantic_layer(self, semantic_layer: Any) -> None:
===END REPLACE===
```

#### Section 2.3 — `_derive_ref_id` helper

Insert immediately after `_format_age` (around line 110, before `class OracleService`).

```python
===SEARCH===
def _format_age(timestamp: float) -> str:
    """Format a timestamp as a human-readable age string."""
    delta = time.time() - timestamp
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


class OracleService:
===REPLACE===
def _format_age(timestamp: float) -> str:
    """Format a timestamp as a human-readable age string."""
    delta = time.time() - timestamp
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


def _derive_ref_id(result: OracleResult, fallback_index: int) -> str:
    """AD-462f: Derive a stable ``ref_id`` from a tier result's metadata.

    Format: ``f"{tier}:{stable_key}"``. Per AD-462f DLog #3, each tier
    has a designated metadata key. Empty/missing keys fall back to
    ``f"{tier}:idx{fallback_index}"`` so collisions within a single
    ``query_refs()`` call are avoided.
    """
    md = result.metadata or {}
    tier = result.source_tier
    if tier == "episodic":
        key = md.get("episode_id", "")
    elif tier in ("records", "operational"):
        key = md.get("path", "")
    elif tier == "archive":
        key = md.get("archive_id") or md.get("path", "")
    elif tier == "semantic":
        coll = md.get("collection", "?")
        sid = md.get("id", "")
        key = f"{coll}:{sid}" if sid else ""
    elif tier == "graph":
        key = md.get("edge_id", "")
    elif tier == "health":
        key = md.get("snapshot_key", "")
    else:
        key = ""
    if not key:
        key = f"idx{fallback_index}"
    return f"{tier}:{key}"


class OracleService:
===END REPLACE===
```

#### Section 2.4 — `query_refs` / `resolve_ref` / `format_refs` methods

Insert immediately after `query_formatted` (which ends around line 380, just before `# -- Private tier query methods --`).

```python
===SEARCH===
        lines.append("=== END ORACLE RESULTS ===")
        return "\n".join(lines)

    # -- Private tier query methods --
===REPLACE===
        lines.append("=== END ORACLE RESULTS ===")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # AD-462f: Retrieval-as-pointers — lightweight projection layer.
    # ------------------------------------------------------------------
    async def query_refs(
        self,
        query_text: str,
        *,
        agent_id: str = "",
        intent_type: str = "",
        k_per_tier: int = 3,
        tiers: list[str] | None = None,
    ) -> list["MemoryRef"]:
        """AD-462f: Query and return lightweight ``MemoryRef`` projections.

        Calls the existing :meth:`query` pipeline and projects each
        ``OracleResult`` to a ``MemoryRef`` (id + tier + score + snippet
        + provenance + metadata). Populates the instance LRU so
        :meth:`resolve_ref` can later return the full result. Empty input
        short-circuits to ``[]``.
        """
        if not query_text:
            return []

        results = await self.query(
            query_text, agent_id=agent_id, intent_type=intent_type,
            k_per_tier=k_per_tier, tiers=tiers,
        )
        if not results:
            return []

        refs: list[MemoryRef] = []
        for i, r in enumerate(results):
            ref_id = _derive_ref_id(r, i)
            snippet = (r.content or "")[:_MEMORY_REF_SNIPPET_CHARS]
            timestamp = float(r.metadata.get("timestamp", 0.0) or 0.0)
            ref_metadata = {
                k: v for k, v in (r.metadata or {}).items()
                if k in ("episode_id", "path", "edge_id", "collection", "id",
                         "archive_id", "snapshot_key", "agent_scope")
            }
            refs.append(MemoryRef(
                ref_id=ref_id,
                tier=r.source_tier,
                score=float(r.score),
                snippet=snippet,
                provenance=r.provenance,
                timestamp=timestamp,
                metadata=ref_metadata,
            ))
            # LRU populate (most-recent first)
            self._ref_cache[ref_id] = r
            self._ref_cache.move_to_end(ref_id)
            while len(self._ref_cache) > _MEMORY_REF_CACHE_SIZE:
                self._ref_cache.popitem(last=False)

        return refs

    def resolve_ref(self, ref_id: str) -> OracleResult | None:
        """AD-462f: Re-hydrate a ``MemoryRef`` to its full ``OracleResult``.

        Cache lookup over the instance-scoped LRU populated by
        :meth:`query_refs`. Cache miss returns ``None`` (Tier-2
        log-and-degrade per AD-462f DLog #5). LRU updates on hit so
        repeatedly-resolved refs stay warm.
        """
        if not ref_id:
            return None
        result = self._ref_cache.get(ref_id)
        if result is None:
            logger.debug("AD-462f: resolve_ref miss — ref_id=%s", ref_id)
            return None
        self._ref_cache.move_to_end(ref_id)
        return result

    @staticmethod
    def format_refs(
        refs: list["MemoryRef"], *, max_lines: int = _FORMAT_REFS_DEFAULT_LINES,
    ) -> str:
        """AD-462f: Render ``MemoryRef`` list as a short prompt-ready block.

        Each line: ``[tier] ref_id (score: 0.NN) snippet``. Hard caps per
        AD-462f DLog #6 — ``max_lines`` lines, ``_FORMAT_REFS_LINE_CHAR_CAP``
        chars per line. Returns empty string for empty input.
        """
        if not refs:
            return ""
        out = ["=== MEMORY REFS ==="]
        for ref in refs[:max_lines]:
            line = f"[{ref.tier}] {ref.ref_id} (score: {ref.score:.2f}) {ref.snippet}"
            if len(line) > _FORMAT_REFS_LINE_CHAR_CAP:
                line = line[: _FORMAT_REFS_LINE_CHAR_CAP - 1] + "…"
            out.append(line)
        out.append("=== END MEMORY REFS ===")
        return "\n".join(out)

    # -- Private tier query methods --
===END REPLACE===
```

### Section 3 — `sub_tasks/query.py` (`oracle_refs` QUERY op)

**File:** `src/probos/cognitive/sub_tasks/query.py`

#### Section 3.1 — New op handler

Insert immediately after `_query_oracle_lookup` (end of function, before `_query_introspective_telemetry`).

Anchor: the closing `return {"oracle_lookup": formatted}` line.

```python
===SEARCH===
    return {"oracle_lookup": formatted}


async def _query_introspective_telemetry(
===REPLACE===
    return {"oracle_lookup": formatted}


async def _query_oracle_refs(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """AD-462f: Memory-refs retrieval — lightweight projection of Oracle results.

    Reads ``oracle_query_text`` (required) and optional ``oracle_tiers`` from
    context. Returns ``{"oracle_refs": <formatted refs str>}``. Tier-2
    log-and-degrade: returns empty string on (1) ``runtime.oracle`` not
    attached, (2) ``oracle_query_text`` empty, (3) ``context["_recall_tier"]``
    below ``RecallTier.ENHANCED``, (4) Oracle raises. Emits
    ``MEMORY_REFS_DISPATCHED`` only on a non-empty dispatch.

    Tier gate is intentionally lower than ``oracle_lookup`` (AD-696, ORACLE
    only) — refs are cheaper than full lookups, so Lieutenant+ rank can
    query refs as an early-screen step. Per AD-462f DLog #7.
    """
    query_text = (context.get("oracle_query_text") or "").strip()
    if not query_text:
        return {"oracle_refs": ""}

    from probos.earned_agency import RecallTier, _TIER_ORDER
    tier = context.get("_recall_tier")
    if tier is None or _TIER_ORDER.get(tier, -1) < _TIER_ORDER[RecallTier.ENHANCED]:
        logger.debug(
            "AD-462f: oracle_refs denied — recall_tier=%s (need ENHANCED+)", tier,
        )
        return {"oracle_refs": ""}

    oracle = getattr(runtime, "oracle", None)
    if oracle is None:
        logger.debug("AD-462f: oracle_refs — runtime.oracle not attached")
        return {"oracle_refs": ""}

    tiers = context.get("oracle_tiers")
    agent_id = context.get("_agent_id", "") or _ctx(context, "agent_id")

    try:
        refs = await oracle.query_refs(
            query_text=query_text,
            agent_id=agent_id,
            k_per_tier=3,
            tiers=tiers,
        )
    except Exception:
        logger.warning(
            "AD-462f: oracle_refs query failed for agent %s", agent_id,
            exc_info=True,
        )
        return {"oracle_refs": ""}

    if not refs:
        return {"oracle_refs": ""}

    formatted = oracle.format_refs(refs)

    emit_fn = context.get("_emit_event_fn")
    if emit_fn is not None:
        try:
            from probos.events import EventType
            emit_fn(EventType.MEMORY_REFS_DISPATCHED, {
                "agent_id": agent_id,
                "agent_type": context.get("_agent_type", ""),
                "query_text": query_text,
                "tiers": tiers or [],
                "ref_count": len(refs),
            })
        except Exception:
            logger.warning("AD-462f: MEMORY_REFS_DISPATCHED emit failed", exc_info=True)

    return {"oracle_refs": formatted}


async def _query_introspective_telemetry(
===END REPLACE===
```

#### Section 3.2 — Dispatch table entry

Anchor: existing `"oracle_lookup": _query_oracle_lookup,` line.

```python
===SEARCH===
    "oracle_lookup": _query_oracle_lookup,                       # AD-696
}
===REPLACE===
    "oracle_lookup": _query_oracle_lookup,                       # AD-696
    "oracle_refs": _query_oracle_refs,                           # AD-462f
}
===END REPLACE===
```

### Section 4 — Tests (`tests/test_ad462f_memory_refs.py`)

**File:** `tests/test_ad462f_memory_refs.py` (NEW)
**Operation:** CREATE

Net-new test file. 14 tests. Use `MagicMock` runtime + a real `OracleService` instance with `MagicMock` tier dependencies (Wave 13/66/67/68/69/70/72 fixture precedent — never boot a `ProbOSRuntime`).

```python
"""AD-462f: Memory Architecture — Optimized Memory Representation.

Tests cover the retrieval-as-pointers projection layer:
  - MemoryRef dataclass shape + hashability
  - OracleService.query_refs() projection + LRU population
  - OracleService.resolve_ref() cache hit/miss
  - OracleService.format_refs() rendering caps
  - _query_oracle_refs QUERY op (gate, success, failure modes)
  - _derive_ref_id stable-key derivation per tier

Wave 73 / GH #58. 14 tests target +14 (window [+11, +15] → 11458–11462).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.oracle_service import (
    _MEMORY_REF_CACHE_SIZE,
    _derive_ref_id,
    OracleResult,
    OracleService,
)
from probos.cognitive.sub_tasks.query import _query_oracle_refs
from probos.earned_agency import RecallTier
from probos.events import EventType
from probos.types import MemoryRef


def _make_result(tier: str, content: str, score: float, **md: Any) -> OracleResult:
    return OracleResult(
        source_tier=tier, content=content, score=score,
        metadata=dict(md), provenance=f"[{tier}]",
    )


def _make_oracle_with_results(results: list[OracleResult]) -> OracleService:
    """Build an OracleService whose query() returns a fixed list."""
    svc = OracleService()
    svc.query = AsyncMock(return_value=results)  # type: ignore[method-assign]
    return svc


# --- 1. MemoryRef dataclass shape + hashability ---

def test_memory_ref_is_frozen_and_hashable():
    ref = MemoryRef(
        ref_id="episodic:abc", tier="episodic", score=0.9,
        snippet="hello", provenance="[episodic]",
    )
    with pytest.raises(Exception):
        ref.score = 0.5  # type: ignore[misc]
    # Hashable
    assert {ref} == {ref}
    # Eq by ref_id (full-tuple eq, but ref_id drives identity in practice)
    other = MemoryRef(
        ref_id="episodic:abc", tier="episodic", score=0.9,
        snippet="hello", provenance="[episodic]",
    )
    assert ref == other


# --- 2. _derive_ref_id per tier ---

def test_derive_ref_id_episodic_uses_episode_id():
    r = _make_result("episodic", "x", 0.5, episode_id="ep_42")
    assert _derive_ref_id(r, 0) == "episodic:ep_42"


def test_derive_ref_id_records_uses_path():
    r = _make_result("records", "x", 0.5, path="ship_records/foo.md")
    assert _derive_ref_id(r, 0) == "records:ship_records/foo.md"


def test_derive_ref_id_graph_uses_edge_id():
    r = _make_result("graph", "x", 0.5, edge_id="e_99")
    assert _derive_ref_id(r, 0) == "graph:e_99"


def test_derive_ref_id_falls_back_to_idx_when_metadata_empty():
    r = _make_result("episodic", "x", 0.5)
    assert _derive_ref_id(r, 7) == "episodic:idx7"


# --- 3. query_refs projection + LRU population ---

@pytest.mark.asyncio
async def test_query_refs_projects_results_to_memory_refs():
    results = [
        _make_result("episodic", "alpha content", 0.9, episode_id="ep_1", timestamp=100.0),
        _make_result("graph", "beta content", 0.7, edge_id="e_5"),
    ]
    svc = _make_oracle_with_results(results)
    refs = await svc.query_refs("test query")
    assert len(refs) == 2
    assert refs[0].ref_id == "episodic:ep_1"
    assert refs[0].snippet == "alpha content"
    assert refs[0].timestamp == 100.0
    assert refs[1].tier == "graph"
    # LRU populated
    assert "episodic:ep_1" in svc._ref_cache
    assert "graph:e_5" in svc._ref_cache


@pytest.mark.asyncio
async def test_query_refs_empty_query_returns_empty_list_no_query_call():
    svc = _make_oracle_with_results([])
    refs = await svc.query_refs("")
    assert refs == []
    svc.query.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_query_refs_truncates_snippet_to_200_chars():
    long = "x" * 500
    svc = _make_oracle_with_results([_make_result("episodic", long, 0.5, episode_id="e1")])
    refs = await svc.query_refs("q")
    assert len(refs[0].snippet) == 200


# --- 4. resolve_ref cache hit/miss ---

@pytest.mark.asyncio
async def test_resolve_ref_returns_full_result_on_hit():
    full = _make_result("episodic", "full body", 0.9, episode_id="ep_1")
    svc = _make_oracle_with_results([full])
    refs = await svc.query_refs("q")
    resolved = svc.resolve_ref(refs[0].ref_id)
    assert resolved is full
    assert resolved.content == "full body"


def test_resolve_ref_returns_none_on_miss():
    svc = OracleService()
    assert svc.resolve_ref("episodic:nope") is None
    assert svc.resolve_ref("") is None


@pytest.mark.asyncio
async def test_query_refs_lru_evicts_oldest_at_cap():
    # Pack the cache to exactly _MEMORY_REF_CACHE_SIZE + 5 entries; oldest 5 should evict.
    cap = _MEMORY_REF_CACHE_SIZE
    overflow = 5
    results = [
        _make_result("episodic", f"c{i}", 0.5, episode_id=f"ep_{i}")
        for i in range(cap + overflow)
    ]
    svc = _make_oracle_with_results(results)
    await svc.query_refs("q")
    assert len(svc._ref_cache) == cap
    # Oldest 5 (ep_0..ep_4) should be gone
    assert "episodic:ep_0" not in svc._ref_cache
    assert "episodic:ep_4" not in svc._ref_cache
    assert "episodic:ep_5" in svc._ref_cache
    assert f"episodic:ep_{cap + overflow - 1}" in svc._ref_cache


# --- 5. format_refs rendering ---

def test_format_refs_empty_returns_empty_string():
    assert OracleService.format_refs([]) == ""


def test_format_refs_caps_at_max_lines():
    refs = [
        MemoryRef(
            ref_id=f"episodic:e{i}", tier="episodic", score=0.5,
            snippet=f"snippet {i}", provenance="[episodic]",
        )
        for i in range(20)
    ]
    out = OracleService.format_refs(refs, max_lines=5)
    # Header + 5 refs + footer = 7 lines
    assert out.count("\n") == 6
    assert "=== MEMORY REFS ===" in out
    assert "=== END MEMORY REFS ===" in out
    assert "episodic:e0" in out
    assert "episodic:e6" not in out


# --- 6. _query_oracle_refs QUERY op ---

@pytest.mark.asyncio
async def test_query_oracle_refs_denies_below_enhanced_tier():
    runtime = MagicMock()
    runtime.oracle = MagicMock()
    spec = MagicMock()
    context = {
        "oracle_query_text": "alpha incident",
        "_recall_tier": RecallTier.BASIC,  # below ENHANCED
    }
    out = await _query_oracle_refs(runtime, spec, context)
    assert out == {"oracle_refs": ""}
    runtime.oracle.query_refs.assert_not_called()


@pytest.mark.asyncio
async def test_query_oracle_refs_emits_event_on_success():
    runtime = MagicMock()
    refs = [MemoryRef(
        ref_id="episodic:e1", tier="episodic", score=0.8,
        snippet="hello", provenance="[episodic]",
    )]
    runtime.oracle = MagicMock()
    runtime.oracle.query_refs = AsyncMock(return_value=refs)
    runtime.oracle.format_refs = MagicMock(return_value="=== MEMORY REFS ===\n[episodic] episodic:e1 (score: 0.80) hello\n=== END MEMORY REFS ===")
    emit_fn = MagicMock()
    spec = MagicMock()
    context = {
        "oracle_query_text": "alpha incident",
        "_recall_tier": RecallTier.ENHANCED,
        "_agent_id": "test_agent",
        "_emit_event_fn": emit_fn,
    }
    out = await _query_oracle_refs(runtime, spec, context)
    assert "episodic:e1" in out["oracle_refs"]
    emit_fn.assert_called_once()
    args = emit_fn.call_args[0]
    assert args[0] == EventType.MEMORY_REFS_DISPATCHED
    payload = args[1]
    assert payload["ref_count"] == 1
    assert payload["agent_id"] == "test_agent"


@pytest.mark.asyncio
async def test_query_oracle_refs_returns_empty_when_runtime_oracle_missing():
    runtime = MagicMock(spec=[])  # no `oracle` attr
    spec = MagicMock()
    context = {
        "oracle_query_text": "q",
        "_recall_tier": RecallTier.ENHANCED,
    }
    out = await _query_oracle_refs(runtime, spec, context)
    assert out == {"oracle_refs": ""}
```

### Section 5 — Tracking updates

#### 5.1 PROGRESS.md (CLOSED paragraph after Wave 72)

Append a new "Wave 73 (closed) — AD-462f v1" entry under the same heading style as the existing Wave 72 entry. Cite test count delta and the explicit pillar coverage.

#### 5.2 docs/development/roadmap.md

Flip the AD-462f roadmap entry from `*(planned)*` to:

```
- **AD-462f: Optimized Memory Representation** *(complete via AD-462f v1, Wave 73, GH #58)* — Three pillars resolved: (1) Structured metadata covered by AD-567a (AnchorFrame), AD-541 (MemorySource), AD-598 (importance), AD-579b (temporal validity); (2) Concept graphs covered by AD-688 (KnowledgeEdgeStorage) + AD-692 (typed-triple traversal) + Tier 6 in OracleService; (3) Retrieval-as-pointers shipped here — `MemoryRef` projection dataclass, `OracleService.query_refs/resolve_ref/format_refs` LRU-backed cache (256 entries), `oracle_refs` QUERY op gated at RecallTier.ENHANCED, `MEMORY_REFS_DISPATCHED` event. Deferred children: AD-462f-1 (ToolRegistry registration; same root cause as AD-696-1 — `init_communication` signature), AD-462f-b (ANALYZE intent signal + chain dispatch seam), AD-462f-c (cross-conversation ref persistence), AD-462f-d (per-tier metadata contracts).
```

#### 5.3 prompts/wave-plan.yaml

Wave 73 entry — see WAVE-73-DISPATCH.md.

#### 5.4 GitHub issue #58

Close with comment listing: (1) the three pillars and how they were resolved (citing AD numbers), (2) the new public surface (`MemoryRef`, `query_refs`, `resolve_ref`, `format_refs`, `oracle_refs` op, `MEMORY_REFS_DISPATCHED`), (3) the four deferred children (AD-462f-1/b/c/d) with one-line forcing functions, (4) the commit hash.

#### 5.5 DECISIONS.md

Append `### AD-462f: Optimized Memory Representation v1` entry to the Era 4 file (`decisions-era-4-evolution.md`). Replace the existing `| AD-462f | DEFERRED — concept graphs, AnchorFrame sufficient for now |` table row with `| AD-462f | COMPLETE via Wave 73 — pillars 1+2 covered by intervening ADs (567a/541/598/579b/688/692), pillar 3 (retrieval-as-pointers) shipped as MemoryRef + LRU resolve cache + oracle_refs QUERY op |`.

---

## What This AD Does NOT Change

1. `OracleService.query()` and `OracleService.query_formatted()` signatures and behavior. Byte-for-byte preserved per DLog #1.
2. `oracle_lookup` QUERY op (AD-696). Continues to use `query_formatted` as today.
3. Any tier-side internal API (no `get_by_id` added on EpisodicMemory, RecordsStore, KnowledgeStore, KnowledgeGraph, SemanticKnowledgeLayer, ArchiveStore, or HealthProvider). Resolution is purely cache-backed in v1.
4. ANALYZE prompt at `analyze.py`. Per DLog #13, no new intent signal.
5. `cognitive_agent.py` chain dispatch. No new chain seam in v1.
6. `startup/communication.py`. No new tool registration in v1 (same root cause as deferred AD-696 Section 4 — DLog #14).
7. `runtime.py`. No new wiring; `runtime.oracle` already attached.
8. `config.py` / `system.yaml`. Per DLog #10, zero new config fields.
9. `Episode` / `AnchorFrame` / `OracleResult` types. `MemoryRef` is additive, not a substitute.
10. Any HXI surface or panels.py rendering. UI integration is a future AD.

---

## Acceptance Criteria

1. Full gate passes at 11461 ± 2 (target +14; window [11458, 11462]).
2. All Section 0–4 SEARCH/REPLACE / CREATE blocks applied byte-for-byte.
3. 14 new tests in `tests/test_ad462f_memory_refs.py` all pass.
4. No file outside the dispatch's named set is modified other than tracking files (`PROGRESS.md`, `docs/development/roadmap.md`, `prompts/wave-plan.yaml`, `decisions-era-4-evolution.md`).
5. Builder build report cites:
   - Test count delta.
   - The ten "What This AD Does NOT Change" verifications.
   - The four deferred children (AD-462f-1/b/c/d) and their forcing functions.
   - Confirmation that pillars 1 and 2 of GH #58 are documented as covered by prior ADs (no new code required).
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-05-05, HEAD `a63aa3e`)

```
grep -n "ORACLE_LOOKUP_DISPATCHED" src/probos/events.py
  235:    ORACLE_LOOKUP_DISPATCHED = "oracle_lookup_dispatched"  # AD-696
  (Section 0 SEARCH anchor confirmed; MEMORY_REFS_DISPATCHED collision-free)

grep -n "class RecallScore\|class Episode" src/probos/types.py
  397: class RecallScore:
  411: class Episode:
  (Section 1 insertion site between RecallScore (397) and Episode (411) confirmed)

grep -n "_GRAPH_MIN_TOKEN_LEN\|_GRAPH_STOPWORDS" src/probos/cognitive/oracle_service.py
  44: _GRAPH_MIN_TOKEN_LEN = 3
  (Section 2.1 SEARCH anchor confirmed)

grep -n "self._health_provider = health_provider" src/probos/cognitive/oracle_service.py
  (Section 2.2 SEARCH anchor confirmed; OrderedDict import + cache field insertion)

grep -n "def _format_age" src/probos/cognitive/oracle_service.py
  103: def _format_age(timestamp: float) -> str:
  (Section 2.3 SEARCH anchor confirmed; _derive_ref_id insertion before class OracleService)

grep -n "=== END ORACLE RESULTS ===" src/probos/cognitive/oracle_service.py
  (Section 2.4 SEARCH anchor confirmed; insert after query_formatted)

grep -n "return {\"oracle_lookup\": formatted}" src/probos/cognitive/sub_tasks/query.py
  306:    return {"oracle_lookup": formatted}
  (Section 3.1 SEARCH anchor confirmed)

grep -n "\"oracle_lookup\": _query_oracle_lookup" src/probos/cognitive/sub_tasks/query.py
  359:    "oracle_lookup": _query_oracle_lookup,                       # AD-696
  (Section 3.2 SEARCH anchor confirmed)

grep -n "class RecallTier\|_TIER_ORDER" src/probos/earned_agency.py
  53: class RecallTier(str, Enum):
  92: _TIER_ORDER: dict[RecallTier, int] = {
  94:     RecallTier.ENHANCED: 1,
  (DLog #7 RecallTier.ENHANCED gate logic — _TIER_ORDER is the live ordering helper at HEAD a63aa3e; module-private but cross-module import mirrors the existing `from probos.earned_agency import RecallTier` pattern in AD-696's _query_oracle_lookup at query.py:256)

grep -n "self.oracle = cog.oracle_service" src/probos/runtime.py
  1349:    self.oracle = cog.oracle_service  # AD-686 (public alias)
  (DLog #8 — public seam exists at HEAD; matches AD-696 precedent)

grep -rn "test_ad462f" tests/
  (no matches — net-new test file confirmed)

grep -n "AD-462f" docs/development/roadmap.md
  4177: > - **AD-462f: Optimized Memory Representation** *(planned)* —
        Structured metadata, concept graphs, retrieval-as-pointers.
  (roadmap source-of-truth; flip to *(complete via AD-462f v1, Wave 73, GH #58)* per Section 5.2)

grep -n "AD-462f" decisions-era-4-evolution.md
  2699: | AD-462f | DEFERRED — concept graphs, AnchorFrame sufficient for now |
  (Era-4 decisions table row; replace per Section 5.5)
```

---

## Builder Pre-Flight Checklist

1. `git status` — clean tree.
2. `git log --oneline -1` — confirm HEAD `a63aa3e` (Wave 72 archive commit).
3. `pytest tests/ -q -n 4 --dist=loadfile` — confirm baseline 11447 collected.
4. `grep -n "ORACLE_LOOKUP_DISPATCHED" src/probos/events.py` — confirm Section 0 anchor.
5. `grep -n "class RecallScore" src/probos/types.py` — confirm Section 1 anchor.
6. Apply Section 0, then Section 1, then Section 2.1–2.4, then Section 3.1–3.2, then Section 4. Run focused tests after each section per the dispatch workflow.
7. Final gate: `pytest tests/ -q -n 4 --dist=loadfile` — expect 11461 ± 2.
