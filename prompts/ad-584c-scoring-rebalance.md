# AD-584c: Recall Scoring Rebalance

**Scope:** Rebalance composite scoring weights + add convergence bonus + wire config weights into `score_recall()`
**Prerequisite:** AD-584a/b (complete — QA embedding model swap + query reformulation)
**Research:** `docs/research/recall-pipeline-research-synthesis.md` (Tier 3), `docs/research/memory-retrieval-research.md`
**Qualification evidence:** Post-AD-584a/b qual run (2026-04-10) shows systemic failure of all memory recall probes across 15 agents: `seeded_recall` 0.000–0.147, `temporal_reasoning` 0.000–0.013, `knowledge_update` 0.000–0.500, `cross_agent_synthesis` 0.167–0.500. `retrieval_accuracy_benchmark` passes (0.300–0.500) because it calls `recall_for_agent()` directly, bypassing the composite scoring pipeline. All non-memory probes pass.

---

## Problem

The composite scoring formula in `score_recall()` was tuned for `all-MiniLM-L6-v2` (sentence-similarity model). AD-584a swapped to `multi-qa-MiniLM-L6-cos-v1` (QA-trained), which produces different similarity score distributions. The qualification probe failure pattern proves the issue is in the **scoring/filtering pipeline**, not raw retrieval — `retrieval_accuracy_benchmark` (which bypasses scoring) passes.

Three root causes identified:

1. **Weight distribution mismatch:** Current weights give semantic similarity only 35% of the composite score. With the QA model producing more reliable semantic signals, this under-weights the primary relevance indicator. Trust (15%) and Hebbian (10%) dominate for newly seeded probe episodes that have default 0.5 values, compressing composite scores into a narrow band where the anchor_confidence_gate filters them.

2. **No convergence bonus:** Episodes found by both semantic search AND keyword search (FTS5) have stronger evidence of relevance. The current scoring treats these channels independently — no spreading-activation bonus for multi-pathway evidence accumulation.

3. **Config weights disconnected:** `config.memory.recall_weights` exists in `config.py:278–285` but `score_recall()` at `episodic.py:1511` uses hardcoded defaults as fallback. While `cognitive_agent.py:2566` passes config weights via `recall_weighted()`, there's no guarantee all recall paths honor config — and the defaults should match the rebalanced weights.

---

## Solution

### Change 1: Rebalance scoring weights

**File: `src/probos/cognitive/episodic.py`** — `score_recall()` method (~line 1511)

Update the hardcoded default weights dictionary:

```python
# CURRENT (line 1511-1513):
w = weights or {
    "semantic": 0.35, "keyword": 0.10, "trust": 0.15,
    "hebbian": 0.10, "recency": 0.20, "anchor": 0.10,
}

# NEW:
w = weights or {
    "semantic": 0.35, "keyword": 0.20, "trust": 0.10,
    "hebbian": 0.05, "recency": 0.15, "anchor": 0.15,
}
```

Also update the docstring at line 1506 to reflect the new formula.

**Rationale for each change (from research synthesis):**
- `keyword`: 0.10 → **0.20** — QA tasks benefit from exact term matching. Keywords are orthogonal to semantic similarity and provide high-precision complementary signal.
- `trust`: 0.15 → **0.10** — Trust is a source-quality signal, not a content-relevance signal. It should influence but not dominate retrieval ranking.
- `hebbian`: 0.10 → **0.05** — Hebbian weight reflects routing frequency, not episode relevance. For newly seeded episodes (default 0.5), this injects noise.
- `recency`: 0.20 → **0.15** — Recency is important but the exponential decay (`exp(-age_hours / 168)`) already privileges recent episodes. 20% over-weights temporal proximity relative to content relevance.
- `anchor`: 0.10 → **0.15** — Per encoding specificity research (Tulving & Thomson 1973), retrieval cues that match encoding context are primary cues, not tiebreakers.
- `semantic`: stays at **0.35** — Already the largest single weight. The QA model improvement comes from *better* similarity scores, not from needing a higher weight.

**Constraint:** Weights must sum to 1.0 (excluding convergence bonus). 0.35 + 0.20 + 0.10 + 0.05 + 0.15 + 0.15 = 1.00. Verified.

