# AD-690 v1 — Dream Step 10: Relationship Inference

**Status:** Ready for build (Wave 40)
**Dependencies:** AD-687 (Knowledge Edge Store, Wave 37 ✅), AD-689 (`EpisodicMemory.list_episodes`, Wave 39 ✅), AD-551 (Dream Step 7g, shipped)
**Phase:** Unified Knowledge Graph — Phase B (Intelligence)
**GH issue:** #384
**Estimated tests:** 12 (over 10-floor by 2)

---

## Architect Calls (read first)

These are decisions baked into the prompt. Do not relitigate them at build time.

### DLog #1 — Pipeline-step-number collision

The GH issue title says "Dream Step 10". Live `cognitive/dreaming.py` already has a Step 10 (`# Step 10: Notebook Quality Metrics (AD-555)` at line 1197). Renumbering AD-555 is invasive and risky.

**Decision:** Keep AD title and GH issue label as "Dream Step 10 — Relationship Inference" (Captain-facing name, roadmap, DECISIONS.md). In the pipeline, this AD installs as **`Step 7i`** between Step 7h (AD-572 episodic-procedural bridge, line ~1067) and Step 8 (AD-385/539 gap detection, line 1069). Function name is `_step_7i_relationship_inference`. Inline comment: `# Step 7i: Relationship Inference (AD-690 — "Dream Step 10" in spec; numbered 7i to avoid collision with existing Step 10 = AD-555)`.

This slot is semantically right: runs after procedure consolidation (7a–7h) so episode metadata is fresh, but before downstream metrics steps (8–15) consume it.

### DLog #2 — Episode source

Captain's spec mentioned `runtime.episodic.list_episodes(since=...)`. Verified at HEAD: `EpisodicMemory.list_episodes(*, limit: int | None = None) -> list[Episode]` (`episodic.py:1132`, AD-689). **There is no `since` parameter.**

**Decision:** Step 7i consumes the **already-in-scope `episodes` variable** that earlier dream-cycle steps (7g/7h/8/etc.) all read. This naturally captures "episodes considered in this cycle" without a new fetch and without API drift. No call to `list_episodes` from this step.

### DLog #3 — Rejection cache implementation

Two options weighed: (a) overload `KnowledgeRelationType.CLASSIFIED_AS` with a sentinel, (b) dedicated SQLite table.

**Decision:** Dedicated SQLite-backed `SQLiteRejectionCache` in a new module `src/probos/knowledge/rejection_cache.py`. Option (a) pollutes `knowledge_edges` with non-graph rows and confuses AD-688/AD-689 consumers. Option (b) is one tiny module mirroring `SQLiteKnowledgeEdgeStore` lifecycle (start/stop, schema bootstrap). Surface kept narrow: `was_rejected(...) -> bool` and `record_rejection(...) -> None`. Public attribute `runtime.rejection_cache`.

### DLog #4 — AGENT→AGENT relation whitelist

`KnowledgeRelationType` has 10 values. Most are not semantically valid for an AGENT→AGENT pair (e.g. `MEMBER_OF` is agent→department, `COMPETENT_IN` is agent→capability, `INFORMED_BY` is decision→decision).

**Decision:** v1 classifies AGENT→AGENT pairs only (`agent_ids` in episodes are the entity source). The LLM prompt presents a **whitelist of two relations**: `REPORTS_TO` and `DEPENDS_ON`, plus the option to return `null`. If the LLM returns any other relation, treat as a rejection (parse-failure tier; recorded in cache; counted as `relationship_pairs_rejected`). Future ADs widen the entity scope and relation set (AD-690b/c).

---

## Verified Against Codebase (HEAD `b402fee`, 2026-05-04)

