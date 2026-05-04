# AD-688 v1 — Oracle Graph Integration (Tier 6 + Post-Merge Expansion)

**Status:** Pending Builder
**Issue:** #382 (closes on merge)
**Predecessor:** AD-687 v1 (Wave 37, commit `def4f37`) — `KnowledgeEdgeStorage` Protocol + `SQLiteKnowledgeEdgeStore` + `runtime.knowledge_edges`
**Sibling reference:** AD-686 v1 (Wave 36, commit `48db252`) — Tier 5 / `attach_semantic_layer` mirror for late-bind setter
**Wave-plan slot:** id `"38"` (already populated, status `pending`)
**Verified at HEAD:** `ef34c85` (post-Wave-37)
**Test-count baseline:** 10990 → expected 11000–11002 (+10–11; one test may be absorbed by `test_knowledge_store::test_auto_commit_after_debounce` known xdist flake — see Wave 37 build notes).

---

## v1 Scope (one paragraph)

Make the **Knowledge Edge Store searchable through the Oracle**. Adds **Tier 6 (`graph`)** to `OracleService.query()` and a **post-merge `_expand_via_graph` enrichment pass** that 1-hop-expands the top-K merged results from all tiers via the knowledge graph. New constructor kwarg `knowledge_graph: KnowledgeEdgeStorage | None = None` (kwargs-only, default `None`); new public idempotent `attach_knowledge_graph(graph)` late-bind setter mirroring AD-686's `attach_semantic_layer`. Wires `runtime.oracle.attach_knowledge_graph(runtime.knowledge_edges)` immediately after `comm.knowledge_edges` is adopted at `runtime.py:1612`. Adds `"graph"` to the default `active_tiers` list. Provenance tags use the existing `OracleResult.provenance` field (NOT metadata): `[knowledge graph]` for Tier 6 hits, `[graph expansion: <parent_provenance>]` for post-merge expansions; the original tier's tag is preserved in `metadata["expansion_source"]`. Captain's "complete v1" standing convention applies — Tier 6 + post-merge expansion + wiring + provenance + tier-list update all ship together.

## Phase Context