### Change 2: Add convergence bonus

**File: `src/probos/cognitive/episodic.py`** — `score_recall()` method

Add a `convergence_bonus` parameter and logic. An episode found by multiple retrieval channels (semantic + keyword) gets a bonus, reflecting spreading activation / multi-pathway evidence accumulation.

```python
@staticmethod
def score_recall(
    episode: Episode,
    semantic_similarity: float,
    keyword_hits: int = 0,
    trust_weight: float = 0.5,
    hebbian_weight: float = 0.5,
    recency_weight: float = 0.0,
    weights: dict[str, float] | None = None,
    convergence_bonus: float = 0.10,  # NEW: bonus for multi-channel evidence
) -> RecallScore:
```

After computing `composite`, add:

```python
# AD-584c: Convergence bonus — multi-pathway evidence accumulation.
# Episodes found by BOTH semantic AND keyword channels get a bonus.
if semantic_similarity > 0.0 and keyword_hits > 0:
    composite += convergence_bonus
```

**File: `src/probos/types.py`** (or wherever `RecallScore` is defined) — verify that `RecallScore` can hold scores > 1.0, or cap it. Check the actual `RecallScore` definition first. If it's a plain dataclass with `composite_score: float`, no change needed — scores > 1.0 just mean stronger evidence.

### Change 3: Update config defaults

**File: `src/probos/config.py`** — `MemoryConfig` (~line 278)

Update `recall_weights` defaults to match the new formula:

```python
# CURRENT:
recall_weights: dict[str, float] = {
    "semantic": 0.35,
    "keyword": 0.10,
    "trust": 0.15,
    "hebbian": 0.10,
    "recency": 0.20,
    "anchor": 0.10,
}

# NEW:
recall_weights: dict[str, float] = {
    "semantic": 0.35,
    "keyword": 0.20,
    "trust": 0.10,
    "hebbian": 0.05,
    "recency": 0.15,
    "anchor": 0.15,
}
```

Add convergence bonus to config:

```python
recall_convergence_bonus: float = 0.10  # AD-584c: bonus for multi-channel hits
```

### Change 4: Wire convergence bonus from config through recall_weighted

**File: `src/probos/cognitive/episodic.py`** — `recall_weighted()` method (~line 1541)

Add `convergence_bonus` parameter:

```python
async def recall_weighted(
    self,
    agent_id: str,
    query: str,
    *,
    trust_network: Any = None,
    hebbian_router: Any = None,
    intent_type: str = "",
    k: int = 5,
    context_budget: int = 4000,
    weights: dict[str, float] | None = None,
    anchor_confidence_gate: float = 0.0,
    convergence_bonus: float = 0.10,  # NEW
) -> list[RecallScore]:
```

Pass it through to `score_recall()`:

```python
rs = self.score_recall(
    episode=ep,
    semantic_similarity=sim,
    keyword_hits=kw_hits,
    trust_weight=tw,
    hebbian_weight=hw,
    recency_weight=rw,
    weights=weights,
    convergence_bonus=convergence_bonus,  # NEW
)
```

**File: `src/probos/cognitive/cognitive_agent.py`** (~line 2558-2568)

Pass convergence bonus from config:

```python
scored_results = await em.recall_weighted(
    _mem_id, query,
    trust_network=trust_net,
    hebbian_router=heb_router,
    intent_type=intent.intent,
    k=_tier_params.get("k", 5),
    context_budget=_tier_params.get("context_budget", 4000),
    weights=getattr(mem_cfg, 'recall_weights', None) if mem_cfg else None,
    anchor_confidence_gate=_tier_params.get("anchor_confidence_gate", 0.3),
    convergence_bonus=getattr(mem_cfg, 'recall_convergence_bonus', 0.10) if mem_cfg else 0.10,  # NEW
)
```

---

## Scope Boundaries

- **DO** update scoring weights (defaults and config)
- **DO** add convergence bonus
- **DO** wire config values through the full call chain
- **DO NOT** change the embedding model (AD-584a — already done)
- **DO NOT** change query reformulation (AD-584b — already done)
- **DO NOT** change `relevance_threshold` (0.7) or `agent_recall_threshold` (0.15)
- **DO NOT** change recall tier parameters (k, context_budget, anchor_confidence_gate)
- **DO NOT** embed reflection alongside user_input (AD-584d — separate prompt)
- **DO NOT** add LLM calls to the scoring pipeline