```
grep -n "class KnowledgeEntityType" src/probos/knowledge/edges.py
  41:class KnowledgeEntityType(str, Enum):     # AGENT="agent" at :43
grep -n "class KnowledgeRelationType" src/probos/knowledge/edges.py
  54:class KnowledgeRelationType(str, Enum):   # REPORTS_TO/DEPENDS_ON among 10
grep -n "class KnowledgeEdge" src/probos/knowledge/edges.py
  73:class KnowledgeEdge:                      # 13 fields, frozen, __post_init__ bounds
grep -n "async def add_edge\|async def find_edges" src/probos/knowledge/edges.py
  139,150,240,348                              # Protocol + impl
grep -n "async def list_episodes" src/probos/cognitive/episodic.py
  1132: async def list_episodes(self, *, limit: int | None = None)
grep -n "class Episode" src/probos/types.py
  411: class Episode:                          # agent_ids: list[str] at :420
grep -n "class LLMRequest" src/probos/types.py
  227: class LLMRequest:                       # tier="standard" at :232
grep -n "class DreamingConfig" src/probos/config.py
  579: class DreamingConfig(BaseModel):        # last field at :632 (trace_exemplars_per_procedure)
grep -n "class DreamReport" src/probos/types.py
  474: class DreamReport:                      # last fields :550-552
grep -n "Step 7h\|# Step 8:" src/probos/cognitive/dreaming.py
  1044: # Step 7h: Cross-cycle episodic-procedural bridge (AD-572)
  1067: logger.warning("Step 7h episodic-procedural bridge failed...")
  1069: # Step 8: Enhanced capability gap detection (AD-385 + AD-539)
grep -n "self.knowledge_edges" src/probos/runtime.py
  428: self.knowledge_edges: Any = None        # public, adopted at :1615
  1615: self.knowledge_edges = comm.knowledge_edges
grep -n "_wire_chain_optimizer\|_wire_edge_backfill" src/probos/startup/finalize.py
  214: def _wire_chain_optimizer(*, runtime, config) -> bool
  239: async def _wire_edge_backfill(*, runtime, config) -> bool
  635/638/641: invocation site (sequential)
grep -n "DreamingEngine(" src/probos/startup/dreaming.py
  166: dreaming_engine = DreamingEngine(...)   # construction site; setters at :202+
grep -n "def set_records_store\|def set_confidence_tracker" src/probos/cognitive/dreaming.py
  145, 152                                     # setter pattern precedent
grep -n "extract_json" src/probos/utils/json_extract.py
  17: def extract_json(content: str) -> dict[str, Any]
```

---

## Problem

ProbOS has a typed knowledge-edge graph (AD-687, Wave 37) and an episodic memory whose episodes record the agents that participated (`Episode.agent_ids: list[str]`). Today, no dream step looks across recent episodes for **co-occurring agents that lack any edge in `knowledge_edges`** and tries to classify their relationship.

This is the relationship-inference surface from the unified-knowledge-graph research doc (`docs/research/unified-knowledge-graph.md`, Phase B). Without it the graph stays seeded only by structural backfill (AD-689) and never learns from observed co-participation.

The work must include hard anti-contamination: a per-entity edge cap, a rejection cache to avoid re-classifying the same pair every cycle, explicit source tagging, a min-confidence threshold, and a v1 relation whitelist.

---

## Solution Overview

1. **New module `src/probos/knowledge/rejection_cache.py`** — `RejectionCacheStorage` Protocol + `SQLiteRejectionCache` impl. Mirrors `SQLiteKnowledgeEdgeStore` lifecycle.
2. **New module `src/probos/cognitive/relationship_inference.py`** — pure service:
   - `RelationshipInferenceResult` frozen dataclass (counters)
   - `infer_relationships_from_episodes(...)` async function (LLM-driven classifier)
   - Helper: `_extract_agent_pairs(episodes)`, `_classify_pair_with_llm(...)`
3. **`DreamingConfig` extension** — 4 new flat fields (existing pattern; no sub-config).
4. **`DreamReport` extension** — 3 new counter fields.
5. **`DreamingEngine` extension** — 2 new setters (`set_knowledge_edges`, `set_rejection_cache`) + Step 7i block in `dream_cycle` between Step 7h and Step 8.
6. **`startup/finalize.py` wirer** — `_wire_relationship_inference` creates the cache, attaches both deps to `dreaming_engine` via setters, exposes `runtime.rejection_cache` public.
7. **`runtime.py`** — declare `self.rejection_cache: Any = None` next to `knowledge_edges`.
8. **Tests** — 12-test file `tests/test_ad690_relationship_inference.py`.

---

## Implementation

### Section 0: Property-collision check

Before draft, grep these names — none must collide with existing public attributes/methods:

- `runtime.rejection_cache` — collision-free (verified: no hits in `src/probos`).
- `DreamingEngine.set_knowledge_edges` / `set_rejection_cache` — collision-free.
- `DreamingEngine._knowledge_edges` / `_rejection_cache` — collision-free.
- `DreamReport.inferred_relationships` / `relationship_pairs_rejected` / `relationship_pairs_capped` — collision-free.
- `DreamingConfig.relationship_inference_enabled` etc. — collision-free.
- Module path `src/probos/cognitive/relationship_inference.py` — does not exist.
- Module path `src/probos/knowledge/rejection_cache.py` — does not exist.