Phase A (Foundation) of the **Unified Knowledge Graph + Oracle Unification** stack. AD-688 is the **third of four** Phase-A ADs:
AD-686 ✅ (Wave 36, Tier 5) → AD-687 ✅ (Wave 37, Edge Store) → **AD-688 (this) Oracle ↔ Graph stitching** → AD-689 (#383, edge backfill) → AD-690 (#384, Dream Step 10).

After AD-688 lands, the graph is **queryable** but still **empty in production**. AD-689 backfills it from existing data (Hebbian/ontology/episodes). AD-690 grows it through Dream-Step-10 inference. AD-688 closes the **read seam**.

---

## Verify-First Findings (HEAD `ef34c85`)

| Symbol | Location | Used in v1 |
|---|---|---|
| `OracleService.__init__` (kwargs-only, 9 deps) | `cognitive/oracle_service.py:50–69` | YES — add 10th kwarg `knowledge_graph: Any = None` after `semantic_layer` |
| `attach_semantic_layer(layer)` setter | `cognitive/oracle_service.py:72–79` | YES — mirror exactly as `attach_knowledge_graph(graph)` |
| `query()` async dispatcher | `cognitive/oracle_service.py:81–173` | YES — extend `active_tiers` default + append Tier 6 dispatch + post-merge expansion |
| Default `active_tiers` list | `cognitive/oracle_service.py:102` (`["episodic", "records", "operational", "archive", "semantic"]`) | YES — append `"graph"` (6 tiers total) |
| Tier dispatch pattern (5× `if self._X and "name" in active_tiers:` blocks) | `cognitive/oracle_service.py:107–167` | Mirrored — Tier 6 block goes immediately after Tier 5 (semantic) at line 167 |
| Result merge + sort + truncate | `cognitive/oracle_service.py:170–172` (sort by score desc, slice `[:k_per_tier * len(active_tiers)]`) | YES — `_expand_via_graph` runs BEFORE sort/truncate so its results compete in the merge ranking |
| `_query_semantic(query_text, *, k, types=None)` mirror | `cognitive/oracle_service.py:343–378` | YES — `_query_graph(query_text, *, k)` mirrors shape (no `types` kwarg) |
| `OracleResult` frozen dc | `cognitive/oracle_service.py:22–30` (5 fields: `source_tier`, `content`, `score`, `metadata: dict[str, Any]`, `provenance: str`) | **`provenance` is its own field, NOT a metadata key.** Captain's spec phrasing was loose — graph results populate the `provenance` field; `metadata["expansion_source"]` records the parent tier's provenance for post-merge results |
| `KnowledgeEdgeStorage` Protocol | `knowledge/edges.py:130–167` (`find_edges`, `traverse` async signatures) | YES — Tier 6 dispatch declares `knowledge_graph: KnowledgeEdgeStorage \| None` for type narrowing |
| `KnowledgeEdge` frozen dc fields | `knowledge/edges.py:73–96` (`source_type`, `source_id`, `relation`, `target_type`, `target_id`, `id`, `confidence`, `weight`, …) | YES — Tier 6 reads `weight`, `confidence`, `source_type`, `source_id`, `target_type`, `target_id`, `relation`, `id` |
| `runtime.knowledge_edges` slot | `runtime.py:428` (`Any = None` placeholder), adopted at `runtime.py:1612` from `comm.knowledge_edges` | YES — late-bind to Oracle immediately after adoption |
| `runtime.oracle` public alias | `runtime.py:1327` (`self.oracle = cog.oracle_service`) | YES — same instance as `_oracle_service`; both point at one `OracleService` |
| `runtime._oracle_service.attach_semantic_layer(...)` precedent | `runtime.py:1531–1535` | Mirrored — wrap `attach_knowledge_graph` in `try/except Exception: logger.warning(...)` |
| Phase ordering: cognitive (Oracle) before structural-services (semantic) before communication (knowledge_edges) | `runtime.py:1326`, `1531`, `1612` | Late-bind setter at line 1614+ is safe — Oracle exists ≥285 lines earlier |

**Phase ordering note (architect call).** `runtime.knowledge_edges` is set at `runtime.py:1612` inside the **Phase 7 (Communication)** block, AFTER `runtime.oracle` (Phase 5/Cognitive) and AFTER the AD-686 `attach_semantic_layer` block (Phase 6/Structural). The new `attach_knowledge_graph` call belongs **immediately after line 1612** so both attached references are stable by the time agents start consuming the runtime.

---

## Decision Log (architect calls)

1. **`OracleResult.provenance` is a dedicated field, NOT a metadata key.** Captain's spec said `metadata: "[knowledge graph]"` — but the live dataclass has `provenance: str` separately. Tier 6 hits set `provenance="[knowledge graph]"`. Expansion results set `provenance="[graph expansion: <parent_provenance>]"`. Parent tier's original provenance string is mirrored into `metadata["expansion_source"]` for downstream consumers that want to filter/group by origin tier without parsing the formatted string. **Builder must NOT relocate provenance into metadata** — that would break `query_formatted()` at line 199 which reads `r.provenance` directly.

2. **Entity extraction strategy: token-substring match against `entity_id`.** v1 is **NOT** named-entity recognition. Strategy:
   - Lowercase + `split()` the query into tokens.
   - Drop tokens of length < 3 and tokens in a small inline `_STOPWORDS` frozenset (~30 common words; documented in module).
   - For each surviving token, call **both** `find_edges(source_id=token, limit=k)` and `find_edges(target_id=token, limit=k)` — these are exact `entity_id` matches (the v1 store does `WHERE source_id = ?`, not `LIKE`). This is acceptable because backfill (AD-689) uses normalized lowercase ids; v1 graph users (and tests) construct edges with lowercase ids matching token shape.
   - Document explicitly in module docstring: **"v1 entity match is exact-id-equals-token; AD-691 will add NL-to-graph extraction with embedding-based fuzzy matching."**

3. **Hop-proximity scoring: 1.0 for direct, 0.6 for 2-hop.** Direct = edge returned by `find_edges` (token matched the edge's source_id or target_id directly). 2-hop = edge returned by `traverse(source_type=match.target_type, source_id=match.target_id, max_hops=1)` — i.e., one extra edge starting from the direct-match's target. v1 caps at 2-hop total (1 direct + 1 traversal hop). Score = `edge.weight * edge.confidence * hop_proximity`. **Hard caps inline (NOT config):** `_GRAPH_DIRECT_LIMIT = 10` per token, `_GRAPH_TRAVERSE_LIMIT = 5` per direct match. Externalize only if AD-688b adoption signals demand it.

4. **Dedupe by `edge.id` across both `source_id`/`target_id` directions and across direct/traverse merges.** A single edge can match a token by source_id AND target_id (e.g., self-loop) or appear as direct-match for one token AND 2-hop for another. Use a `seen: set[str]` keyed on `edge.id`. Keep the **highest-scoring** instance (max of competing hop_proximity).

5. **Empty graph or unattached graph → `[]` with `logger.debug`.** Mirrors the AD-686 Tier-5 unattached behavior at `oracle_service.py:357`. NEVER raises into `query()`.

6. **`_expand_via_graph(merged_results, *, top_k=5)` runs BEFORE the merge sort.** Order in `query()`:
   1. Run all 6 tiers (including new Tier 6).
   2. Run `_expand_via_graph(all_results, top_k=5)` → returns 0..N additional `OracleResult`s.
   3. `extend()` expansion results into `all_results`.
   4. Sort by score desc.
   5. Truncate to `k_per_tier * len(active_tiers)` (now 6 tiers → larger window absorbs expansion results).
   This makes expansion results **compete on score** in the final ranking.

7. **Expansion uses the SAME token-extraction helper as Tier 6.** `_extract_entity_tokens(text)` is module-private and reused. Top-K parents → for each, extract tokens from `parent.content`, dedupe across parents, do `find_edges(source_id=token, limit=10)` ONLY (no traverse — expansion is 1-hop by design per Captain's spec). Expansion-result score = `parent.score * 0.7 * edge.weight * edge.confidence`. The 0.7× discount expresses "1 step removed from a high-scoring tier hit". Provenance = `f"[graph expansion: {parent.provenance}]"`. Metadata carries `{"expansion_source": parent.provenance, "expansion_parent_tier": parent.source_tier, "edge_id": edge.id, "relation": edge.relation.value, ...}`.

8. **Expansion respects `top_k` AND a `_GRAPH_EXPANSION_PER_PARENT = 5` per-parent cap.** Without the per-parent cap a single parent with many neighbors could swamp the merge.

9. **Default `active_tiers` becomes 6 entries.** Order: `["episodic", "records", "operational", "archive", "semantic", "graph"]`. Existing callers that pass an explicit `tiers=` list keep their narrowed behavior. Adding `"graph"` to the default list is the v1 opt-in: zero callers need to change, but the tier is live everywhere.

10. **NO new EventType, NO new Pydantic config, NO new module.** All edits land in `cognitive/oracle_service.py` and `runtime.py`. The graph store already has its own config (`KnowledgeEdgesConfig` from AD-687); whether the graph tier is "enabled" is implicit in `runtime.knowledge_edges is not None`.

11. **NO change to `OracleService.__init__` for `knowledge_graph` — just append the 10th kwarg.** Maintains backward compat with all existing test fixtures that call `OracleService(episodic_memory=...)` with arbitrary subsets of kwargs.

---

## What This Does NOT Change (legitimate scope boundaries — separate GitHub issues)

| Out of scope | Tracked under |
|---|---|
| NL-to-graph query (LLM extracts entity refs from natural-language query before tier dispatch) | AD-691 (#385, future) |
| Edge population from existing data (Hebbian / ontology / episodes / records) | AD-689 (#383) |
| Dream Step 10 relationship inference (LLM-driven edge creation during dream cycle) | AD-690 (#384) |
| Classification enforcement on graph reads (filter by `private/department/ship/fleet` per requester) | AD-692 (#386, commercial) |
| Federation cross-instance edge sync | AD-693 (#387, commercial) |
| HXI graph visualization | AD-690b or later |
| Shell command (`/graph search`, `/graph traverse`) | once consumers exist |
| Graph metrics in `oracle.stats()` (Oracle has no stats surface today; would require AD-688b) | deferred |

These are **separate-issue scope**, not v1 deferrals.

---

## Section 0 — Naming-collision check

```pwsh
Select-String -Path src/probos -Pattern "_query_graph|_expand_via_graph|attach_knowledge_graph|_extract_entity_tokens|_GRAPH_DIRECT_LIMIT|_GRAPH_TRAVERSE_LIMIT|_GRAPH_EXPANSION_PER_PARENT|_STOPWORDS" -SimpleMatch | Select-Object -First 20
```

Expected: 0 hits in `src/probos`. (`_STOPWORDS` may collide if any future module adds one — verify no `_STOPWORDS` in `cognitive/oracle_service.py` or its dependencies at build time. If a collision surfaces, rename to `_GRAPH_STOPWORDS`.)

---

## Section 1 — Constructor + late-bind setter

**File:** `src/probos/cognitive/oracle_service.py`

### 1a. Add `knowledge_graph` kwarg to `__init__`

SEARCH (around line 50–67):

```python
    def __init__(
        self,
        *,
        episodic_memory: Any = None,
        records_store: Any = None,
        knowledge_store: Any = None,
        archive_store: Any = None,  # AD-524
        trust_network: Any = None,
        hebbian_router: Any = None,
        expertise_directory: Any = None,
        semantic_layer: Any = None,  # AD-686 (Tier 5)
    ) -> None:
        self._episodic_memory = episodic_memory
        self._records_store = records_store
        self._knowledge_store = knowledge_store
        self._archive_store = archive_store
        self._trust_network = trust_network
        self._hebbian_router = hebbian_router
        self._expertise_directory = expertise_directory
        self._semantic_layer = semantic_layer  # AD-686 (Tier 5)
```

REPLACE with:

```python
    def __init__(
        self,
        *,
        episodic_memory: Any = None,
        records_store: Any = None,
        knowledge_store: Any = None,
        archive_store: Any = None,  # AD-524
        trust_network: Any = None,
        hebbian_router: Any = None,
        expertise_directory: Any = None,
        semantic_layer: Any = None,  # AD-686 (Tier 5)
        knowledge_graph: Any = None,  # AD-688 (Tier 6)
    ) -> None:
        self._episodic_memory = episodic_memory
        self._records_store = records_store
        self._knowledge_store = knowledge_store
        self._archive_store = archive_store
        self._trust_network = trust_network
        self._hebbian_router = hebbian_router
        self._expertise_directory = expertise_directory
        self._semantic_layer = semantic_layer  # AD-686 (Tier 5)
        self._knowledge_graph = knowledge_graph  # AD-688 (Tier 6)
```

### 1b. Add `attach_knowledge_graph` setter immediately after `attach_semantic_layer`

SEARCH (around line 72–79):

```python
    def attach_semantic_layer(self, semantic_layer: Any) -> None:
        """AD-686: Late-bind the SemanticKnowledgeLayer.

        Used by the runtime because `SemanticKnowledgeLayer` is constructed
        in the structural-services phase (after the cognitive phase that
        builds `OracleService`). Idempotent — last write wins.
        """
        self._semantic_layer = semantic_layer
```

REPLACE with:

```python
    def attach_semantic_layer(self, semantic_layer: Any) -> None:
        """AD-686: Late-bind the SemanticKnowledgeLayer.

        Used by the runtime because `SemanticKnowledgeLayer` is constructed
        in the structural-services phase (after the cognitive phase that
        builds `OracleService`). Idempotent — last write wins.
        """
        self._semantic_layer = semantic_layer

    def attach_knowledge_graph(self, knowledge_graph: Any) -> None:
        """AD-688: Late-bind the KnowledgeEdgeStorage.

        Used by the runtime because `SQLiteKnowledgeEdgeStore` is constructed
        in the communication phase (after the cognitive phase that builds
        `OracleService`). Idempotent — last write wins. Mirrors
        `attach_semantic_layer` shape exactly.
        """
        self._knowledge_graph = knowledge_graph
```

---

## Section 2 — Module-level constants + helpers

**File:** `src/probos/cognitive/oracle_service.py`

### 2a. Add constants and stopword set immediately above the `_format_age` helper

SEARCH (around line 32–34):

```python
def _format_age(timestamp: float) -> str:
    """Format a timestamp as a human-readable age string."""
    delta = time.time() - timestamp
```

REPLACE with:

```python
# AD-688: Tier 6 (graph) tunables — inline caps, NOT config (escalate to
# config only if v1 adoption signals justify it).
_GRAPH_DIRECT_LIMIT = 10        # find_edges(limit=…) per direction per token
_GRAPH_TRAVERSE_LIMIT = 5       # 2-hop edges per direct match
_GRAPH_EXPANSION_PER_PARENT = 5 # 1-hop neighbors per top-K parent
_GRAPH_HOP_PROXIMITY_DIRECT = 1.0
_GRAPH_HOP_PROXIMITY_TWO_HOP = 0.6
_GRAPH_EXPANSION_DISCOUNT = 0.7  # parent_score × this × edge.weight × edge.confidence
_GRAPH_MIN_TOKEN_LEN = 3

# Small inline stopword set — keeps _extract_entity_tokens self-contained
# (no nltk / no external corpus). Lowercase only.
_GRAPH_STOPWORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "day", "get", "has", "him", "his",
    "how", "man", "new", "now", "old", "see", "two", "way", "who", "boy",
    "did", "its", "let", "put", "say", "she", "too", "use", "what", "with",
    "from", "this", "that", "they", "have", "been", "were", "their", "would",
    "there", "could", "about", "into",
})


def _extract_entity_tokens(text: str) -> list[str]:
    """AD-688: Heuristic token extractor for v1 graph entity matching.

    Strategy: lowercase + split-on-whitespace, drop tokens shorter than
    `_GRAPH_MIN_TOKEN_LEN`, drop stopwords, dedupe preserving order.
    Returns at most 16 tokens (v1 ceiling — keeps per-query graph load
    bounded). Strips trailing punctuation `.,!?;:` from each token before
    filtering.

    NOT named-entity recognition. AD-691 will add NL-to-graph with
    embedding-based fuzzy matching; v1 deliberately stays simple so the
    Oracle integration can be exercised end-to-end with predictable inputs.
    """
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in text.lower().split():
        token = raw.strip(".,!?;:'\"()[]{}")
        if len(token) < _GRAPH_MIN_TOKEN_LEN:
            continue
        if token in _GRAPH_STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= 16:
            break
    return out


def _format_age(timestamp: float) -> str:
    """Format a timestamp as a human-readable age string."""
    delta = time.time() - timestamp
```

---

## Section 3 — Wire Tier 6 into `query()` dispatcher

**File:** `src/probos/cognitive/oracle_service.py`

### 3a. Extend default `active_tiers` list

SEARCH (around line 102):

```python
        active_tiers = tiers or ["episodic", "records", "operational", "archive", "semantic"]
        all_results: list[OracleResult] = []
```

REPLACE with:

```python
        active_tiers = tiers or [
            "episodic", "records", "operational", "archive", "semantic", "graph",
        ]
        all_results: list[OracleResult] = []
```

### 3b. Append Tier 6 dispatch block after Tier 5

SEARCH (around line 161–172):

```python
        # Tier 5: Semantic Knowledge Layer (AD-686) — non-episode ChromaDB collections
        if "semantic" in active_tiers:
            try:
                tier_results = await self._query_semantic(query_text, k=k_per_tier)
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 5 (semantic) query failed", exc_info=True)

        # Merge & sort by score descending
        all_results.sort(key=lambda r: r.score, reverse=True)
        max_results = k_per_tier * len(active_tiers)
        return all_results[:max_results]
```

REPLACE with:

```python
        # Tier 5: Semantic Knowledge Layer (AD-686) — non-episode ChromaDB collections
        if "semantic" in active_tiers:
            try:
                tier_results = await self._query_semantic(query_text, k=k_per_tier)
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 5 (semantic) query failed", exc_info=True)

        # Tier 6: Knowledge Graph (AD-688) — typed-triple traversal
        if "graph" in active_tiers:
            try:
                tier_results = await self._query_graph(query_text, k=k_per_tier)
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 6 (graph) query failed", exc_info=True)

        # AD-688: Post-merge graph expansion — 1-hop enrichment of top-K
        # results from all tiers. Runs BEFORE the final sort/truncate so
        # expansion results compete on score in the merged ranking.
        try:
            expansion_results = await self._expand_via_graph(all_results, top_k=5)
            all_results.extend(expansion_results)
        except Exception:
            logger.debug("Oracle: graph expansion failed", exc_info=True)

        # Merge & sort by score descending
        all_results.sort(key=lambda r: r.score, reverse=True)
        max_results = k_per_tier * len(active_tiers)
        return all_results[:max_results]
```

---

## Section 4 — `_query_graph` private tier method

**File:** `src/probos/cognitive/oracle_service.py`

Append immediately AFTER the `_query_semantic` method (which ends near line 378 with `return results`). Insertion point: after the closing `return results` of `_query_semantic`, before the next class member or end-of-class.

```python
    async def _query_graph(
        self,
        query_text: str,
        *,
        k: int,
    ) -> list[OracleResult]:
        """AD-688: Query KnowledgeEdgeStorage (Tier 6).

        Extracts candidate entity tokens from the query (v1: token-substring
        match, see ``_extract_entity_tokens``), looks up direct edges via
        ``find_edges(source_id=token)`` and ``find_edges(target_id=token)``
        (1-hop, hop_proximity=1.0), and traverses one extra hop from each
        direct match (2-hop, hop_proximity=0.6). Edges are deduped by
        ``edge.id`` keeping the highest-scoring instance.

        Score = edge.weight × edge.confidence × hop_proximity.

        When the graph is not attached (test/legacy bootstrap), returns
        ``[]`` and logs at debug — mirrors the AD-686 Tier-5 unattached
        path.
        """
        graph = self._knowledge_graph
        if graph is None:
            logger.debug("Oracle: Tier 6 (graph) — no graph attached; returning []")
            return []

        tokens = _extract_entity_tokens(query_text)
        if not tokens:
            return []

        # edge.id -> (best_score, edge, hop_proximity, source_token, source_dir)
        scored: dict[str, tuple[float, Any, float, str, str]] = {}

        for token in tokens:
            # Direct: source_id matches
            try:
                src_hits = await graph.find_edges(
                    source_id=token, limit=_GRAPH_DIRECT_LIMIT,
                )
            except Exception:
                logger.debug("Oracle Tier 6: find_edges(source_id=%r) failed", token, exc_info=True)
                src_hits = []
            for edge in src_hits:
                _record_graph_hit(scored, edge, _GRAPH_HOP_PROXIMITY_DIRECT, token, "source")

            # Direct: target_id matches
            try:
                tgt_hits = await graph.find_edges(
                    target_id=token, limit=_GRAPH_DIRECT_LIMIT,
                )
            except Exception:
                logger.debug("Oracle Tier 6: find_edges(target_id=%r) failed", token, exc_info=True)
                tgt_hits = []
            for edge in tgt_hits:
                _record_graph_hit(scored, edge, _GRAPH_HOP_PROXIMITY_DIRECT, token, "target")

            # 2-hop: traverse one extra step from each direct match's target
            for edge in (*src_hits, *tgt_hits):
                try:
                    paths = await graph.traverse(
                        source_type=edge.target_type,
                        source_id=edge.target_id,
                        max_hops=1,
                    )
                except Exception:
                    logger.debug(
                        "Oracle Tier 6: traverse(source_id=%r) failed",
                        edge.target_id, exc_info=True,
                    )
                    continue
                for path in paths[:_GRAPH_TRAVERSE_LIMIT]:
                    for hop_edge in path:
                        if hop_edge.id == edge.id:
                            continue  # don't double-count the seed edge
                        _record_graph_hit(
                            scored, hop_edge,
                            _GRAPH_HOP_PROXIMITY_TWO_HOP, token, "traverse",
                        )

        if not scored:
            return []

        results: list[OracleResult] = []
        for edge_id, (score, edge, hop_prox, source_token, source_dir) in scored.items():
            content = (
                f"{edge.source_type.value}:{edge.source_id} "
                f"--[{edge.relation.value}]--> "
                f"{edge.target_type.value}:{edge.target_id}"
            )
            results.append(OracleResult(
                source_tier="graph",
                content=content,
                score=score,
                metadata={
                    "edge_id": edge_id,
                    "relation": edge.relation.value,
                    "source_type": edge.source_type.value,
                    "source_id": edge.source_id,
                    "target_type": edge.target_type.value,
                    "target_id": edge.target_id,
                    "weight": edge.weight,
                    "confidence": edge.confidence,
                    "hop_proximity": hop_prox,
                    "matched_token": source_token,
                    "matched_direction": source_dir,
                },
                provenance="[knowledge graph]",
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:k]

    async def _expand_via_graph(
        self,
        merged_results: list[OracleResult],
        *,
        top_k: int = 5,
    ) -> list[OracleResult]:
        """AD-688: 1-hop graph enrichment on the top-K merged tier results.

        For each parent in the top-K (by score), extracts candidate tokens
        from ``parent.content`` via ``_extract_entity_tokens``, fetches up to
        ``_GRAPH_EXPANSION_PER_PARENT`` neighbor edges via
        ``find_edges(source_id=token)``, and emits an OracleResult per
        neighbor with::

            score = parent.score
                  × _GRAPH_EXPANSION_DISCOUNT
                  × edge.weight
                  × edge.confidence
            provenance = f"[graph expansion: {parent.provenance}]"
            metadata["expansion_source"] = parent.provenance
            metadata["expansion_parent_tier"] = parent.source_tier

        Skips parents whose ``source_tier == "graph"`` (already a graph hit;
        re-expanding would inflate). Returns ``[]`` when graph is not
        attached, top_k <= 0, or no candidate tokens are produced.
        """
        graph = self._knowledge_graph
        if graph is None or top_k <= 0 or not merged_results:
            return []

        # Defensive copy + sort so callers don't have to pre-sort
        ordered = sorted(merged_results, key=lambda r: r.score, reverse=True)
        parents = [p for p in ordered if p.source_tier != "graph"][:top_k]
        if not parents:
            return []

        seen_edges: set[str] = set()
        expansion: list[OracleResult] = []

        for parent in parents:
            tokens = _extract_entity_tokens(parent.content)
            if not tokens:
                continue
            per_parent_emitted = 0
            for token in tokens:
                if per_parent_emitted >= _GRAPH_EXPANSION_PER_PARENT:
                    break
                try:
                    edges = await graph.find_edges(
                        source_id=token, limit=_GRAPH_EXPANSION_PER_PARENT,
                    )
                except Exception:
                    logger.debug(
                        "Oracle expansion: find_edges(source_id=%r) failed",
                        token, exc_info=True,
                    )
                    continue
                for edge in edges:
                    if per_parent_emitted >= _GRAPH_EXPANSION_PER_PARENT:
                        break
                    if edge.id in seen_edges:
                        continue
                    seen_edges.add(edge.id)
                    score = (
                        parent.score
                        * _GRAPH_EXPANSION_DISCOUNT
                        * edge.weight
                        * edge.confidence
                    )
                    content = (
                        f"{edge.source_type.value}:{edge.source_id} "
                        f"--[{edge.relation.value}]--> "
                        f"{edge.target_type.value}:{edge.target_id}"
                    )
                    expansion.append(OracleResult(
                        source_tier="graph",
                        content=content,
                        score=score,
                        metadata={
                            "edge_id": edge.id,
                            "relation": edge.relation.value,
                            "source_type": edge.source_type.value,
                            "source_id": edge.source_id,
                            "target_type": edge.target_type.value,
                            "target_id": edge.target_id,
                            "weight": edge.weight,
                            "confidence": edge.confidence,
                            "expansion_source": parent.provenance,
                            "expansion_parent_tier": parent.source_tier,
                            "matched_token": token,
                        },
                        provenance=f"[graph expansion: {parent.provenance}]",
                    ))
                    per_parent_emitted += 1
        return expansion
```

Also append the `_record_graph_hit` module-level helper near the other module-level helpers (immediately after `_extract_entity_tokens`):

```python
def _record_graph_hit(
    scored: dict[str, tuple[float, Any, float, str, str]],
    edge: Any,
    hop_proximity: float,
    source_token: str,
    source_dir: str,
) -> None:
    """AD-688: Insert-or-replace a graph hit by edge.id, keeping the
    highest-scoring instance. Score = weight × confidence × hop_proximity.
    """
    score = float(edge.weight) * float(edge.confidence) * hop_proximity
    existing = scored.get(edge.id)
    if existing is None or score > existing[0]:
        scored[edge.id] = (score, edge, hop_proximity, source_token, source_dir)
```

---

## Section 5 — Runtime late-bind wiring

**File:** `src/probos/runtime.py`

SEARCH (around line 1610–1614):

```python
        self.cognitive_journal = comm.cognitive_journal
        self.knowledge_edges = comm.knowledge_edges  # AD-687
        self.skill_registry = comm.skill_registry
```

REPLACE with:

```python
        self.cognitive_journal = comm.cognitive_journal
        self.knowledge_edges = comm.knowledge_edges  # AD-687
        # AD-688: Stitch Tier 6 onto Oracle now that the knowledge graph exists.
        if self._oracle_service is not None and self.knowledge_edges is not None:
            try:
                self._oracle_service.attach_knowledge_graph(self.knowledge_edges)
            except Exception:
                logger.warning(
                    "AD-688: failed to attach knowledge graph to OracleService; "
                    "Tier 6 graph queries will return [] until restart",
                    exc_info=True,
                )
        self.skill_registry = comm.skill_registry
```

---

## Section 6 — Tests

**File:** `tests/test_ad688_oracle_graph_integration.py` (new).

Use the existing AD-687 store as a real backing fixture (NOT mocked) for happy-path tests; use a stub `KnowledgeEdgeStorage` Protocol-compatible class for behavioral tests where edge behavior must be controlled. Reuse the live `OracleService` for end-to-end.

### Test plan (11 tests, exceeds 10-floor by 1)

1. **`test_attach_knowledge_graph_late_binds`** — `OracleService()` constructed without graph; `attach_knowledge_graph(stub)` swaps in. Idempotent: second call replaces.
2. **`test_query_graph_method_shape`** — `_query_graph` is async, returns `list[OracleResult]`, accepts `(query_text, *, k)`.
3. **`test_query_graph_unattached_returns_empty`** — graph is `None` → `[]` (no exception, debug log).
4. **`test_query_graph_one_hop_direct_match_source`** — token matches edge source_id; returns 1 OracleResult with `source_tier="graph"`, provenance `"[knowledge graph]"`, score = weight × confidence × 1.0.
5. **`test_query_graph_one_hop_direct_match_target`** — token matches edge target_id (separate edge); returned with same hop_proximity=1.0.
6. **`test_query_graph_two_hop_with_proximity_discount`** — chain A→B→C; query token=`a`; A→B returned at hop_proximity 1.0, B→C at 0.6. Verify B→C score = weight × confidence × 0.6.
7. **`test_query_graph_dedupe_keeps_highest_score`** — single edge X→Y where token "x" matches source AND token "y" matches target; result list contains exactly one entry for that edge.
8. **`test_default_active_tiers_includes_graph`** — `OracleService.query("test")` with all 6 tiers attached invokes `_query_graph` (assert via spy/mock on `_query_graph`).
9. **`test_expand_via_graph_happy_path`** — 5 synthetic top-K parents (semantic/episodic/etc.); each parent's content contains a token that matches a `find_edges(source_id=token)` hit; expansion produces N results with provenance prefix `"[graph expansion: "` and score = parent.score × 0.7 × edge.weight × edge.confidence.
10. **`test_expand_via_graph_skips_graph_parents`** — top-K includes a Tier 6 graph result; that one is NOT re-expanded (no double-counting).
11. **`test_expand_via_graph_respects_top_k_and_per_parent_cap`** — 10 parents but `top_k=3`; each parent has 20 candidate edges in the graph; expansion emits at most `3 × _GRAPH_EXPANSION_PER_PARENT = 15` results; metadata records `expansion_parent_tier` correctly.
12. **`test_runtime_attaches_knowledge_graph_to_oracle`** — minimal runtime-shape integration test using stubs: assert that after the wiring block runs, `runtime._oracle_service._knowledge_graph is runtime.knowledge_edges` (smoke test only — full runtime boot not required; mock `_oracle_service` + `knowledge_edges` slots on a `SimpleNamespace` and re-execute the attach try/except).

If a test must drop due to drift: drop test #5 (target_id symmetry — test #4's source_id path is the more common production case) or #11 (per-parent cap — the floor of 10 is preserved if either of these is dropped).

### Stopword + token helper tests (2 tests, modulo merge into above)

Optionally fold these into a single `test_extract_entity_tokens_*` parametrize:
- Drops short tokens (<3 chars).
- Drops stopwords.
- Strips trailing punctuation.
- Dedupes preserving order.
- Caps at 16 tokens.

If folded as parametrize, count remains 11 distinct test functions.

---

## Section 7 — Phantom-API Pre-Check

```pwsh
./scripts/phantom-api-precheck.ps1 prompts/ad-688-oracle-graph-integration-v1.md
```

**Expected:** small number of FPs only — `_query_graph`, `_expand_via_graph`, `attach_knowledge_graph`, `_extract_entity_tokens`, `_record_graph_hit`, `_GRAPH_*` constants are all introduced by Sections 1–4 of this prompt. `KnowledgeEdgeStorage` Protocol + `KnowledgeEdge` dataclass + `find_edges` + `traverse` all exist at HEAD `ef34c85` (AD-687 verified table above).

**Builder action:** if any phantom surfaces beyond the introduced-in-prompt list, document in build report; do NOT fix without architect review.

---

## Standing Conventions (required acknowledgement)

- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
- **Cloud-Ready Storage:** consumes `KnowledgeEdgeStorage` Protocol from AD-687 — NOT `SQLiteKnowledgeEdgeStore` directly. Type narrowing in code uses `Any` to avoid the import cycle (knowledge ↔ cognitive); the Protocol contract is documented in the methods' docstrings instead.
- **Property collision (Wave 32 retrospective).** `OracleService` is NOT a `CognitiveAgent` subclass; no `@property` shadowing risk. `runtime.knowledge_edges` already lives at the runtime (AD-687 Wave 37) — no new public attribute on runtime; `runtime.oracle` already lives there from AD-686. **No new `runtime.X` slot in this AD.**
- **`OracleResult.provenance` is a top-level field, NOT a metadata key** (Decision Log #1).
- **Ship complete v1** (Captain's standing convention, banked 2026-05-04): Tier 6 + post-merge expansion + runtime wiring + provenance + tier-list update all ship together. NO sub-deferral within AD-688's spec.
- **No new EventType, no new Pydantic config, no new module.** All edits in `cognitive/oracle_service.py` + `runtime.py` + new test file.

---

## Acceptance Criteria

1. ✅ All Sections 1–5 applied with no SEARCH/REPLACE drift.
2. ✅ Test file `tests/test_ad688_oracle_graph_integration.py` exists with ≥10 passing tests.
3. ✅ Full gate at ≥11000 (10990 baseline + ≥10 net new).
4. ✅ Phantom-API pre-check shows only intro-not-yet-in-index FPs (documented).
5. ✅ Existing AD-686 tests (`test_ad686_*` if any, plus the runtime wiring test for `attach_semantic_layer`) still pass — Tier 5 path unchanged.
6. ✅ Existing `OracleService` callers (`introspect/`, `organizer_agents.py`, `cmd_search`) not modified — they pass `tiers=["semantic"]` or rely on defaults; defaults grow but remain backward-compatible.
7. ✅ PROGRESS.md prepended with AD-688 v1 entry. roadmap.md status flipped Scoped → Complete. DECISIONS.md prepended at top of Era V.
8. ✅ Single commit per Captain ask: `"Wave 38: AD-688 v1 Oracle graph integration (Tier 6 + post-merge expansion)"`. Pushed to origin/main.
9. ✅ Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (HEAD `ef34c85`, 2026-05-04)

```
grep -n "OracleService" src/probos/cognitive/oracle_service.py
   43: class OracleService:
   50:     def __init__(

grep -n "attach_semantic_layer" src/probos/cognitive/oracle_service.py
   72:     def attach_semantic_layer(self, semantic_layer: Any) -> None:

grep -n "active_tiers = tiers or" src/probos/cognitive/oracle_service.py
  102:        active_tiers = tiers or ["episodic", "records", "operational", "archive", "semantic"]

grep -n "_query_semantic" src/probos/cognitive/oracle_service.py
  164:                tier_results = await self._query_semantic(query_text, k=k_per_tier)
  343:    async def _query_semantic(

grep -n "OracleResult" src/probos/cognitive/oracle_service.py
   23: class OracleResult:
   29:     provenance: str  # Human-readable provenance tag

grep -n "class KnowledgeEdgeStorage" src/probos/knowledge/edges.py
  131: class KnowledgeEdgeStorage(Protocol):

grep -n "async def find_edges\|async def traverse" src/probos/knowledge/edges.py
  150:     async def find_edges(
  160:     async def traverse(
  348:     async def find_edges(
  392:     async def traverse(

grep -n "knowledge_edges" src/probos/runtime.py
  428:        self.knowledge_edges: Any = None  # SQLiteKnowledgeEdgeStore | None
 1612:        self.knowledge_edges = comm.knowledge_edges  # AD-687

grep -n "oracle_service\|self\.oracle" src/probos/runtime.py
 1326:        self._oracle_service = cog.oracle_service  # AD-462e
 1327:        self.oracle = cog.oracle_service  # AD-686 (public alias; same instance)
 1531:        if self._oracle_service is not None and semantic_layer is not None:
 1533:                self._oracle_service.attach_semantic_layer(semantic_layer)
```

Every concrete claim in Sections 1–5 maps to one of these grep hits. `_query_graph`, `_expand_via_graph`, `attach_knowledge_graph`, `_extract_entity_tokens`, `_record_graph_hit`, `_GRAPH_*` constants, and `_GRAPH_STOPWORDS` are all introduced by this prompt — expected to be 0 hits before build.

---

**End of AD-688 v1 prompt.**
