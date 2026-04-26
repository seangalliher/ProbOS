# AD-603: Anchor Recall Composite Scoring

**Issue:** AD-603
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-570 (Anchor-Indexed Recall — complete), AD-567b (Salience-Weighted Recall — complete), AD-584c (Scoring Rebalance — complete)
**Files:** `src/probos/cognitive/episodic.py` (EDIT), `src/probos/cognitive/cognitive_agent.py` (EDIT), `tests/test_ad603_anchor_recall_composite_scoring.py` (NEW)

## Problem

`recall_by_anchor()` returns raw `list[Episode]` objects (episodic.py:1940–2120). These episodes bypass the entire composite scoring pipeline (`score_recall()` at episodic.py:1693–1773) — they have no semantic similarity, keyword hits, trust weight, hebbian weight, recency, convergence bonus, or temporal match scores.

Meanwhile, `recall_weighted()` (episodic.py:1775–1936) produces fully scored `list[RecallScore]` results with composite scores from all seven signals.

The merge step in `cognitive_agent.py:4469–4493` combines these two result sets. Anchor episodes (`_anchor_episodes`) are raw `list[Episode]`. Semantic episodes (`episodes`) are extracted from scored `list[RecallScore]` via `[rs.episode for rs in scored_results]` (cognitive_agent.py:4461). The merge is position-based — anchor results go first, semantic results append — with no quality-aware interleaving. This means:

1. Low-quality anchor matches outrank high-quality semantic matches by position alone.
2. There is no mechanism to drop irrelevant anchor results below a quality threshold.
3. The two populations are ranked by fundamentally different criteria (structure vs. salience).

**What this delivers:** Anchor-recalled episodes get full composite scoring via `score_recall()`, and the merge step uses composite scores for unified ranking instead of positional ordering. Anchor results get a small "structural match bonus" (they matched a deliberate structured query) but must compete on quality.

**What this does NOT include:**
- Changing `recall_by_anchor()` return type (it stays `list[Episode]` for callers outside the cognitive pipeline)
- Modifying anchor metadata storage or ChromaDB filtering
- Any changes to `score_recall()` weights or formula (AD-584c owns those)
- Changes to `_try_anchor_recall()` parsing logic (AD-570c owns that)

---

## Section 1: Add `recall_by_anchor_scored()` to EpisodicMemory

**File:** `src/probos/cognitive/episodic.py` (EDIT)

Add a new method after `recall_by_anchor()` (after line 2120). This method wraps `recall_by_anchor()` and scores each result through the same `score_recall()` pipeline that `recall_weighted()` uses.