Builder: re-grep at build time. If any collision, hard-stop and surface.

---

### Section 1: New module — `src/probos/knowledge/rejection_cache.py`

Create the file with this exact content shape:

```python
"""AD-690: Rejection cache for Dream Step 7i relationship inference.

Persists `(source_id, target_id, relation, reason, rejected_at)` rows so the
nightly dream cycle does not re-ask the LLM about the same agent pair every
run. Mirrors the SQLiteKnowledgeEdgeStore lifecycle (start/stop bootstrap).

Surface kept deliberately narrow: `was_rejected` for the read path,
`record_rejection` for the write path. No update or delete in v1 — entries
are append-only and persist for the life of the database.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol, runtime_checkable

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dream_step10_rejections (
    source_id  TEXT NOT NULL,
    target_id  TEXT NOT NULL,
    relation   TEXT,
    reason     TEXT,
    rejected_at REAL NOT NULL,
    PRIMARY KEY (source_id, target_id)
);
"""


@runtime_checkable
class RejectionCacheStorage(Protocol):
    """Public read+write surface used by AD-690 Step 7i."""

    async def was_rejected(self, source_id: str, target_id: str) -> bool: ...
    async def record_rejection(
        self,
        *,
        source_id: str,
        target_id: str,
        relation: str | None,
        reason: str,
    ) -> None: ...


class SQLiteRejectionCache:
    """Concrete SQLite-backed rejection cache.

    Lifecycle parallels SQLiteKnowledgeEdgeStore: pass a path; call ``start()``
    to bootstrap schema; call ``stop()`` on shutdown. ``was_rejected`` checks
    BOTH directions — `(a, b)` and `(b, a)` — since pairs are undirected at
    classification time.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        if self._db is not None:
            return
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def was_rejected(self, source_id: str, target_id: str) -> bool:
        if self._db is None:
            return False
        try:
            async with self._db.execute(
                "SELECT 1 FROM dream_step10_rejections "
                "WHERE (source_id = ? AND target_id = ?) "
                "   OR (source_id = ? AND target_id = ?) LIMIT 1",
                (source_id, target_id, target_id, source_id),
            ) as cur:
                row = await cur.fetchone()
            return row is not None
        except Exception:
            logger.debug("AD-690: rejection cache read failed", exc_info=True)
            return False

    async def record_rejection(
        self,
        *,
        source_id: str,
        target_id: str,
        relation: str | None,
        reason: str,
    ) -> None:
        if self._db is None:
            return
        try:
            await self._db.execute(
                "INSERT OR REPLACE INTO dream_step10_rejections "
                "(source_id, target_id, relation, reason, rejected_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (source_id, target_id, relation, reason, time.time()),
            )
            await self._db.commit()
        except Exception:
            logger.debug("AD-690: rejection cache write failed", exc_info=True)
```

Then export from `src/probos/knowledge/__init__.py` (add to existing names, do not remove):

```python
from probos.knowledge.rejection_cache import (
    RejectionCacheStorage,
    SQLiteRejectionCache,
)
```

(Use a SEARCH/REPLACE adjacent to the AD-687 export block. Anchor on the existing `from probos.knowledge.edges import (` import in that file.)

---

### Section 2: New module — `src/probos/cognitive/relationship_inference.py`

Create with this shape (~250 lines). Pure service: dependencies passed in, never reaches into `runtime`. The dream-step block calls this and assembles counters.

Key elements (full code follows):

- **`RelationshipInferenceResult`** frozen dataclass:
  - `candidate_pairs: int = 0`
  - `inferred_edges: int = 0`
  - `relationship_pairs_rejected: int = 0`
  - `relationship_pairs_capped: int = 0`
  - `to_dict() -> dict[str, int]`

- **Constants**:
  - `_AGENT_AGENT_RELATION_WHITELIST = (KnowledgeRelationType.REPORTS_TO, KnowledgeRelationType.DEPENDS_ON)`
  - `_LLM_PROMPT_TEMPLATE` (multi-line constant)
  - `_RESPONSE_MAX_TOKENS = 200`