---

## Test Plan

**File: `tests/test_ad584c_scoring_rebalance.py`** — new test file

### Group 1: Weight Rebalance (8 tests)

1. `test_score_recall_default_weights_sum_to_one` — Verify default weights dict sums to 1.0.
2. `test_score_recall_new_keyword_weight` — Episode with keyword_hits=2 scores higher than before (old keyword contribution: 0.10 * 0.67 = 0.067; new: 0.20 * 0.67 = 0.134).
3. `test_score_recall_reduced_trust_weight` — With trust_weight=1.0, composite contribution from trust is 0.10 (was 0.15).
4. `test_score_recall_reduced_hebbian_weight` — With hebbian_weight=1.0, composite contribution from hebbian is 0.05 (was 0.10).
5. `test_score_recall_increased_anchor_weight` — Episode with anchor_confidence=0.8, anchor contribution is 0.12 (was 0.08).
6. `test_score_recall_reduced_recency_weight` — Recency contribution is 0.15 * recency_weight (was 0.20).
7. `test_score_recall_custom_weights_override` — Passing explicit `weights=` dict overrides defaults.
8. `test_config_default_weights_match_score_recall` — `MemoryConfig().recall_weights` matches the defaults in `score_recall()`.

### Group 2: Convergence Bonus (5 tests)

9. `test_convergence_bonus_both_channels` — Episode with `semantic_similarity > 0` AND `keyword_hits > 0` gets +0.10 bonus.
10. `test_no_convergence_bonus_semantic_only` — Episode with `semantic_similarity > 0` but `keyword_hits == 0`: no bonus.
11. `test_no_convergence_bonus_keyword_only` — Episode with `semantic_similarity == 0.0` but `keyword_hits > 0`: no bonus.
12. `test_convergence_bonus_configurable` — `convergence_bonus=0.05` produces +0.05 (not hardcoded).
13. `test_convergence_bonus_zero_disables` — `convergence_bonus=0.0` produces no bonus.

### Group 3: Config Wiring (4 tests)

14. `test_config_convergence_bonus_default` — `MemoryConfig().recall_convergence_bonus == 0.10`.
15. `test_recall_weighted_passes_convergence_bonus` — Mock `score_recall()` and verify `convergence_bonus` kwarg is passed.
16. `test_recall_weighted_passes_config_weights` — Mock `score_recall()` and verify custom weights dict is passed.
17. `test_cognitive_agent_passes_convergence_bonus` — Integration test: cognitive agent recall path passes config convergence bonus.

### Group 4: Regression — Probe Signal Improvement (3 tests)

18. `test_probe_episode_scores_above_gate` — A probe-style episode (BF-133 anchor fields, freshly seeded) with realistic QA semantic similarity (0.5–0.7) produces a composite score that passes `anchor_confidence_gate=0.3`.
19. `test_convergence_boosts_ranking` — Episode found by both channels ranks higher than one found by semantic only, all else equal.
20. `test_keyword_heavy_episode_promoted` — Episode with 3+ keyword hits ranks meaningfully higher with new weights vs old.

**Total: 20 tests.**

---

## Engineering Principles Checklist

- **Single Responsibility:** `score_recall()` remains a pure scoring function. Convergence bonus is computed in-place, not delegated to a new class.
- **Open/Closed:** Scoring weights and convergence bonus are configurable via `MemoryConfig` — no need to edit source to tune. Extension via config, not modification.
- **Dependency Inversion:** `score_recall()` receives weights as a dict parameter — doesn't import or depend on `config.py` directly.
- **Law of Demeter:** No new deep attribute chains. Convergence bonus flows through public method parameters.
- **DRY:** Config defaults and `score_recall()` defaults are updated in both locations to stay synchronized. Test 8 verifies they match.
- **Fail Fast:** If weights don't sum to ~1.0 (within floating point tolerance), log a warning but don't crash (scoring still works with any weights — the ranking order is what matters, not the absolute scale).
- **Defense in Depth:** `convergence_bonus` clamped to `max(0.0, convergence_bonus)` to prevent negative bonuses from config typos.