```python
    async def recall_by_anchor_scored(
        self,
        *,
        agent_id: str = "",
        department: str = "",
        channel: str = "",
        trigger_type: str = "",
        trigger_agent: str = "",
        watch_section: str = "",
        participants: list[str] | None = None,
        time_range: tuple[float, float] | None = None,
        semantic_query: str = "",
        limit: int = 50,
        trust_network: Any = None,
        hebbian_router: Any = None,
        intent_type: str = "",
        weights: dict[str, float] | None = None,
        convergence_bonus: float = 0.10,
        query_watch_section: str = "",
        temporal_match_weight: float = 0.10,
        temporal_mismatch_penalty: float = 0.15,
        anchor_bonus: float = 0.08,
    ) -> list[RecallScore]:
        """AD-603: Anchor recall with full composite scoring.

        Delegates to recall_by_anchor() for structured retrieval, then scores
        each result through score_recall() with trust, hebbian, recency,
        keyword, and anchor confidence signals — the same pipeline as
        recall_weighted().

        Anchor results receive an anchor_bonus (default 0.08) on top of their
        composite score. This reflects the fact that they matched a deliberate
        structured query, not just semantic similarity. The bonus is modest
        enough that a high-quality semantic result can still outrank a
        low-quality anchor result.

        Parameters match recall_by_anchor() for the retrieval phase, plus
        the scoring parameters from recall_weighted().

        Returns list[RecallScore] sorted by composite_score descending.
        """
        # 1. Retrieve raw episodes via existing recall_by_anchor
        raw_episodes = await self.recall_by_anchor(
            department=department,
            channel=channel,
            trigger_type=trigger_type,
            trigger_agent=trigger_agent,
            watch_section=watch_section,
            agent_id=agent_id,
            participants=participants,
            time_range=time_range,
            semantic_query=semantic_query,
            limit=limit,
        )

        if not raw_episodes:
            return []

        # 2. Compute semantic similarity for each episode against semantic_query
        #    If no semantic_query provided, use a baseline similarity of 0.0
        #    (anchor results matched structurally, not semantically)
        ep_similarities: dict[str, float] = {}
        if semantic_query and self._collection:
            try:
                count = self._collection.count()
                if count > 0:
                    # Query ChromaDB for similarity scores for these specific episodes
                    # Use query() to get distances, then map by episode ID
                    from probos.knowledge.embeddings import reformulate_query
                    query_variants = reformulate_query(semantic_query) if self._query_reformulation_enabled else [semantic_query]
                    n_results = min(limit * 3, count)
                    result = self._collection.query(
                        query_texts=query_variants,
                        n_results=n_results,
                        include=["distances"],
                    )
                    if result and result.get("ids"):
                        for q_idx in range(len(result["ids"])):
                            for i, doc_id in enumerate(result["ids"][q_idx]):
                                distance = result["distances"][q_idx][i] if result.get("distances") else 0.0
                                sim = 1.0 - distance
                                if doc_id not in ep_similarities or sim > ep_similarities[doc_id]:
                                    ep_similarities[doc_id] = sim
            except Exception:
                logger.debug("AD-603: Semantic similarity lookup for anchor episodes failed", exc_info=True)

        # 3. Gather keyword hits
        keyword_map: dict[str, int] = {}
        if semantic_query:
            try:
                kw_results = await self.keyword_search(semantic_query, k=limit * 3)
                for ep_id, _rank in kw_results:
                    keyword_map[ep_id] = keyword_map.get(ep_id, 0) + 1
            except Exception:
                logger.debug("AD-603: Keyword search for anchor episodes failed", exc_info=True)

        # 4. Score each episode through the composite pipeline
        now = time.time()
        results: list[RecallScore] = []
        for ep in raw_episodes:
            # Semantic similarity (0.0 if not found — structural match only)
            sim = ep_similarities.get(ep.id, 0.0)

            # Trust weight
            tw = 0.5
            if trust_network is not None and agent_id:
                try:
                    tw = trust_network.get_score(agent_id)
                except Exception:
                    tw = 0.5

            # Hebbian weight
            hw = 0.5
            if hebbian_router is not None and intent_type:
                try:
                    hw = hebbian_router.get_weight(intent_type, agent_id, rel_type="intent")
                except Exception:
                    hw = 0.5

            # Recency weight: exp(-age_hours / 168)
            age_hours = (now - ep.timestamp) / 3600.0 if ep.timestamp > 0 else 168.0 * 4
            rw = math.exp(-age_hours / 168.0)

            kw_hits = keyword_map.get(ep.id, 0)

            # Temporal match check
            _temporal_match = bool(
                query_watch_section
                and getattr(ep, "anchors", None)
                and getattr(ep.anchors, "watch_section", "") == query_watch_section
            )

            rs = self.score_recall(
                episode=ep,
                semantic_similarity=sim,
                keyword_hits=kw_hits,
                trust_weight=tw,
                hebbian_weight=hw,
                recency_weight=rw,
                weights=weights,
                convergence_bonus=convergence_bonus,
                temporal_match=_temporal_match,
                temporal_match_weight=temporal_match_weight,
                temporal_mismatch_penalty=temporal_mismatch_penalty,
                query_has_temporal_intent=bool(query_watch_section),
                importance=ep.importance,
                importance_weight=0.05,
            )

            # AD-603: Apply anchor bonus — structural match signal
            boosted_score = rs.composite_score + max(0.0, anchor_bonus)
            rs = RecallScore(
                episode=rs.episode,
                semantic_similarity=rs.semantic_similarity,
                keyword_hits=rs.keyword_hits,
                trust_weight=rs.trust_weight,
                hebbian_weight=rs.hebbian_weight,
                recency_weight=rs.recency_weight,
                anchor_confidence=rs.anchor_confidence,
                composite_score=boosted_score,
            )
            results.append(rs)

        # 5. Sort by composite score descending
        results.sort(key=lambda r: r.composite_score, reverse=True)

        return results
```