- **`_extract_agent_pairs(episodes) -> list[tuple[str, str]]`**:
  Iterate `episodes`. Skip any with `< 2` agents in `agent_ids`. Build deduped pairs as sorted tuples (`(min, max)`) so `(a, b)` and `(b, a)` collapse. Return list with stable insertion order (use `dict.fromkeys`).

- **`_classify_pair_with_llm(agent_a, agent_b, *, llm_client) -> tuple[KnowledgeRelationType | None, float, str]`**:
  Build `LLMRequest(prompt=_LLM_PROMPT_TEMPLATE.format(a=agent_a, b=agent_b), tier="standard", temperature=0.0, max_tokens=_RESPONSE_MAX_TOKENS)`.
  Call `await llm_client.complete(req)`. Parse `resp.content` via `extract_json` (utils.json_extract:17).
  Expected JSON: `{"relation": "reports_to" | "depends_on" | null, "confidence": float, "rationale": str}`.
  - On parse failure: return `(None, 0.0, "llm_parse_failure")`.
  - On `relation == null`: return `(None, 0.0, "llm_returned_null")`.
  - On relation outside whitelist: return `(None, 0.0, "relation_not_in_whitelist")`.
  - On valid relation: return `(KnowledgeRelationType(relation), clamp(confidence, 0, 1), rationale)`.

- **`infer_relationships_from_episodes(...)`** async — main entry:
  ```python
  async def infer_relationships_from_episodes(
      *,
      episodes: list[Episode],
      knowledge_edges: KnowledgeEdgeStorage,
      llm_client: Any,
      rejection_cache: RejectionCacheStorage,
      max_pairs_per_run: int = 50,
      max_inferences_per_entity: int = 5,
      min_confidence: float = 0.6,
  ) -> RelationshipInferenceResult:
  ```
  Algorithm:
  1. Build pair list via `_extract_agent_pairs(episodes)`. Set `result.candidate_pairs = len(pairs)`.
  2. `per_entity_counter: dict[str, int] = {}`; `processed = 0`.
  3. For each `(a, b)` pair (in order):
     - If `processed >= max_pairs_per_run`: break.
     - If `await rejection_cache.was_rejected(a, b)`: continue silently (do NOT increment `relationship_pairs_rejected` — already counted on first run; this branch is the "skip-on-replay" path).
     - If `await knowledge_edges.find_edges(source_id=a, target_id=b, limit=1)` non-empty OR `find_edges(source_id=b, target_id=a, limit=1)` non-empty: continue (already linked).
     - If `per_entity_counter.get(a, 0) >= max_inferences_per_entity` or `per_entity_counter.get(b, 0) >= max_inferences_per_entity`: `result.relationship_pairs_capped += 1`; `processed += 1`; continue.
     - `relation, conf, rationale = await _classify_pair_with_llm(a, b, llm_client=llm_client)`.
     - `processed += 1`.
     - If `relation is None`:
       - `await rejection_cache.record_rejection(source_id=a, target_id=b, relation=None, reason=rationale)`.
       - `result.relationship_pairs_rejected += 1`.
       - continue.
     - If `conf < min_confidence`:
       - `await rejection_cache.record_rejection(source_id=a, target_id=b, relation=relation.value, reason=f"below_threshold_{conf:.2f}")`.
       - `result.relationship_pairs_rejected += 1`.
       - continue.
     - Build `KnowledgeEdge(source_type=AGENT, source_id=a, relation=relation, target_type=AGENT, target_id=b, confidence=conf, weight=0.5, source_agent="dream_step10", source_duty="relationship_inference")`.
     - Try `await knowledge_edges.add_edge(edge)`; on success increment `result.inferred_edges`, `per_entity_counter[a]+=1`, `per_entity_counter[b]+=1`. On exception (tier-2 log-and-degrade) `logger.warning("AD-690: add_edge failed for (%s,%s): %s", a, b, e)` and continue.
  4. Return `result`.

LLM prompt template (verbatim — tune is not in scope for v1):

```
You are classifying the working relationship between two ProbOS agents that
co-occurred in recent episodes. Choose ONE relation, or return null if no
clear relationship exists. Reply with ONLY a JSON object.

Allowed relations:
- "reports_to"  — A reports to B in the org chain of command.
- "depends_on"  — A's work depends on outputs/decisions from B.
- null          — no clear working relationship between A and B.

Agent A: {a}
Agent B: {b}

Respond with EXACTLY this JSON shape:
{{"relation": "<relation_or_null>", "confidence": <0.0-1.0>, "rationale": "<one sentence>"}}
```

