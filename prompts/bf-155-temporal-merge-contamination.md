# BF-155: Temporal Recall Merge Contamination — Wrong-Watch Episodes Outscore Correct Watch

## Issue

GitHub Issue #176. Bug tracker entry in `docs/development/roadmap.md`.

## Problem

`temporal_reasoning_probe` shows ~40% watch confusion rate across agents. Three compounding causes:

1. **Merge contamination** (`cognitive_agent.py:2794-2801`): `_recall_relevant_memories()` merges anchor-filtered episodes (correctly watch-filtered via ChromaDB `where` clause in `recall_by_anchor()`) with **unfiltered** semantic episodes from `recall_weighted()`. The merge is a naive union — semantic episodes from the wrong watch enter the final recall set.

2. **Weak temporal match bonus** (BF-147): `temporal_match_weight` default is +0.10. Wrong-watch episodes frequently outscore right-watch episodes by 0.15+ on semantic similarity alone. A 0.10 bonus is insufficient discrimination.

3. **No mismatch suppression**: When a query has explicit temporal intent ("during first watch") and an episode is from a different watch, the episode receives no penalty — it simply misses the +0.10 bonus (+0.0 instead of +0.10). Research documents (`docs/research/memory-retrieval-research.md` Section 4.2, 8.1, 8.2) recommend actively penalizing contradictory temporal context. This has never been implemented.

## Fix — 3 Changes

### Change 1: Pre-merge watch filtering in `_recall_relevant_memories()`

**File:** `src/probos/cognitive/cognitive_agent.py`
**Location:** Lines 2794-2801, the AD-570c merge step

**Current code (lines 2794-2801):**
```python
# AD-570c: Merge anchor recall with semantic recall
if _anchor_episodes:
    _seen_ids = {getattr(ep, 'id', id(ep)) for ep in _anchor_episodes}
    for ep in episodes:
        if getattr(ep, 'id', id(ep)) not in _seen_ids:
            _anchor_episodes.append(ep)
            _seen_ids.add(getattr(ep, 'id', id(ep)))
    episodes = _anchor_episodes
```

**Replace with:**
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

**Logic:**
- `_query_watch_section` is already extracted at line 2654 from `_try_anchor_recall()`.
- Only filter when ALL conditions hold: (a) query has temporal intent (`_query_watch_section` non-empty), (b) episode has anchors with a watch_section, (c) the watch sections differ.
- Episodes with no anchors or no watch_section pass through (no penalty for missing temporal context).
- Debug logging with BF-155 prefix for traceability.

### Change 2: Temporal mismatch suppression penalty in `score_recall()`

**File:** `src/probos/cognitive/episodic.py`
**Location:** `score_recall()` method starting at line 1494

**Step 2a — Add two new parameters to `score_recall()` signature (line ~1503-1504):**

After the existing `temporal_match_weight` parameter, add:
```python
    temporal_mismatch_penalty: float = 0.15,  # BF-155: penalty when query watch differs from episode watch
    query_has_temporal_intent: bool = False,   # BF-155: True when query_watch_section is non-empty
```

Full updated signature:
```python
    def score_recall(
        self,
        episode: "Episode",
        semantic_similarity: float,
        keyword_hits: int = 0,
        trust_weight: float = 0.5,
        hebbian_weight: float = 0.5,
        recency_weight: float = 0.0,
        weights: dict[str, float] | None = None,
        convergence_bonus: float = 0.10,
        temporal_match: bool = False,
        temporal_match_weight: float = 0.10,
        temporal_mismatch_penalty: float = 0.15,  # BF-155
        query_has_temporal_intent: bool = False,   # BF-155
    ) -> RecallScore:
```

**Step 2b — Add mismatch penalty logic after the temporal match bonus (line ~1542):**

Replace:
```python
        # BF-147: temporal match bonus — query temporal cue matches episode anchor
        if temporal_match:
            composite += max(0.0, temporal_match_weight)
```