**Key design decisions:**

1. **Separate method, not modifying `recall_by_anchor()`**: Other callers (dream consolidation, guided reminiscence, retrieval practice) use `recall_by_anchor()` for bulk enumeration and don't need scoring overhead. The original method stays unchanged.

2. **Semantic similarity computed via ChromaDB query**: If `semantic_query` is provided, we query ChromaDB for distance scores and map them by episode ID. If not, similarity is 0.0 — the anchor matched structurally, not semantically.

3. **Anchor bonus (0.08)**: Modest additive bonus. The default composite formula sums to roughly 0.35+0.20+0.10+0.05+0.15+0.15 = 1.0 at maximum. An 0.08 bonus is ~8% — enough to break ties in favor of anchor matches but not enough to rescue a low-quality result.

4. **Reuses the same trust/hebbian/recency/temporal scoring path** as `recall_weighted()` lines 1839–1886. The scoring code is intentionally duplicated (not extracted to a helper) because `recall_weighted()` iterates over `ep_map` entries while this iterates over `raw_episodes`. Extracting a shared helper would require a refactoring AD. The logic is simple enough that the duplication is acceptable per DRY judgment.

---

## Section 2: Update Merge Step in cognitive_agent.py

**File:** `src/probos/cognitive/cognitive_agent.py` (EDIT)

### 2a: Update `_try_anchor_recall()` to return scored results

Replace the `_try_anchor_recall` method (cognitive_agent.py:4655–4702) to call `recall_by_anchor_scored()` instead of `recall_by_anchor()` when the scoring dependencies are available.

Replace the method body starting at `try: results = await em.recall_by_anchor(` (line 4682) through `return (results if isinstance(results, list) and results else None), anchor.watch_section or ""` (line 4702):

**Find** (the try block and return at the end of `_try_anchor_recall`):
```python
        try:
            results = await em.recall_by_anchor(
                department=anchor.department,
                trigger_agent=anchor.trigger_agent,
                participants=anchor.participants if anchor.participants else None,
                time_range=anchor.time_range,
                watch_section=anchor.watch_section,  # BF-134
                semantic_query=anchor.semantic_query,
                agent_id=agent_mem_id,
                limit=10,
            )
        except Exception:
            logger.debug("AD-570c: recall_by_anchor failed", exc_info=True)
            return None, anchor.watch_section or ""

        if isinstance(results, list) and results:
            logger.debug(
                "AD-570c: Anchor recall returned %d episodes (dept=%s, agent=%s, watch=%s)",
                len(results), anchor.department, anchor.trigger_agent, anchor.watch_section,
            )
        return (results if isinstance(results, list) and results else None), anchor.watch_section or ""
```