(Note the doubled braces — this is a Python `str.format` template.)

---

### Section 3: Extend `DreamingConfig` (`src/probos/config.py`)

Use SEARCH/REPLACE — anchor on the AD-657 line `trace_exemplars_per_procedure: int = 3` (last field today, line 632).

```
SEARCH:
    # AD-657: Trace exemplars preserved per consolidated procedure (0 = disabled)
    trace_exemplars_per_procedure: int = 3


class DreamWMConfig(BaseModel):
REPLACE:
    # AD-657: Trace exemplars preserved per consolidated procedure (0 = disabled)
    trace_exemplars_per_procedure: int = 3
    # AD-690: Dream Step 7i — Relationship inference from co-occurring episode agents
    relationship_inference_enabled: bool = True
    relationship_inference_max_pairs_per_run: int = 50
    relationship_inference_max_per_entity: int = 5
    relationship_inference_min_confidence: float = 0.6


class DreamWMConfig(BaseModel):
END
```

**Default `enabled=True`** rationale (precedent: `notebook_consolidation_enabled` line 592, `KnowledgeEdgesConfig`, `EdgeBackfillConfig`): step is gated downstream on `knowledge_edges` and `rejection_cache` being non-None — both wired by `_wire_relationship_inference` which itself depends on `knowledge_edges` already being adopted at `runtime.py:1615`. Out-of-box behavior: enabled but inert until wirer runs and dependencies exist.

---

### Section 4: Extend `DreamReport` (`src/probos/types.py`)

SEARCH/REPLACE anchored on the last existing field (`wm_priming_entries: int = 0` at line 552).

```
SEARCH:
    # AD-671: Dream-Working Memory bridge
    wm_entries_flushed: int = 0
    bridged_procedures: int = 0  # AD-572: cross-cycle procedural bridge
    wm_priming_entries: int = 0


REPLACE:
    # AD-671: Dream-Working Memory bridge
    wm_entries_flushed: int = 0
    bridged_procedures: int = 0  # AD-572: cross-cycle procedural bridge
    wm_priming_entries: int = 0
    # AD-690: Dream Step 7i — Relationship inference (titled "Dream Step 10" in spec/issue)
    inferred_relationships: int = 0
    relationship_pairs_rejected: int = 0
    relationship_pairs_capped: int = 0


END
```

---

### Section 5: Extend `DreamingEngine` (`src/probos/cognitive/dreaming.py`)

Three edits. Apply via `multi_replace_string_in_file`.

**Edit 5a — new `__init__` field assignments.** Anchor on the existing `self._addressed_degradations` block at ~line 132 (last self-assignment in ctor). Append new private fields on a single `# AD-690` group:

```
SEARCH:
        self._reactive_cooldowns: dict[str, float] = {}  # AD-532e: agent_id -> last reactive check

    def set_ward_room(self, ward_room: Any) -> None:
REPLACE:
        self._reactive_cooldowns: dict[str, float] = {}  # AD-532e: agent_id -> last reactive check
        # AD-690: late-bound after finalize phase (knowledge_edges adopted at runtime.py:1615)
        self._knowledge_edges: Any = None
        self._rejection_cache: Any = None

    def set_ward_room(self, ward_room: Any) -> None:
END
```

**Edit 5b — new setters.** Anchor on the existing `set_quality_router` setter at line 164.

```
SEARCH:
    def set_quality_router(self, router: Any) -> None:
        """AD-565: Late-bind quality router."""
        self._quality_router = router
REPLACE:
    def set_quality_router(self, router: Any) -> None:
        """AD-565: Late-bind quality router."""
        self._quality_router = router

    def set_knowledge_edges(self, store: Any) -> None:
        """AD-690: Late-bind KnowledgeEdgeStore (adopted in finalize phase)."""
        self._knowledge_edges = store

    def set_rejection_cache(self, cache: Any) -> None:
        """AD-690: Late-bind SQLiteRejectionCache (adopted in finalize phase)."""
        self._rejection_cache = cache
END
```

**Edit 5c — Step 7i block.** Anchor on the Step 7h closing log + Step 8 header at lines 1067–1069. The `# Step 7i` block goes BETWEEN them. **Counters declared inside the block default to 0 so the DreamReport construction (~line 1522) can read them whether or not Step 7i ran.**