With:
```python
        # BF-147: temporal match bonus — query temporal cue matches episode anchor
        if temporal_match:
            composite += max(0.0, temporal_match_weight)
        # BF-155: temporal mismatch suppression — penalize episodes from wrong watch
        # when query has explicit temporal intent. Only penalize when the episode
        # HAS a watch_section that DIFFERS from the query — don't penalize episodes
        # with no temporal context.
        elif query_has_temporal_intent and not temporal_match:
            _ep_watch = (
                getattr(episode, "anchors", None)
                and getattr(episode.anchors, "watch_section", "")
            )
            if _ep_watch:
                composite -= min(temporal_mismatch_penalty, composite)  # clamp: don't go below 0
```

**Logic:**
- `elif` ensures it only applies when `temporal_match` is `False`.
- `query_has_temporal_intent` is `True` when the query had a watch_section extracted by `parse_anchor_query()`.
- Only penalizes when the episode actually has a watch_section that differs. Episodes with no watch_section are not penalized.
- `min(penalty, composite)` prevents composite score from going negative.

**Step 2c — Wire new params through `recall_weighted()` at line ~1650-1661:**

In `recall_weighted()`, update the `score_recall()` call (line ~1650) to pass the new parameters:

```python
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
                temporal_mismatch_penalty=temporal_mismatch_penalty,      # BF-155
                query_has_temporal_intent=bool(query_watch_section),       # BF-155
            )
```

**Step 2d — Add `temporal_mismatch_penalty` parameter to `recall_weighted()` signature (line ~1572):**

After the existing `temporal_match_weight` parameter:
```python
        temporal_mismatch_penalty: float = 0.15,  # BF-155: penalty for temporal contradiction
```

### Change 3: Increase `temporal_match_weight` default and add mismatch config

**File:** `src/probos/config.py`
**Location:** `MemoryConfig` class, line 287

**Replace:**
```python
    recall_temporal_match_weight: float = 0.10  # BF-147: bonus for temporal cue match in score_recall()
```

**With:**
```python
    recall_temporal_match_weight: float = 0.25       # BF-147→BF-155: bonus for temporal cue match in score_recall()
    recall_temporal_mismatch_penalty: float = 0.15   # BF-155: penalty when query watch differs from episode watch
```

**Wire into `cognitive_agent.py`:** Update the `recall_weighted()` call at line ~2748-2749 to also pass:
```python
    temporal_mismatch_penalty=getattr(mem_cfg, 'recall_temporal_mismatch_penalty', 0.15) if mem_cfg else 0.15,
```

And update the existing `temporal_match_weight` line to use the new default:
```python
    temporal_match_weight=getattr(mem_cfg, 'recall_temporal_match_weight', 0.25) if mem_cfg else 0.25,
```

## Tests

**New file:** `tests/test_bf155_temporal_merge.py`

Write the following tests (use existing test patterns from `tests/test_bf147_temporal_probe.py` and `tests/test_ad584c_scoring_rebalance.py` for fixture patterns):

### TestPreMergeFiltering (4 tests)

1. **`test_wrong_watch_excluded_from_merge`** — Create anchor episodes with `watch_section="first"`, semantic episodes with `watch_section="second_dog"`, set `_query_watch_section="first"`. After merge, verify no `second_dog` episodes in final list.

2. **`test_no_watch_episodes_pass_through`** — Semantic episodes with empty `watch_section` (or no anchors) should NOT be excluded. They pass the filter because they have no contradicting temporal context.

3. **`test_no_temporal_intent_no_filtering`** — When `_query_watch_section` is empty, all semantic episodes pass through regardless of their watch_section. No filtering without explicit temporal intent.

4. **`test_duplicate_dedup_preserved`** — Episodes already in anchor set are still deduplicated by ID, even when watch filtering is active.

### TestMismatchPenalty (5 tests)