**Replace with:**
```python
        # AD-603: Use scored anchor recall when available
        trust_net = getattr(self._runtime, 'trust_network', None)
        heb_router = getattr(self._runtime, 'hebbian_router', None)
        mem_cfg = None
        if hasattr(self._runtime, 'config') and hasattr(self._runtime.config, 'memory'):
            mem_cfg = self._runtime.config.memory

        if hasattr(em, 'recall_by_anchor_scored'):
            try:
                scored_results = await em.recall_by_anchor_scored(
                    department=anchor.department,
                    trigger_agent=anchor.trigger_agent,
                    participants=anchor.participants if anchor.participants else None,
                    time_range=anchor.time_range,
                    watch_section=anchor.watch_section,
                    semantic_query=anchor.semantic_query,
                    agent_id=agent_mem_id,
                    limit=10,
                    trust_network=trust_net,
                    hebbian_router=heb_router,
                    intent_type="",  # Not available at this point
                    weights=getattr(mem_cfg, 'recall_weights', None) if mem_cfg else None,
                    query_watch_section=anchor.watch_section or "",
                    temporal_match_weight=getattr(mem_cfg, 'recall_temporal_match_weight', 0.25) if mem_cfg else 0.25,
                    temporal_mismatch_penalty=getattr(mem_cfg, 'recall_temporal_mismatch_penalty', 0.15) if mem_cfg else 0.15,
                )
            except Exception:
                logger.debug("AD-603: recall_by_anchor_scored failed, falling back to unscored", exc_info=True)
                scored_results = None

            if scored_results:
                logger.debug(
                    "AD-603: Scored anchor recall returned %d results (dept=%s, agent=%s, watch=%s)",
                    len(scored_results), anchor.department, anchor.trigger_agent, anchor.watch_section,
                )
                return scored_results, anchor.watch_section or ""

        # Fallback: unscored recall_by_anchor (pre-AD-603 path)
        try:
            results = await em.recall_by_anchor(
                department=anchor.department,
                trigger_agent=anchor.trigger_agent,
                participants=anchor.participants if anchor.participants else None,
                time_range=anchor.time_range,
                watch_section=anchor.watch_section,
                semantic_query=anchor.semantic_query,
                agent_id=agent_mem_id,
                limit=10,
            )
        except Exception:
            logger.debug("AD-570c: recall_by_anchor failed", exc_info=True)
            return None, anchor.watch_section or ""

        if isinstance(results, list) and results:
            logger.debug(
                "AD-570c: Anchor recall returned %d episodes (dept=%s, agent=%s, watch=%s)",
                len(results), anchor.department, anchor.trigger_agent, anchor.watch_section,
            )
        return (results if isinstance(results, list) and results else None), anchor.watch_section or ""
```

**Note:** The return type of `_try_anchor_recall` changes from `tuple[list | None, str]` to `tuple[list[RecallScore] | list[Episode] | None, str]`. Update the type annotation:

**Find:**
```python
    async def _try_anchor_recall(
        self, query: str, agent_mem_id: str
    ) -> tuple[list | None, str]:
```

**Replace with:**
```python
    async def _try_anchor_recall(
        self, query: str, agent_mem_id: str
    ) -> tuple[list | None, str]:  # list[RecallScore] | list[Episode] | None
```

### 2b: Update the merge step to handle scored anchor results

Replace the merge step at cognitive_agent.py:4469–4493. The new merge must handle two cases:
1. `_anchor_episodes` is `list[RecallScore]` (AD-603 path) — merge by composite score
2. `_anchor_episodes` is `list[Episode]` (fallback path) — legacy position-based merge

**Find:**
```python
                # AD-570c: Merge anchor recall with semantic recall
                if _anchor_episodes:
                    _seen_ids = {getattr(ep, 'id', id(ep)) for ep in _anchor_episodes}
                    for ep in episodes:
                        if getattr(ep, 'id', id(ep)) in _seen_ids:
                            continue
                        # BF-155: Exclude semantic episodes whose watch_section contradicts
                        # the query's temporal intent. Without this filter, wrong-watch
                        # episodes contaminate the anchor-filtered recall set.
                        if (
                            _query_watch_section
                            and getattr(ep, "anchors", None)
                            and getattr(ep.anchors, "watch_section", "")
                            and ep.anchors.watch_section != _query_watch_section
                        ):
                            logger.debug(
                                "BF-155: Excluding episode %s (watch=%s) — query watch=%s",
                                getattr(ep, 'id', '?')[:8],
                                ep.anchors.watch_section,
                                _query_watch_section,
                            )
                            continue
                        _anchor_episodes.append(ep)
                        _seen_ids.add(getattr(ep, 'id', id(ep)))
                    episodes = _anchor_episodes
```