```
SEARCH:
            except Exception as e:
                logger.warning("Step 7h episodic-procedural bridge failed; continuing dream cycle: %s", e)

        # Step 8: Enhanced capability gap detection (AD-385 + AD-539)
REPLACE:
            except Exception as e:
                logger.warning("Step 7h episodic-procedural bridge failed; continuing dream cycle: %s", e)

        # Step 7i: Relationship Inference (AD-690 — titled "Dream Step 10" in spec
        # and GH issue #384; numbered 7i in the pipeline to avoid collision with
        # existing Step 10 = AD-555 Notebook Quality Metrics).
        inferred_relationships = 0
        relationship_pairs_rejected = 0
        relationship_pairs_capped = 0
        ri_cfg = getattr(self.config, "relationship_inference_enabled", False)
        if (
            ri_cfg
            and self._knowledge_edges is not None
            and self._rejection_cache is not None
            and self._llm_client is not None
            and episodes
        ):
            try:
                from probos.cognitive.relationship_inference import (
                    infer_relationships_from_episodes,
                )

                ri_result = await infer_relationships_from_episodes(
                    episodes=episodes,
                    knowledge_edges=self._knowledge_edges,
                    llm_client=self._llm_client,
                    rejection_cache=self._rejection_cache,
                    max_pairs_per_run=getattr(
                        self.config, "relationship_inference_max_pairs_per_run", 50,
                    ),
                    max_inferences_per_entity=getattr(
                        self.config, "relationship_inference_max_per_entity", 5,
                    ),
                    min_confidence=getattr(
                        self.config, "relationship_inference_min_confidence", 0.6,
                    ),
                )
                inferred_relationships = ri_result.inferred_edges
                relationship_pairs_rejected = ri_result.relationship_pairs_rejected
                relationship_pairs_capped = ri_result.relationship_pairs_capped
                logger.debug(
                    "Step 7i: candidates=%d inferred=%d rejected=%d capped=%d",
                    ri_result.candidate_pairs,
                    inferred_relationships,
                    relationship_pairs_rejected,
                    relationship_pairs_capped,
                )
            except Exception as e:
                logger.warning("Step 7i relationship inference failed; continuing dream cycle: %s", e)

        # Step 8: Enhanced capability gap detection (AD-385 + AD-539)
END
```

**Edit 5d — Plumb counters into DreamReport.** Anchor on the existing AD-572 line in the report assembly (line ~1535).

```
SEARCH:
            bridged_procedures=bridged_procedures,
            procedures_evolved=procedures_evolved,
REPLACE:
            bridged_procedures=bridged_procedures,
            # AD-690: Dream Step 7i — relationship inference
            inferred_relationships=inferred_relationships,
            relationship_pairs_rejected=relationship_pairs_rejected,
            relationship_pairs_capped=relationship_pairs_capped,
            procedures_evolved=procedures_evolved,
END
```