5. **`test_mismatch_penalty_applied`** — `score_recall()` with `temporal_match=False`, `query_has_temporal_intent=True`, episode has `watch_section="second_dog"` (different from query). Verify `composite_score` is reduced by penalty amount.

6. **`test_no_penalty_when_no_temporal_intent`** — `score_recall()` with `query_has_temporal_intent=False`. No penalty regardless of watch_section mismatch.

7. **`test_no_penalty_when_episode_has_no_watch`** — Episode with `anchors.watch_section=""` or `anchors=None`. No penalty applied (can't determine mismatch without episode temporal context).

8. **`test_penalty_clamped_to_zero`** — Episode with very low composite_score (e.g., 0.05). Penalty of 0.15 should not make composite negative — clamps to 0.0.

9. **`test_match_bonus_and_mismatch_penalty_mutually_exclusive`** — An episode either gets the match bonus OR the mismatch penalty, never both.

### TestWeightIncrease (3 tests)

10. **`test_temporal_match_weight_default_025`** — Verify `MemoryConfig().recall_temporal_match_weight == 0.25`.

11. **`test_temporal_mismatch_penalty_default_015`** — Verify `MemoryConfig().recall_temporal_mismatch_penalty == 0.15`.

12. **`test_match_vs_mismatch_swing`** — `score_recall()` on two identical episodes with same semantic_similarity, one matching watch (gets +0.25), one mismatching watch (gets -0.15). Verify composite difference is 0.40.

### TestRecallWeightedIntegration (2 tests)

13. **`test_recall_weighted_passes_mismatch_params`** — Verify `recall_weighted()` passes `temporal_mismatch_penalty` and `query_has_temporal_intent` to `score_recall()`. Use a mock or subclass to intercept.

14. **`test_recall_weighted_mismatch_penalty_from_config`** — Pass custom penalty value through, verify it reaches `score_recall()`.

### Fixtures

Use `EpisodicMemory.__new__()` pattern from `test_ad584c_scoring_rebalance.py` to create a minimal `EpisodicMemory` instance for `score_recall()` tests. Create `Episode` instances with `AnchorFrame(watch_section=...)` for temporal context. Import from `probos.types` (Episode, AnchorFrame, RecallScore) and `probos.config` (MemoryConfig).

## Verification

```bash
python -m pytest tests/test_bf155_temporal_merge.py -v
```

Then run the full qualification probe regression:
```bash
python -m pytest tests/test_bf147_temporal_probe.py tests/test_bf152_temporal_keyword.py tests/test_ad584c_scoring_rebalance.py -v
```

## Files Modified

| File | Changes |
|------|---------|
| `src/probos/cognitive/cognitive_agent.py` | Pre-merge watch filtering at merge step (lines 2794-2801) |
| `src/probos/cognitive/episodic.py` | `score_recall()`: new params `temporal_mismatch_penalty`, `query_has_temporal_intent` + penalty logic. `recall_weighted()`: new param + wiring |
| `src/probos/config.py` | `recall_temporal_match_weight` 0.10→0.25, new `recall_temporal_mismatch_penalty` field |
| `tests/test_bf155_temporal_merge.py` | **NEW** — 14 tests across 4 classes |

## Engineering Principles

- **Defense in Depth:** Three independent layers — pre-merge filter, scoring penalty, weight calibration. Each effective alone.
- **Fail Fast:** Mismatch penalty makes wrong-watch episodes visibly degraded in composite scores.
- **Open/Closed:** `score_recall()` and `recall_weighted()` extended with new optional params, all existing callers unaffected (defaults preserve backward compatibility).
- **Single Responsibility:** Filtering at merge boundary (cognitive_agent.py), scoring at scoring boundary (episodic.py), config at config boundary (config.py).
- **DRY:** Mismatch check reuses existing `watch_section` field comparison pattern from BF-147.
- **No new imports required** — all files already import the needed modules.