**Replace with:**
```python
                # AD-603: Merge anchor recall with semantic recall (score-aware)
                if _anchor_episodes:
                    from probos.types import RecallScore as _RecallScore
                    _is_scored = bool(_anchor_episodes and isinstance(_anchor_episodes[0], _RecallScore))

                    if _is_scored and scored_results:
                        # AD-603: Both populations are scored — merge by composite score
                        _seen_ids: set[str] = {rs.episode.id for rs in _anchor_episodes}
                        _merged: list[_RecallScore] = list(_anchor_episodes)

                        for rs in scored_results:
                            if rs.episode.id in _seen_ids:
                                continue
                            # BF-155: Exclude semantic episodes whose watch_section contradicts
                            if (
                                _query_watch_section
                                and getattr(rs.episode, "anchors", None)
                                and getattr(rs.episode.anchors, "watch_section", "")
                                and rs.episode.anchors.watch_section != _query_watch_section
                            ):
                                logger.debug(
                                    "BF-155: Excluding episode %s (watch=%s) — query watch=%s",
                                    rs.episode.id[:8],
                                    rs.episode.anchors.watch_section,
                                    _query_watch_section,
                                )
                                continue
                            _merged.append(rs)
                            _seen_ids.add(rs.episode.id)

                        # Sort unified list by composite score descending
                        _merged.sort(key=lambda r: r.composite_score, reverse=True)
                        scored_results = _merged
                        episodes = [rs.episode for rs in scored_results]
                    else:
                        # Fallback: legacy position-based merge (unscored anchor results)
                        _seen_ids = {getattr(ep, 'id', id(ep)) for ep in _anchor_episodes}
                        for ep in episodes:
                            if getattr(ep, 'id', id(ep)) in _seen_ids:
                                continue
                            # BF-155: Exclude semantic episodes whose watch_section contradicts
                            if (
                                _query_watch_section
                                and getattr(ep, "anchors", None)
                                and getattr(ep.anchors, "watch_section", "")
                                and ep.anchors.watch_section != _query_watch_section
                            ):
                                logger.debug(
                                    "BF-155: Excluding episode %s (watch=%s) — query watch=%s",
                                    getattr(ep, 'id', '?')[:8],
                                    ep.anchors.watch_section,
                                    _query_watch_section,
                                )
                                continue
                            _anchor_episodes.append(ep)
                            _seen_ids.add(getattr(ep, 'id', id(ep)))
                        episodes = _anchor_episodes
```

---

## Section 3: Tests

**File:** `tests/test_ad603_anchor_recall_composite_scoring.py` (NEW)

### Test infrastructure

Create a minimal in-memory `EpisodicMemory` setup using ChromaDB ephemeral client. Create helper episodes with anchor frames for structured filtering.

Use `unittest.mock.AsyncMock` / `MagicMock` for trust_network and hebbian_router. Import `RecallScore`, `Episode`, `AnchorFrame` from `probos.types`.

Helper to build test episodes:
```python
def _make_episode(
    ep_id: str,
    user_input: str = "test input",
    agent_ids: list[str] | None = None,
    timestamp: float = 0.0,
    department: str = "",
    channel: str = "",
    trigger_agent: str = "",
    watch_section: str = "",
    importance: int = 5,
) -> Episode:
    anchors = AnchorFrame(
        department=department,
        channel=channel,
        trigger_agent=trigger_agent,
        watch_section=watch_section,
    ) if any([department, channel, trigger_agent, watch_section]) else None
    return Episode(
        id=ep_id,
        timestamp=timestamp or time.time(),
        user_input=user_input,
        dag_summary={},
        outcomes=[],
        agent_ids=agent_ids or ["agent_1"],
        duration_ms=100.0,
        anchors=anchors,
        importance=importance,
    )
```

### Test categories (18 tests):

**`recall_by_anchor_scored()` — scoring pipeline (8 tests):**

1. `test_scored_returns_recall_score_objects` — results are `list[RecallScore]`, not `list[Episode]`
2. `test_scored_includes_composite_score` — each result has `composite_score > 0` (at minimum the anchor bonus + anchor_confidence)
3. `test_scored_sorted_by_composite_descending` — results are sorted by `composite_score` descending
4. `test_scored_applies_anchor_bonus` — composite score includes the anchor_bonus (0.08 default). Create two episodes with identical content; verify scored result has score >= anchor_bonus
5. `test_scored_custom_anchor_bonus` — passing `anchor_bonus=0.20` increases the bonus. Verify the composite score reflects the custom value
6. `test_scored_empty_results` — when `recall_by_anchor()` returns empty list, scored returns empty list
7. `test_scored_with_semantic_query` — when `semantic_query` is provided, results have `semantic_similarity > 0` for matching episodes
8. `test_scored_without_semantic_query` — when no `semantic_query`, `semantic_similarity == 0.0` for all results (structural match only)