(There is also a partial `DreamReport(...)` construction at ~line 1499 inside an exception branch. Builder: leave that one alone — it's a degraded-path partial report that does NOT need the new fields. The defaults (`= 0`) cover it.)

---

### Section 6: New wirer in `src/probos/startup/finalize.py`

Two edits.

**Edit 6a — new wirer function.** Insert immediately AFTER `_wire_edge_backfill` (ends at line ~292) and BEFORE `_wire_causal_reasoner` (starts line 294). Anchor:

```
SEARCH:
def _wire_causal_reasoner(*, runtime: Any, config: "SystemConfig") -> bool:
REPLACE:
async def _wire_relationship_inference(
    *, runtime: Any, config: "SystemConfig"
) -> bool:
    """AD-690: Wire SQLiteRejectionCache and attach knowledge_edges +
    rejection_cache to DreamingEngine for Step 7i relationship inference.

    Skips silently if dreaming is disabled, knowledge_edges is unavailable,
    or relationship_inference_enabled is False.
    """
    dream_cfg = getattr(config, "dreaming", None)
    if not dream_cfg or not getattr(dream_cfg, "relationship_inference_enabled", False):
        return False

    knowledge_edges = getattr(runtime, "knowledge_edges", None)
    if knowledge_edges is None:
        logger.debug(
            "AD-690: relationship inference enabled but knowledge_edges not "
            "wired; skipping (depends on AD-687)."
        )
        return False

    dreaming_engine = getattr(runtime, "dreaming_engine", None)
    if dreaming_engine is None:
        logger.debug(
            "AD-690: relationship inference enabled but dreaming_engine not "
            "wired; skipping."
        )
        return False

    from probos.knowledge.rejection_cache import SQLiteRejectionCache
    from pathlib import Path

    data_dir = getattr(config, "data_dir", "data")
    db_path = str(Path(data_dir) / "rejection_cache.sqlite")
    cache = SQLiteRejectionCache(db_path)
    try:
        await cache.start()
    except Exception as exc:
        logger.warning(
            "AD-690: rejection cache failed to start at %s: %s; "
            "Step 7i will be skipped",
            db_path,
            exc,
        )
        return False

    runtime.rejection_cache = cache

    if hasattr(dreaming_engine, "set_knowledge_edges"):
        dreaming_engine.set_knowledge_edges(knowledge_edges)
    if hasattr(dreaming_engine, "set_rejection_cache"):
        dreaming_engine.set_rejection_cache(cache)
    return True


def _wire_causal_reasoner(*, runtime: Any, config: "SystemConfig") -> bool:
END
```

**Edit 6b — invocation site.** Insert in the wirer-cascade between the `_wire_edge_backfill` call (line 638) and `_wire_causal_reasoner` (line 641):

```
SEARCH:
    if await _wire_edge_backfill(runtime=runtime, config=config):
        logger.info("AD-689: EdgeBackfillService v1 wired during finalization")

    if _wire_causal_reasoner(runtime=runtime, config=config):
REPLACE:
    if await _wire_edge_backfill(runtime=runtime, config=config):
        logger.info("AD-689: EdgeBackfillService v1 wired during finalization")

    if await _wire_relationship_inference(runtime=runtime, config=config):
        logger.info("AD-690: Dream Step 7i relationship inference v1 wired during finalization")

    if _wire_causal_reasoner(runtime=runtime, config=config):
END
```

---

### Section 7: Declare `runtime.rejection_cache` (`src/probos/runtime.py`)

SEARCH/REPLACE anchored on the AD-687 `knowledge_edges` declaration at line 428.

```
SEARCH:
        self.knowledge_edges: Any = None  # SQLiteKnowledgeEdgeStore | None — Any to avoid circular import
REPLACE:
        self.knowledge_edges: Any = None  # SQLiteKnowledgeEdgeStore | None — Any to avoid circular import
        self.rejection_cache: Any = None  # AD-690: SQLiteRejectionCache | None — Any to avoid circular import
END
```

---

### Section 8: Tests — `tests/test_ad690_relationship_inference.py`

Create a new test file. Use `tmp_path` for the rejection cache DB. Use stub LLM clients that return fixed JSON strings. Use a stub `KnowledgeEdgeStorage` (in-memory) — do NOT spin up `SQLiteKnowledgeEdgeStore` for unit tests that only need the Protocol surface (faster + isolation).

**12 tests planned:**

1. `test_relationship_inference_result_shape` — frozen, defaults to 0/0/0/0, `to_dict` round-trips.
2. `test_extract_agent_pairs_dedupes_and_skips_singletons` — episodes with `agent_ids=["a","b"]`, `["b","a"]` (collapses), `["c"]` (skipped), `["x","y","z"]` (3 pairs) → expected pair set.
3. `test_existing_edge_skip_no_llm_call` — stub edges store returns one `KnowledgeEdge` for `(a,b)`; LLM stub records call count; assert no LLM call, no inference.
4. `test_llm_happy_path_adds_edge_with_tags` — LLM returns `{"relation":"reports_to","confidence":0.85,"rationale":"..."}` → edge added to store with `confidence=0.85`, `weight=0.5`, `source_agent="dream_step10"`, `source_duty="relationship_inference"`, `relation=REPORTS_TO`. `result.inferred_edges == 1`.
5. `test_min_confidence_filter_records_rejection` — LLM returns `{"relation":"reports_to","confidence":0.4,"rationale":"..."}`; `min_confidence=0.6` → no edge added; rejection cache has the entry; `result.relationship_pairs_rejected == 1`.
6. `test_per_entity_cap_honored` — synthetic episodes that pair `agent_a` with 10 distinct partners; `max_inferences_per_entity=5`; LLM returns valid relation each time. `result.inferred_edges == 5`; `result.relationship_pairs_capped == 5`.
7. `test_max_pairs_per_run_honored` — 50 candidate pairs available; `max_pairs_per_run=10`; LLM returns valid relation each time → exactly 10 LLM calls and 10 edges.
8. `test_rejection_cache_prevents_reclassification` — first run records a rejection for `(a,b)`. Second run with the same pair → `was_rejected` returns True → LLM not called for that pair; inferred/rejected counters do not increment for that pair on the second run.
9. `test_llm_json_parse_failure_counts_as_rejection` — LLM returns malformed `"not json"`; pair is recorded as rejected with `reason="llm_parse_failure"`; no edge added.
10. `test_relation_outside_whitelist_counts_as_rejection` — LLM returns `{"relation":"member_of",...}` (not in whitelist); pair rejected with `reason="relation_not_in_whitelist"`; no edge added.
11. `test_disabled_config_short_circuits_step` — exercise the dream-engine block via a real `DreamingEngine` instance with `config.relationship_inference_enabled=False`; LLM stub call count is 0; counters stay 0.
12. `test_sqlite_rejection_cache_round_trip` — concrete `SQLiteRejectionCache` with `tmp_path / "x.db"`. `start()` → `record_rejection(...)` → `was_rejected(a,b)` is True; `was_rejected(b,a)` is True (undirected); `was_rejected(c,d)` is False; `stop()`.

Each test is independent and uses fresh `tmp_path` fixtures. No shared mutable state.

---

## What This Does NOT Change

- No new EventType. (Telemetry is via `DreamReport` counters and `logger.debug`. EventType deferred to AD-690b if signal value emerges.)
- No HXI surface. (Counters are visible via existing dream-report channels only.)
- No backfill or migration of existing knowledge_edges (AD-689 owns backfill).
- No federation sync (AD-693).
- No classification gating (`KnowledgeEdge.classification` left at default `None` for inferred edges; AD-692 commercial owns ORACLE/SECRET labeling).
- No new entity types. v1 classifies AGENT→AGENT pairs only. Episode `agent_ids` are the entity source; episode metadata fields are NOT scanned.
- No widening of relation whitelist beyond `REPORTS_TO` and `DEPENDS_ON`. (AD-690b/c may widen.)
- No retry on `add_edge` failure. (Tier-2 log-and-degrade; failed pairs are not added to rejection cache so they retry next cycle.)
- No scheduling change. (Existing `DreamScheduler` already invokes `dream_cycle`; Step 7i runs whenever the cycle runs.)
- No LLM tier escalation. v1 is `tier="standard"` only.

---

## Tracking

After build:

- **PROGRESS.md** — prepend a v1 entry under Era V at the top of the AD list mirroring AD-689's format (one paragraph, summarize what shipped + test count delta + closes #384).
- **docs/development/roadmap.md** — flip AD-690 status from "Scoped" (or whatever current label is) to "Complete (v1)".
- **DECISIONS.md** — no entry required for v1 unless an architectural call is made beyond the four documented above. (DLogs #1–#4 are already captured in this prompt and the dispatch.)

---

## Acceptance Criteria

- All 12 new tests pass: `pytest tests/test_ad690_relationship_inference.py -v -n 0`.
- Full gate non-decreasing: `pytest tests/ -q -n 8 --dist=loadfile`. Expect baseline `11015` → ≥ `11025` (+10–12; one may absorb into the known `test_dreaming::test_nl_to_dream_cycle_changes_weights` xdist flake documented in Wave 39 build notes).
- All `KnowledgeEdge` instances created by Step 7i carry `source_agent="dream_step10"`, `source_duty="relationship_inference"`, `weight=0.5`, `confidence` from the LLM clamped into `[0, 1]`.
- `SQLiteRejectionCache.was_rejected` is undirected (verified by Test 12).
- `DreamingEngine.dream_cycle` returns a `DreamReport` whose new counters round-trip (asserted in Test 11 with config disabled — they MUST still be present at `0`).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Phantom-API Pre-Check

Run before commit:

```
./scripts/phantom-api-precheck.ps1 -PromptPath prompts/ad-690-dream-step10-relationship-inference-v1.md
```

Expected: 0 NEW phantoms. Same FP class as Waves 27/36/37/38/39 (intra-prompt-introduced symbols, e.g. `RelationshipInferenceResult`, `SQLiteRejectionCache`, `runtime.rejection_cache`, `infer_relationships_from_episodes`).

If the script flags a real phantom, hard-stop and surface to architect.