**`recall_by_anchor_scored()` — signal propagation (4 tests):**

9. `test_scored_trust_weight_propagated` — mock trust_network returns 0.9; verify `trust_weight` in RecallScore is 0.9
10. `test_scored_hebbian_weight_propagated` — mock hebbian_router returns 0.8; verify `hebbian_weight` in RecallScore is 0.8
11. `test_scored_recency_weight_computed` — recent episode (timestamp = now) has higher `recency_weight` than old episode (timestamp = 30 days ago)
12. `test_scored_temporal_match_bonus` — episode with matching `watch_section` gets temporal match bonus in composite score

**Merge step — cognitive_agent.py (6 tests):**

These tests mock the cognitive agent's `_observe_memory` method by testing the merge logic in isolation. Extract the merge block into a helper or test it via the full method with mocked dependencies.

For these tests, create a minimal mock of the cognitive agent's recall pipeline. The key assertion is about the merge behavior, not the full pipeline.

13. `test_merge_scored_anchor_and_semantic` — when both `_anchor_episodes` (list[RecallScore]) and `scored_results` (list[RecallScore]) have entries, the merged list is sorted by composite_score. A high-scoring semantic result outranks a low-scoring anchor result.
14. `test_merge_deduplicates_by_id` — an episode appearing in both anchor and semantic results appears only once in the merged list (the anchor version, which has the anchor_bonus)
15. `test_merge_bf155_temporal_filter` — in scored merge, semantic episodes with mismatched `watch_section` are excluded (BF-155 preserved)
16. `test_merge_fallback_unscored` — when `_anchor_episodes` is `list[Episode]` (not RecallScore), falls back to legacy position-based merge (backward compatibility)
17. `test_merge_empty_anchor` — when `_anchor_episodes` is None, semantic results pass through unchanged
18. `test_merge_empty_semantic` — when `scored_results` is empty but `_anchor_episodes` has scored results, episodes come from anchor results only

**Testing the merge logic:**

For tests 13–18, the simplest approach is to test the merge logic directly rather than through the full cognitive pipeline. Create a standalone test helper that replicates the merge block from Section 2b:

```python
def _merge_recall(
    anchor_results: list | None,
    scored_results: list[RecallScore],
    episodes: list[Episode],
    query_watch_section: str = "",
) -> tuple[list[RecallScore], list[Episode]]:
    """Extract of the AD-603 merge logic for isolated testing."""
    from probos.types import RecallScore as _RecallScore

    if not anchor_results:
        return scored_results, episodes

    _is_scored = bool(anchor_results and isinstance(anchor_results[0], _RecallScore))

    if _is_scored and scored_results:
        _seen_ids = {rs.episode.id for rs in anchor_results}
        _merged = list(anchor_results)
        for rs in scored_results:
            if rs.episode.id in _seen_ids:
                continue
            if (
                query_watch_section
                and getattr(rs.episode, "anchors", None)
                and getattr(rs.episode.anchors, "watch_section", "")
                and rs.episode.anchors.watch_section != query_watch_section
            ):
                continue
            _merged.append(rs)
            _seen_ids.add(rs.episode.id)
        _merged.sort(key=lambda r: r.composite_score, reverse=True)
        return _merged, [rs.episode for rs in _merged]
    else:
        _seen_ids = {getattr(ep, 'id', id(ep)) for ep in anchor_results}
        for ep in episodes:
            if getattr(ep, 'id', id(ep)) in _seen_ids:
                continue
            if (
                query_watch_section
                and getattr(ep, "anchors", None)
                and getattr(ep.anchors, "watch_section", "")
                and ep.anchors.watch_section != query_watch_section
            ):
                continue
            anchor_results.append(ep)
            _seen_ids.add(getattr(ep, 'id', id(ep)))
        return [], anchor_results
```

This test helper should live inside the test file, not in production code.

---

## Engineering Principles Compliance

- **SOLID/S** — `recall_by_anchor_scored()` has single responsibility: score anchor results. It delegates retrieval to `recall_by_anchor()` and scoring to `score_recall()`.
- **SOLID/O** — `recall_by_anchor()` is unchanged. New functionality is additive via `recall_by_anchor_scored()`.
- **SOLID/D** — trust_network and hebbian_router are injected via parameters, not accessed through runtime internals.
- **Fail Fast** — Semantic similarity lookup failures degrade to `sim=0.0` (structural match only). Keyword search failures degrade to `kw_hits=0`. The scoring pipeline never crashes — it degrades to anchor_confidence + recency + anchor_bonus.
- **Law of Demeter** — `recall_by_anchor_scored()` accesses only its own `self._collection` and injected parameters. The merge step in cognitive_agent.py accesses `_anchor_episodes` and `scored_results` — both local variables in the same method scope.
- **DRY** — The trust/hebbian/recency scoring logic in Section 1 parallels `recall_weighted()` lines 1839–1886. This is acceptable duplication per the note in Section 1. A shared `_score_episodes()` helper would be a separate refactoring AD.

---

## Verified Signatures and Paths

| Symbol | Location | Signature |
|--------|----------|-----------|
| `recall_by_anchor()` | episodic.py:1940 | `async def recall_by_anchor(self, *, department, channel, trigger_type, trigger_agent, watch_section, agent_id, participants, time_range, semantic_query, limit) -> list[Episode]` |
| `score_recall()` | episodic.py:1693 | `@staticmethod def score_recall(episode, semantic_similarity, keyword_hits=0, trust_weight=0.5, hebbian_weight=0.5, recency_weight=0.0, weights=None, convergence_bonus=0.10, temporal_match=False, temporal_match_weight=0.10, temporal_mismatch_penalty=0.15, query_has_temporal_intent=False, importance=5, importance_weight=0.0) -> RecallScore` |
| `recall_weighted()` | episodic.py:1775 | `async def recall_weighted(self, agent_id, query, *, trust_network, hebbian_router, intent_type, k, context_budget, weights, anchor_confidence_gate, composite_score_floor, max_recall_episodes, recall_quality_floor, convergence_bonus, query_watch_section, temporal_match_weight, temporal_mismatch_penalty) -> list[RecallScore]` |
| `RecallScore` | types.py:388 | `@dataclass class RecallScore: episode, semantic_similarity, keyword_hits, trust_weight, hebbian_weight, recency_weight, anchor_confidence, composite_score` |
| `_try_anchor_recall()` | cognitive_agent.py:4655 | `async def _try_anchor_recall(self, query, agent_mem_id) -> tuple[list \| None, str]` |
| `_observe_memory merge` | cognitive_agent.py:4469 | Position-based merge of `_anchor_episodes` and `episodes` |
| `keyword_search()` | episodic.py:1597 | `async def keyword_search(self, query, k=10) -> list[tuple[str, float]]` |
| `compute_anchor_confidence()` | cognitive/anchor_quality.py | Called inside `score_recall()` — not directly referenced by AD-603 |
| `reformulate_query()` | knowledge/embeddings.py | Called in `recall_for_agent_scored()` and reused in Section 1 |

---

## Tracker Updates

After all tests pass:

1. **PROGRESS.md** — Add entry:
   ```
   | AD-603 | Anchor Recall Composite Scoring | recall_by_anchor_scored() applies full composite scoring; merge uses scores not positions. 18 tests. | CLOSED |
   ```

2. **docs/development/roadmap.md** — Update AD-603 row status to Closed.

3. **DECISIONS.md** — Add entry:
   ```
   ## AD-603: Anchor Recall Composite Scoring

   **Decision:** Added recall_by_anchor_scored() that applies the full score_recall() composite pipeline to anchor-retrieved episodes. Merge step uses composite scores for unified ranking instead of positional ordering. Anchor results get a small bonus (0.08) for matching a structured query.

   **Rationale:** Anchor-recalled episodes entered the merge step with no quality score, while semantic results had full composite scores. This made the merge compare scored vs unscored results — low-quality anchor matches outranked high-quality semantic matches by position alone. Now both populations compete on equal scoring terms.

   **Alternative considered:** Modifying recall_by_anchor() to return RecallScore directly. Rejected — other callers (dream consolidation, guided reminiscence) use it for bulk enumeration and don't need the scoring overhead.
   ```
